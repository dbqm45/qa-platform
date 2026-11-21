"""Local Runner: executes a compiled specification in this process (TASK-035, TASK-036).

Flow of one execution::

    PENDING   -> checks: specification READY, plan matches, adapters selectable
    RUNNING   -> adapters validated and prepared
                 each test case: start hooks -> steps in order -> finish hooks
                 -> evidence
    cleanup   -> always, in reverse order; errors recorded separately
    PASSED | FAILED | ERROR | CANCELLED   (persisted at every transition)

A step implementation receives a :class:`StepContext` and obtains the resource
it needs with ``context.resource("browser")``.
"""

import os
import secrets
import time
from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from qa_core.redaction import MissingSecretError, Redactor, resolve_references
from qa_core.steps.registry import StepArguments, StepParameterError, StepRegistry
from qa_execution.adapters import ExecutionContext, TestAdapter
from qa_execution.errors import TestEnvironmentError, classify, describe
from qa_execution.log import LOG_FILENAME, ExecutionLog
from qa_execution.registry import AdapterRegistry, AdapterSelection, AdapterSelectionError
from qa_execution.timeouts import (
    CLEANUP_SECONDS,
    GRACE_SECONDS,
    HOOK_SECONDS,
    PREPARE_SECONDS,
    Budget,
    deadline,
)
from qa_schemas.compilation import CompiledSpecification
from qa_schemas.enums import ExecutionStatus, FailureClassification
from qa_schemas.evidence import EvidenceReference
from qa_schemas.execution import TestExecution
from qa_schemas.plan import ExecutionPlan
from qa_schemas.project import Environment
from qa_schemas.results import ExecutionReport, Failure, StepResult, TestResult
from qa_schemas.specification import Step, TestCase, TestSpecification

Clock = Callable[[], datetime]
S = ExecutionStatus
C = FailureClassification


class NotExecutableError(Exception):
    """The request cannot be executed at all; nothing was started."""


class ExecutionStore(Protocol):
    """Where execution metadata is persisted (e.g. ``ExecutionRepository``)."""

    def add(self, execution: TestExecution) -> None: ...

    def update(self, execution: TestExecution) -> None: ...


def new_execution_id(now: datetime) -> str:
    """Sortable, unique id such as ``20261121-143005-a1b2c3`` (UTC)."""
    return f"{now.astimezone(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


@dataclass(frozen=True)
class ExecutionRequest:
    project_id: str
    compiled: CompiledSpecification
    plan: ExecutionPlan
    environment: Environment


@dataclass
class StepContext:
    """Passed to every step implementation as its first argument."""

    execution: ExecutionContext
    test_case: TestCase
    step: Step
    _providers: dict[str, TestAdapter] = field(repr=False)

    def mark_secret(self, value: str) -> None:
        """Treat ``value`` as a secret: it is masked in results, reports and evidence."""
        self.execution.redactor.add(value)

    def resource(self, capability: str) -> Any:
        """The resource of the adapter that provides ``capability``."""
        adapter = self._providers.get(capability)
        if adapter is None:
            raise LookupError(f"no adapter provides capability {capability!r} in this execution")
        return adapter.resource


class LocalRunner:
    def __init__(
        self,
        steps: StepRegistry,
        adapters: AdapterRegistry,
        *,
        evidence_root: Path,
        store: ExecutionStore | None = None,
        clock: Clock = lambda: datetime.now(UTC),
        id_factory: Callable[[datetime], str] = new_execution_id,
        adapter_config: Mapping[str, Mapping[str, Any]] | None = None,
        environment_variables: Mapping[str, str] | None = None,
    ) -> None:
        self._adapter_config = dict(adapter_config or {})
        self._variables = environment_variables if environment_variables is not None else os.environ
        self._steps = steps
        self._adapters = adapters
        self._evidence_root = evidence_root
        self._store = store
        self._clock = clock
        self._new_id = id_factory

    # --- Public --------------------------------------------------------------

    def run(self, request: ExecutionRequest) -> ExecutionReport:
        """Execute the request. Raises ``NotExecutableError`` before starting anything
        if the specification is not READY or the request is inconsistent."""
        selection = self._check(request)
        spec, plan = request.compiled.specification, request.plan

        now = self._clock()
        execution = TestExecution(
            id=self._new_id(now),
            project_id=request.project_id,
            specification_id=spec.id,
            plan_id=plan.id,
            mode=plan.mode,
            category=plan.category,
            environment=request.environment.name,
            created_at=now,
        )
        self._persist(execution, new=True)

        evidence_dir = self._evidence_root / execution.id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        context = ExecutionContext(
            execution_id=execution.id,
            environment=request.environment,
            settings=plan.settings,
            evidence_dir=evidence_dir,
            adapter_config=self._adapter_config,
            redactor=Redactor(),
        )
        adapters = [adapter_class() for adapter_class in selection.adapters]
        providers = {
            capability: next(a for a in adapters if type(a) is adapter_class)
            for capability, adapter_class in selection.provider_of.items()
        }

        log = ExecutionLog(evidence_dir / LOG_FILENAME, context.redactor, self._clock)
        log.event(
            "execution-started",
            execution_id=execution.id,
            project_id=execution.project_id,
            specification_id=spec.id,
            scenario=f"{spec.source.path}:{spec.source.line}",
            plan_id=plan.id,
            mode=plan.mode.value,
            category=plan.category.value,
            environment=execution.environment,
            adapters=[adapter.name for adapter in adapters],
            step_timeout_seconds=plan.settings.step_timeout_seconds,
            timeout_seconds=plan.settings.timeout_seconds,
        )
        execution = self._transition(execution, S.RUNNING, started_at=self._clock())
        run = _Run(self._steps, self._clock, context, adapters, providers, self._variables, log)
        try:
            try:
                results, failure = run.execute(spec, plan.settings.fail_fast)
            except KeyboardInterrupt:
                log.event("execution-interrupted")
                _log_cleanup(log, run.cleanup())
                log.event("execution-finished", status=S.CANCELLED.value)
                self._finish(execution, S.CANCELLED)
                raise
            cleanup_errors = run.cleanup()
            _log_cleanup(log, cleanup_errors)

            report = ExecutionReport(
                execution=self._finish(execution, _overall(results, failure)),
                results=tuple(results),
                failure=failure,
                cleanup_errors=tuple(cleanup_errors),
            )
            log.event(
                "execution-finished",
                status=report.execution.status.value,
                failure=failure.message if failure else None,
                counts=dict(Counter(r.status.value for r in results)),
            )
        finally:
            log.close()
        # Secrets become known while steps run, so free text is masked at the end.
        return redact_report(report, context.redactor)

    # --- Internals -----------------------------------------------------------

    def _check(self, request: ExecutionRequest) -> AdapterSelection:
        compiled, plan = request.compiled, request.plan
        spec = compiled.specification
        if not compiled.status.is_executable:
            reasons = "; ".join(compiled.reasons) or "no reason recorded"
            raise NotExecutableError(
                f"specification {spec.id!r} is {compiled.status.value} and cannot be executed: "
                f"{reasons}"
            )
        if plan.specification_id != spec.id:
            raise NotExecutableError(
                f"plan {plan.id!r} is for specification {plan.specification_id!r}, not {spec.id!r}"
            )
        if plan.environment != request.environment.name:
            raise NotExecutableError(
                f"plan {plan.id!r} targets environment {plan.environment!r}, "
                f"not {request.environment.name!r}"
            )
        try:
            return self._adapters.select(spec.required_capabilities, allowed=plan.adapters)
        except AdapterSelectionError as error:
            raise NotExecutableError(str(error)) from None

    def _persist(self, execution: TestExecution, *, new: bool = False) -> None:
        if self._store is None:
            return
        if new:
            self._store.add(execution)
        else:
            self._store.update(execution)

    def _transition(self, execution: TestExecution, status: S, **changes: Any) -> TestExecution:
        updated = TestExecution.model_validate(
            execution.model_dump() | {"status": status, **changes}
        )
        self._persist(updated)
        return updated

    def _finish(self, execution: TestExecution, status: S) -> TestExecution:
        return self._transition(execution, status, finished_at=self._clock())


def _log_cleanup(log: ExecutionLog, errors: list[str]) -> None:
    log.event("cleanup-finished", errors=errors)


def _overall(results: list[TestResult], failure: Failure | None) -> S:
    """ERROR > FAILED > CANCELLED > PASSED: a non-passing result is never hidden."""
    statuses = {r.status for r in results}
    if failure is not None or S.ERROR in statuses:
        return S.ERROR
    for status in (S.FAILED, S.CANCELLED):
        if status in statuses:
            return status
    return S.PASSED


class _Run:
    """State of one execution while it runs."""

    def __init__(
        self,
        steps: StepRegistry,
        clock: Clock,
        context: ExecutionContext,
        adapters: list[TestAdapter],
        providers: dict[str, TestAdapter],
        variables: Mapping[str, str],
        log: ExecutionLog,
    ) -> None:
        self.log = log
        self.variables = variables
        self.steps = steps
        self.clock = clock
        self.context = context
        self.adapters = adapters
        self.providers = providers
        self.prepared: list[TestAdapter] = []
        self._cleaned = False
        self.step_timeout = context.settings.step_timeout_seconds
        self.budget = Budget(context.settings.timeout_seconds)

    def _limited(self, wanted: float, message: str) -> AbstractContextManager[None]:
        """A hard limit for one phase, never beyond the execution deadline."""
        seconds, text = self.budget.limit(wanted, message)
        return deadline(seconds, text)

    def execute(
        self, specification: TestSpecification, fail_fast: bool
    ) -> tuple[list[TestResult], Failure | None]:
        cases = specification.test_cases
        self.budget = Budget(self.context.settings.timeout_seconds)  # starts now
        failure = self._validate_and_prepare(specification)
        if failure is not None:
            return [_not_run(case, failure) for case in cases], failure

        results: list[TestResult] = []
        for index, case in enumerate(cases):
            if self.budget.exhausted:
                message = f"execution timeout of {self.budget.seconds:g}s exceeded"
                results.extend(_cancelled(c, f"not run: {message}") for c in cases[index:])
                self._log_cancelled(cases[index:], message)
                return results, Failure(classification=C.ENVIRONMENT_ERROR, message=message)
            result = self._run_case(case)
            results.append(result)
            if fail_fast and result.status is not S.PASSED:
                reason = f"not run: fail_fast after {case.id} did not pass"
                results.extend(_cancelled(c, reason) for c in cases[index + 1 :])
                self._log_cancelled(cases[index + 1 :], reason)
                break
        if self.budget.exhausted and results and results[-1].status is not S.PASSED:
            message = f"execution timeout of {self.budget.seconds:g}s exceeded"
            return results, Failure(classification=C.ENVIRONMENT_ERROR, message=message)
        return results, None

    def cleanup(self) -> list[str]:
        """Clean up every prepared adapter in reverse order; never raises."""
        if self._cleaned:
            return []
        self._cleaned = True
        errors = []
        for adapter in reversed(self.prepared):
            try:
                # Not limited by the execution deadline: cleanup must always get a chance.
                with deadline(
                    CLEANUP_SECONDS, f"cleanup did not finish within {CLEANUP_SECONDS:g}s"
                ):
                    adapter.cleanup()
            except Exception as error:
                errors.append(f"{adapter.name}: {describe(error)}")
        return errors

    # --- Steps ---------------------------------------------------------------

    def _log_cancelled(self, cases: tuple[TestCase, ...], reason: str) -> None:
        for case in cases:
            self.log.event("test-case-cancelled", test_case_id=case.id, reason=reason)

    @property
    def _hook_limit(self) -> float:
        return max(HOOK_SECONDS, self.step_timeout) + GRACE_SECONDS

    def _validate_and_prepare(self, specification: TestSpecification) -> Failure | None:
        spec_problems: list[str] = []
        for adapter in self.adapters:
            try:
                problems: list[str] = adapter.validate(specification)
            except Exception as error:
                problems = [f"validation failed: {describe(error)}"]
            spec_problems.extend(f"{adapter.name}: {p}" for p in problems)
        if spec_problems:
            self.log.event("adapters-rejected-specification", problems=spec_problems)
            return Failure(classification=C.ENVIRONMENT_ERROR, message="; ".join(spec_problems))

        for adapter in self.adapters:
            limit = max(PREPARE_SECONDS, self.step_timeout)
            try:
                with self._limited(limit, f"{adapter.name} did not start within {limit:g}s"):
                    adapter.prepare(self.context)
            except Exception as error:
                self.prepared.append(adapter)  # partially prepared: still clean it up
                status, classification = classify(error)
                if status is S.ERROR and classification is C.TEST_IMPLEMENTATION_ERROR:
                    classification = C.ENVIRONMENT_ERROR
                self.log.event("adapter-failed", adapter=adapter.name, error=describe(error))
                return Failure(
                    classification=classification,
                    message=f"{adapter.name} could not be prepared: {describe(error)}",
                    error_type=type(error).__name__,
                )
            self.prepared.append(adapter)
            self.log.event("adapter-prepared", adapter=adapter.name)
        return None

    def _run_case(self, case: TestCase) -> TestResult:
        self.log.event("test-case-started", test_case_id=case.id, name=case.name)
        result = self._execute_case(case)
        self.log.event(
            "test-case-finished",
            test_case_id=case.id,
            status=result.status.value,
            duration_ms=result.duration_ms,
            classification=result.failure.classification.value if result.failure else None,
            error=result.failure.message if result.failure else None,
            evidence=[str(ref.path) for ref in result.evidence],
            notes=list(result.notes),
        )
        return result

    def _execute_case(self, case: TestCase) -> TestResult:
        started, clock = self.clock(), time.perf_counter()
        steps: list[StepResult] = []
        failure: Failure | None = None
        status = S.PASSED
        notes: list[str] = []

        for adapter in self.prepared:
            try:
                with self._limited(self._hook_limit, f"{adapter.name}.start_test_case timed out"):
                    adapter.start_test_case(case)
            except Exception as error:
                failure = _failure(error, None, f"{adapter.name} could not start the test case")
                status = S.ERROR
                break

        if failure is None:
            for index, step in enumerate(case.steps):
                step_result, step_failure = self._run_step(case, index, step)
                steps.append(step_result)
                if step_failure is not None:
                    status, failure = step_result.status, step_failure
                    break

        passed = status is S.PASSED
        for adapter in self.prepared:
            try:
                with self._limited(self._hook_limit, f"{adapter.name}.finish_test_case timed out"):
                    adapter.finish_test_case(case, passed)
            except Exception as error:
                if failure is None:
                    status = S.ERROR
                    failure = _failure(
                        error, None, f"{adapter.name} could not finish the test case"
                    )
                else:
                    notes.append(f"{adapter.name}.finish_test_case: {describe(error)}")

        evidence: list[EvidenceReference] = []
        for adapter in self.prepared:
            try:
                # Evidence may be collected after the execution deadline: it only adds notes.
                with deadline(self._hook_limit, "evidence collection timed out"):
                    evidence.extend(adapter.collect_evidence(case))
            except Exception as error:  # evidence must never change the outcome
                notes.append(f"{adapter.name}: evidence collection failed: {describe(error)}")

        return TestResult(
            test_case_id=case.id,
            name=case.name,
            status=status,
            started_at=started,
            finished_at=self.clock(),
            duration_ms=_elapsed_ms(clock),
            steps=tuple(steps),
            steps_total=len(case.steps),
            failure=failure,
            evidence=tuple(evidence),
            notes=tuple(notes),
        )

    def _run_step(
        self, case: TestCase, index: int, step: Step
    ) -> tuple[StepResult, Failure | None]:
        clock = time.perf_counter()
        failure: Failure | None = None
        status = S.PASSED
        try:
            message = f"step exceeded its timeout of {self.step_timeout:g}s"
            with self._limited(self.step_timeout + GRACE_SECONDS, message):
                handler, kwargs = self._prepare_step(step)
                handler(StepContext(self.context, case, step, self.providers), **kwargs)
        except Exception as error:  # KeyboardInterrupt is not an Exception: it propagates
            status, classification = classify(error)
            failure = Failure(
                classification=classification,
                message=describe(error),
                step_index=index,
                error_type=type(error).__name__,
            )
        result = StepResult(
            index=index,
            keyword=step.keyword,
            text=step.text,
            line=step.line,
            action=step.action,
            status=status,
            duration_ms=_elapsed_ms(clock),
        )
        self.log.event(
            "step-finished",
            test_case_id=case.id,
            index=index,
            line=step.line,
            action=step.action,
            text=f"{step.keyword} {step.text}",
            status=status.value,
            duration_ms=result.duration_ms,
            error=failure.message if failure else None,
        )
        return result, failure

    def _resolve(self, text: str) -> str:
        return resolve_references(text, self.variables, self.context.redactor)

    def _prepare_step(self, step: Step) -> tuple[Callable[..., Any], dict[str, Any]]:
        if step.action is None:
            raise _PlatformError("step is not resolved; the specification should not be READY")
        definition = self.steps.get(step.action)
        if definition is None:
            raise _PlatformError(
                f"step definition {step.action!r} is not registered; recompile the scenarios"
            )
        try:
            parameters = {
                name: self._resolve(value) if isinstance(value, str) else value
                for name, value in step.parameters.items()
            }
            arguments = StepArguments(
                data_table=(
                    tuple(tuple(self._resolve(cell) for cell in row) for row in step.data_table)
                    if step.data_table is not None
                    else None
                ),
                doc_string=self._resolve(step.doc_string.content) if step.doc_string else None,
            )
        except MissingSecretError as error:
            raise TestEnvironmentError(str(error)) from None
        try:
            kwargs = definition.bind(parameters, arguments)
        except StepParameterError as error:
            raise _PlatformError(f"{definition.id}: {error}") from None
        return definition.handler, kwargs


class _PlatformError(Exception):
    """Inconsistent input to the runner; classified as TEST_IMPLEMENTATION_ERROR."""


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


def _failure(error: BaseException, step_index: int | None, prefix: str) -> Failure:
    _, classification = classify(error)
    return Failure(
        classification=classification,
        message=f"{prefix}: {describe(error)}",
        step_index=step_index,
        error_type=type(error).__name__,
    )


def _not_run(case: TestCase, failure: Failure) -> TestResult:
    """A test case that could not start because the execution failed before it."""
    return TestResult(
        test_case_id=case.id,
        name=case.name,
        status=S.ERROR,
        steps_total=len(case.steps),
        failure=failure,
    )


def _cancelled(case: TestCase, reason: str) -> TestResult:
    return TestResult(
        test_case_id=case.id,
        name=case.name,
        status=S.CANCELLED,
        steps_total=len(case.steps),
        notes=(reason,),
    )


def redact_report(report: ExecutionReport, redactor: Redactor) -> ExecutionReport:
    """Mask secrets in every free-text field of a report.

    Identifiers, statuses, actions and timestamps are structural data and are
    left untouched: a secret that happens to be a common word (``wrong``) must
    not corrupt ids such as ``login.wrong-password``.
    """
    text = redactor.redact

    def failure(value: Failure | None) -> Failure | None:
        return None if value is None else value.model_copy(update={"message": text(value.message)})

    results = tuple(
        result.model_copy(
            update={
                "name": text(result.name),
                "steps": tuple(s.model_copy(update={"text": text(s.text)}) for s in result.steps),
                "failure": failure(result.failure),
                "notes": tuple(text(note) for note in result.notes),
                "evidence": tuple(
                    e.model_copy(update={"description": text(e.description)})
                    for e in result.evidence
                ),
            }
        )
        for result in report.results
    )
    return report.model_copy(
        update={
            "results": results,
            "failure": failure(report.failure),
            "cleanup_errors": tuple(text(error) for error in report.cleanup_errors),
        }
    )
