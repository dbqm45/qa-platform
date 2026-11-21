"""``qa rerun``: run an earlier execution again, optionally only its failed test cases (TASK-064).

The rerun uses the scenario file as it is now, compiled again, with the
environment, mode and category of the original execution. It is a normal
execution with its own results, evidence and report; ``rerun_of`` links it to
the original in the history.
"""

from dataclasses import replace
from pathlib import Path

from qa_core.config import load_config
from qa_core.steps.registry import StepRegistry
from qa_execution.fingerprint import differences
from qa_execution.history import show_execution
from qa_execution.registry import AdapterRegistry
from qa_execution.service import TestRun, TestRunError, run_file
from qa_schemas.compilation import CompiledSpecification
from qa_schemas.enums import ExecutionStatus
from qa_schemas.results import ExecutionReport


class NothingToRerunError(Exception):
    """The execution has no test case that matches the request (e.g. everything passed)."""


def rerun_execution(
    config_path: Path,
    execution_id: str,
    *,
    failed_only: bool = False,
    steps: StepRegistry | None = None,
    adapters: AdapterRegistry | None = None,
    timeout: float | None = None,
    allow_writes: bool = False,
) -> TestRun:
    """Run the execution's specification again; with ``failed_only`` only the test
    cases that did not pass.

    Raises:
        ExecutionNotFoundError: no execution, or more than one, matches the id.
        NothingToRerunError: ``failed_only`` and every test case passed.
        TestRunError: the execution cannot be rerun (no results, environment or
            specification gone).
    """
    details = show_execution(config_path, execution_id)
    execution = details.execution
    report = details.report
    if report is None:
        raise TestRunError(f"execution {execution.id} has no results.json; it cannot be rerun")
    if report.source is None:
        raise TestRunError(
            f"execution {execution.id} was recorded before reruns were supported; "
            "run it with `qa test` instead"
        )
    rerun_cases = _not_passed(report) if failed_only else None
    if rerun_cases is not None and not rerun_cases and report.results:
        raise NothingToRerunError(f"every test case of execution {execution.id} passed")

    config = load_config(config_path)
    environment = config.project.environment(execution.environment)
    if environment is None:
        raise TestRunError(
            f"environment {execution.environment!r} of execution {execution.id} "
            "no longer exists in qa.yaml"
        )
    warnings: list[str] = []
    source = report.source

    def select(
        specifications: tuple[CompiledSpecification, ...],
    ) -> tuple[CompiledSpecification, ...]:
        matching = [c for c in specifications if c.specification.id == execution.specification_id]
        if not matching:
            raise TestRunError(
                f"specification {execution.specification_id} is no longer in {source.path}"
            )
        [compiled] = matching
        spec = compiled.specification
        if spec.source.content_hash != source.content_hash:
            warnings.append(
                f"scenario '{spec.source.scenario}' changed since execution {execution.id}; "
                "running the current version"
            )
        if rerun_cases is None or not report.results:
            return (compiled,)  # everything, also when the original never got to its cases
        # Outline cases are numbered by position, so an id alone may now name a
        # different example; the name (with the example values) must match too.
        cases = tuple(c for c in spec.test_cases if rerun_cases.get(c.id) == c.name)
        gone = sorted(
            f"{case_id} ({name})"
            for case_id, name in rerun_cases.items()
            if case_id not in {c.id for c in cases}
        )
        if not cases:
            raise TestRunError(f"no longer in the scenario: {', '.join(gone)}; nothing to rerun")
        if gone:
            warnings.append(f"no longer in the scenario, skipped: {', '.join(gone)}")
        narrowed = spec.model_copy(update={"test_cases": cases})
        return (compiled.model_copy(update={"specification": narrowed}),)

    run = run_file(
        config_path,
        config,
        source.path,
        environment,
        mode=execution.mode,
        category=execution.category,
        steps=steps,
        adapters=adapters,
        timeout=timeout,
        select=select,
        rerun_of=execution.id,
        allow_writes=allow_writes,
        mocks=report.mocked,  # the same services as in the original execution
    )
    original = report.fingerprint
    for spec_run in run.runs:
        current = spec_run.report.fingerprint if spec_run.report else None
        if original is None or current is None:
            continue
        changed = [
            line
            for line in differences(original, current)
            if line != "specification" and not line.startswith("test case ")
        ]  # scenario changes are reported above, per scenario
        if changed:
            warnings.append(f"since execution {execution.id} changed: {'; '.join(changed)}")
    return replace(run, warnings=tuple(warnings))


def _not_passed(report: ExecutionReport) -> dict[str, str]:
    """Test case id -> name of every case that did not pass."""
    return {
        r.test_case_id: r.name for r in report.results if r.status is not ExecutionStatus.PASSED
    }
