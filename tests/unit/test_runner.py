"""Local Runner, execution lifecycle and error classification (TASK-034..036, TASK-038)."""

import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

import pytest

from qa_core.scenarios.compilation import compile_documents
from qa_core.scenarios.parsing import parse_document
from qa_core.steps.registry import StepRegistry
from qa_execution.adapters import ExecutionContext, TestAdapter
from qa_execution.errors import StepFailure, TestDataError, TestEnvironmentError
from qa_execution.registry import AdapterRegistry
from qa_execution.runner import (
    ExecutionRequest,
    LocalRunner,
    NotExecutableError,
    StepContext,
    new_execution_id,
)
from qa_execution.targets import LocalTarget
from qa_schemas.compilation import CompiledSpecification
from qa_schemas.enums import (
    CompilationStatus,
    DependencyMode,
    ExecutionMode,
    ExecutionStatus,
    FailureClassification,
    ScenarioFormat,
    StepKind,
    TestCategory,
)
from qa_schemas.evidence import EvidenceReference
from qa_schemas.execution import TestExecution
from qa_schemas.plan import Dependency, ExecutionPlan, ExecutionSettings
from qa_schemas.project import Environment
from qa_schemas.results import ExecutionReport
from qa_schemas.scenario import ScenarioDocument, content_hash
from qa_schemas.specification import TestCase

S, C = ExecutionStatus, FailureClassification
T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)

# --- Fakes -------------------------------------------------------------------

EVENTS: list[str] = []


class FakeAdapter(TestAdapter):
    """Records lifecycle calls; behaviour can be switched per test via ``fail``."""

    fail: ClassVar[set[str]] = set()

    def __init__(self) -> None:
        self.prepared = False

    def _event(self, event: str) -> None:
        EVENTS.append(f"{self.name}.{event}")
        if f"{self.name}.{event}" in self.fail:
            raise RuntimeError(f"{event} broke")

    def validate(self, specification: Any) -> list[str]:
        EVENTS.append(f"{self.name}.validate")
        return ["no base_url"] if f"{self.name}.validate" in self.fail else []

    def prepare(self, context: ExecutionContext) -> None:
        self._event("prepare")
        self.prepared = True

    def start_test_case(self, test_case: TestCase) -> None:
        self._event(f"start:{test_case.id}")

    def finish_test_case(self, test_case: TestCase, passed: bool) -> None:
        self._event(f"finish:{test_case.id}:{passed}")

    def collect_evidence(self, test_case: TestCase) -> list[EvidenceReference]:
        self._event("evidence")
        return [EvidenceReference(kind="log", path=PurePosixPath(f"{test_case.id}.log"))]

    def cleanup(self) -> None:
        self._event("cleanup")
        self.prepared = False

    @property
    def resource(self) -> Any:
        return f"{self.name}-resource"


class Browser(FakeAdapter):
    name = "browser"
    capabilities = frozenset({"browser"})


class Http(FakeAdapter):
    name = "http"
    capabilities = frozenset({"http"})


def _behave(context: StepContext, what: str) -> None:
    EVENTS.append(f"step:{what}:{context.resource('browser')}")
    match what:
        case "fail":
            raise StepFailure("expected 'Welcome', got 'Error'")
        case "boom":
            raise KeyError("missing")
        case "timeout":
            raise TimeoutError("page did not load")
        case "data":
            raise TestDataError("user alice does not exist")
        case "env":
            raise TestEnvironmentError("service down")
        case "interrupt":
            raise KeyboardInterrupt


def _do(context: StepContext, what: str) -> None:
    _behave(context, what)


def _check(context: StepContext, what: str) -> None:
    _behave(context, what)


def _api(context: StepContext, what: str) -> None:
    EVENTS.append(f"api:{what}:{context.resource('http')}")


def _steps() -> StepRegistry:
    registry = StepRegistry()
    registry.register(
        "t.do", "the user does {string}", _do, kind=StepKind.ACTION, capability="browser"
    )
    registry.register(
        "t.check", "outcome {string}", _check, kind=StepKind.EXPECTATION, capability="browser"
    )
    registry.register(
        "t.api", "the api does {string}", _api, kind=StepKind.ACTION, capability="http"
    )
    return registry


def _compiled(*steps: str, outline_rows: list[str] | None = None) -> CompiledSpecification:
    body = "\n".join(f"    {s}" for s in steps)
    if outline_rows is None:
        content = f"Feature: F\n  Scenario: S\n{body}\n"
    else:
        rows = "\n".join(f"      | {r} |" for r in outline_rows)
        content = (
            f"Feature: F\n  Scenario Outline: S\n{body}\n    Examples:\n      | what |\n{rows}\n"
        )
    document = ScenarioDocument(
        path=PurePosixPath("scenarios/f.feature"),
        format=ScenarioFormat.GHERKIN,
        content=content,
        content_hash=content_hash(content.encode()),
    )
    [compiled] = compile_documents(
        [parse_document(document)], _steps(), base=PurePosixPath("scenarios")
    ).specifications
    return compiled


PASSING = ('When the user does "pass"', 'Then outcome "pass"')


class RecordingStore:
    def __init__(self) -> None:
        self.history: list[tuple[str, ExecutionStatus]] = []
        self.saved: dict[str, TestExecution] = {}

    def add(self, execution: TestExecution) -> None:
        self.history.append(("add", execution.status))
        self.saved[execution.id] = execution

    def update(self, execution: TestExecution) -> None:
        assert execution.id in self.saved
        self.history.append(("update", execution.status))
        self.saved[execution.id] = execution


@pytest.fixture(autouse=True)
def _reset() -> None:
    EVENTS.clear()
    FakeAdapter.fail = set()


@pytest.fixture
def store() -> RecordingStore:
    return RecordingStore()


def _runner(tmp_path: Path, store: RecordingStore | None = None, **kwargs: Any) -> LocalRunner:
    times = iter(T0 + timedelta(seconds=i) for i in range(1000))
    return LocalRunner(
        _steps(),
        AdapterRegistry([Browser, Http]),
        evidence_root=tmp_path / "evidence",
        store=store,
        clock=lambda: next(times),
        **kwargs,
    )


def _plan(compiled: CompiledSpecification, **settings: Any) -> ExecutionPlan:
    return ExecutionPlan(
        id="p.local",
        specification_id=compiled.specification.id,
        mode=ExecutionMode.FE,
        category=TestCategory.FUNCTIONAL,
        environment="local",
        adapters=("browser", "http"),
        settings=ExecutionSettings(**settings),
    )


def _run(
    tmp_path: Path,
    compiled: CompiledSpecification,
    store: RecordingStore | None = None,
    **settings: Any,
) -> ExecutionReport:
    request = ExecutionRequest(
        project_id="shop",
        compiled=compiled,
        plan=_plan(compiled, **settings),
        environment=Environment(name="local"),
    )
    return _runner(tmp_path, store).run(request)


# --- Successful execution ----------------------------------------------------


def test_passing_execution(tmp_path: Path, store: RecordingStore) -> None:
    report = _run(tmp_path, _compiled(*PASSING), store)

    assert report.execution.status is S.PASSED
    [result] = report.results
    assert (result.status, result.failure, result.steps_total) == (S.PASSED, None, 2)
    assert [(s.action, s.status) for s in result.steps] == [
        ("t.do", S.PASSED),
        ("t.check", S.PASSED),
    ]
    assert result.evidence[0].path == PurePosixPath("f.s.log")
    assert report.cleanup_errors == ()


def test_steps_receive_parameters_and_adapter_resources(tmp_path: Path) -> None:
    _run(
        tmp_path,
        _compiled('When the user does "pass"', 'And the api does "ping"', 'Then outcome "pass"'),
    )
    steps = [e for e in EVENTS if e.startswith(("step:", "api:"))]
    assert steps == [
        "step:pass:browser-resource",
        "api:ping:http-resource",
        "step:pass:browser-resource",
    ]


def test_adapter_lifecycle_order(tmp_path: Path) -> None:
    _run(tmp_path, _compiled(*PASSING))
    lifecycle = [e for e in EVENTS if e.startswith("browser.")]
    assert lifecycle == [
        "browser.validate", "browser.prepare", "browser.start:f.s",
        "browser.finish:f.s:True", "browser.evidence", "browser.cleanup",
    ]  # fmt: skip


def test_only_needed_adapters_are_used(tmp_path: Path) -> None:
    _run(tmp_path, _compiled(*PASSING))
    assert not any(e.startswith("http.") for e in EVENTS)


# --- Lifecycle and persistence (TASK-036) ------------------------------------


def test_status_is_persisted_at_every_transition(tmp_path: Path, store: RecordingStore) -> None:
    report = _run(tmp_path, _compiled(*PASSING), store)

    assert store.history == [("add", S.PENDING), ("update", S.RUNNING), ("update", S.PASSED)]
    saved = store.saved[report.execution.id]
    assert saved == report.execution
    assert saved.started_at is not None and saved.finished_at is not None
    assert (saved.project_id, saved.plan_id, saved.mode) == ("shop", "p.local", ExecutionMode.FE)


def test_every_execution_has_a_unique_id(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    compiled = _compiled(*PASSING)
    request = ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    ids = {runner.run(request).execution.id for _ in range(5)}
    assert len(ids) == 5


def test_execution_id_format() -> None:
    execution_id = new_execution_id(datetime(2026, 11, 21, 14, 30, 5, tzinfo=UTC))
    assert re.fullmatch(r"20261121-143005-[0-9a-f]{6}", execution_id)


def test_evidence_directory_per_execution(tmp_path: Path) -> None:
    report = _run(tmp_path, _compiled(*PASSING))
    assert (tmp_path / "evidence" / report.execution.id).is_dir()


# --- Failures and classification (TASK-038) ---------------------------------


def test_failed_expectation_is_failed_application_bug(
    tmp_path: Path, store: RecordingStore
) -> None:
    report = _run(
        tmp_path,
        _compiled('When the user does "pass"', 'Then outcome "fail"', 'And outcome "pass"'),
        store,
    )

    assert report.execution.status is S.FAILED
    assert store.history[-1] == ("update", S.FAILED)
    [result] = report.results
    assert result.status is S.FAILED
    assert result.failure is not None
    assert (result.failure.classification, result.failure.step_index) == (C.APPLICATION_BUG, 1)
    assert result.failure.message == "expected 'Welcome', got 'Error'"
    assert (len(result.steps), result.steps_total) == (2, 3)  # third step not run
    assert "browser.finish:f.s:False" in EVENTS
    assert "browser.cleanup" in EVENTS


@pytest.mark.parametrize(
    ("behaviour", "classification", "error_type"),
    [
        ("boom", C.TEST_IMPLEMENTATION_ERROR, "KeyError"),
        ("timeout", C.ENVIRONMENT_ERROR, "TimeoutError"),
        ("data", C.TEST_DATA_ERROR, "TestDataError"),
        ("env", C.ENVIRONMENT_ERROR, "TestEnvironmentError"),
    ],
)
def test_errors_are_never_reported_as_failures(
    tmp_path: Path, behaviour: str, classification: FailureClassification, error_type: str
) -> None:
    report = _run(tmp_path, _compiled(f'When the user does "{behaviour}"', 'Then outcome "pass"'))

    [result] = report.results
    assert result.status is S.ERROR
    assert report.execution.status is S.ERROR
    assert result.failure is not None
    assert (result.failure.classification, result.failure.error_type) == (
        classification,
        error_type,
    )
    assert result.steps[0].status is S.ERROR


def test_missing_step_definition_is_an_implementation_error(tmp_path: Path) -> None:
    compiled = _compiled(*PASSING)
    runner = LocalRunner(
        StepRegistry(), AdapterRegistry([Browser, Http]), evidence_root=tmp_path, clock=lambda: T0
    )
    request = ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))

    [result] = runner.run(request).results

    assert result.status is S.ERROR
    assert result.failure is not None
    assert result.failure.classification is C.TEST_IMPLEMENTATION_ERROR
    assert "'t.do' is not registered" in result.failure.message


# --- Not executable: nothing starts ------------------------------------------


def test_blocked_specification_is_not_executed(tmp_path: Path, store: RecordingStore) -> None:
    compiled = _compiled("When the user flies", 'Then outcome "pass"')
    assert compiled.status is CompilationStatus.BLOCKED

    with pytest.raises(NotExecutableError, match="is blocked and cannot be executed"):
        _run(tmp_path, compiled, store)
    assert store.history == []
    assert EVENTS == []


def test_needs_review_is_not_executed(tmp_path: Path) -> None:
    with pytest.raises(NotExecutableError, match="needs_review"):
        _run(tmp_path, _compiled('When the user does "pass"'))


def test_plan_for_another_specification_is_rejected(tmp_path: Path) -> None:
    compiled = _compiled(*PASSING)
    plan = _plan(compiled).model_copy(update={"specification_id": "other"})
    with pytest.raises(NotExecutableError, match="is for specification 'other'"):
        _runner(tmp_path).run(ExecutionRequest("shop", compiled, plan, Environment(name="local")))


def test_plan_with_mocked_dependency_is_rejected(tmp_path: Path, store: RecordingStore) -> None:
    compiled = _compiled(*PASSING)
    plan = _plan(compiled).model_copy(
        update={"dependencies": (Dependency(name="api", mode=DependencyMode.MOCK),)}
    )
    with pytest.raises(NotExecutableError, match="mocks api, but no mock definition was given"):
        _runner(tmp_path, store).run(
            ExecutionRequest("shop", compiled, plan, Environment(name="local"))
        )
    assert store.history == []


def test_plan_for_another_environment_is_rejected(tmp_path: Path) -> None:
    compiled = _compiled(*PASSING)
    with pytest.raises(NotExecutableError, match="targets environment 'local', not 'qa'"):
        _runner(tmp_path).run(
            ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="qa"))
        )


def test_missing_capability_is_rejected(tmp_path: Path) -> None:
    compiled = _compiled(*PASSING)
    plan = _plan(compiled).model_copy(update={"adapters": ("http",)})
    with pytest.raises(NotExecutableError, match="not provided by the allowed adapters: browser"):
        _runner(tmp_path).run(ExecutionRequest("shop", compiled, plan, Environment(name="local")))


# --- Adapter problems --------------------------------------------------------


def test_adapter_validation_problem_stops_before_prepare(tmp_path: Path) -> None:
    FakeAdapter.fail = {"browser.validate"}

    report = _run(tmp_path, _compiled(*PASSING))

    assert report.execution.status is S.ERROR
    assert report.failure is not None
    assert report.failure.classification is C.ENVIRONMENT_ERROR
    assert report.failure.message == "browser: no base_url"
    assert [r.status for r in report.results] == [S.ERROR]
    assert "browser.prepare" not in EVENTS


def test_prepare_failure_still_cleans_up(tmp_path: Path) -> None:
    FakeAdapter.fail = {"browser.prepare"}

    report = _run(tmp_path, _compiled(*PASSING))

    assert report.execution.status is S.ERROR
    assert report.failure is not None
    assert report.failure.message == "browser could not be prepared: prepare broke"
    assert report.failure.classification is C.ENVIRONMENT_ERROR
    assert "browser.cleanup" in EVENTS
    assert not any(e.startswith("step:") for e in EVENTS)


def test_cleanup_error_does_not_change_the_outcome(tmp_path: Path) -> None:
    FakeAdapter.fail = {"browser.cleanup"}

    passed = _run(tmp_path, _compiled(*PASSING))
    failed = _run(tmp_path, _compiled('When the user does "pass"', 'Then outcome "fail"'))

    assert passed.execution.status is S.PASSED
    assert failed.execution.status is S.FAILED
    assert passed.cleanup_errors == ("browser: cleanup broke",)


def test_evidence_failure_does_not_change_the_outcome(tmp_path: Path) -> None:
    FakeAdapter.fail = {"browser.evidence"}

    [result] = _run(tmp_path, _compiled(*PASSING)).results

    assert result.status is S.PASSED
    assert result.notes == ("browser: evidence collection failed: evidence broke",)


def test_finish_hook_error_after_a_pass_is_an_error(tmp_path: Path) -> None:
    FakeAdapter.fail = {"browser.finish:f.s:True"}
    [result] = _run(tmp_path, _compiled(*PASSING)).results
    assert result.status is S.ERROR
    assert result.failure is not None
    assert result.failure.message.startswith("browser could not finish the test case")


def test_finish_hook_error_does_not_hide_a_failure(tmp_path: Path) -> None:
    FakeAdapter.fail = {"browser.finish:f.s:False"}
    [result] = _run(tmp_path, _compiled('When the user does "pass"', 'Then outcome "fail"')).results
    assert result.status is S.FAILED
    assert result.failure is not None
    assert result.failure.classification is C.APPLICATION_BUG
    assert result.notes == ("browser.finish_test_case: finish:f.s:False broke",)


# --- Several test cases ------------------------------------------------------


def test_all_cases_run_and_any_failure_fails_the_execution(tmp_path: Path) -> None:
    compiled = _compiled(
        'When the user does "pass"', 'Then outcome "<what>"', outline_rows=["pass", "fail", "pass"]
    )

    report = _run(tmp_path, compiled)

    assert [r.status for r in report.results] == [S.PASSED, S.FAILED, S.PASSED]
    assert report.execution.status is S.FAILED


def test_fail_fast_cancels_remaining_cases(tmp_path: Path) -> None:
    compiled = _compiled(
        'When the user does "pass"', 'Then outcome "<what>"', outline_rows=["fail", "pass", "pass"]
    )

    report = _run(tmp_path, compiled, fail_fast=True)

    assert [r.status for r in report.results] == [S.FAILED, S.CANCELLED, S.CANCELLED]
    assert report.results[1].notes == ("not run: fail_fast after f.s:1 did not pass",)
    assert report.execution.status is S.FAILED


def test_error_outranks_failure(tmp_path: Path) -> None:
    compiled = _compiled(
        'When the user does "pass"', 'Then outcome "<what>"', outline_rows=["fail", "boom"]
    )
    assert _run(tmp_path, compiled).execution.status is S.ERROR


# --- Cancellation ------------------------------------------------------------


def test_interrupt_cancels_cleans_up_and_propagates(tmp_path: Path, store: RecordingStore) -> None:
    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, _compiled('When the user does "interrupt"', 'Then outcome "pass"'), store)

    assert store.history[-1] == ("update", S.CANCELLED)
    assert next(iter(store.saved.values())).finished_at is not None
    assert "browser.cleanup" in EVENTS


# --- Execution target (TASK-034) ---------------------------------------------


def test_local_target_runs_in_process(tmp_path: Path) -> None:
    compiled = _compiled(*PASSING)
    target = LocalTarget(_runner(tmp_path))
    report = target.execute(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )
    assert target.name == "local"
    assert report.execution.status is S.PASSED


# --- Secrets (TASK-066) ------------------------------------------------------


def _secret_step(context: StepContext, value: str) -> None:
    EVENTS.append(f"secret-step:{value}")
    if value.startswith("leak"):
        raise StepFailure(f"server echoed {value!r} back")


def _secret_steps() -> StepRegistry:
    steps = _steps()
    steps.register(
        "t.secret",
        "the user types {string}",
        _secret_step,
        kind=StepKind.ACTION,
        capability="browser",
    )
    return steps


def _secret_runner(tmp_path: Path, variables: dict[str, str]) -> LocalRunner:
    return LocalRunner(
        _secret_steps(),
        AdapterRegistry([Browser, Http]),
        evidence_root=tmp_path,
        environment_variables=variables,
    )


def _secret_compiled(*steps: str) -> CompiledSpecification:
    content = "Feature: F\n  Scenario: S\n" + "\n".join(f"    {s}" for s in steps) + "\n"
    document = ScenarioDocument(
        path=PurePosixPath("scenarios/f.feature"), format=ScenarioFormat.GHERKIN,
        content=content, content_hash=content_hash(content.encode()),
    )  # fmt: skip
    [compiled] = compile_documents([parse_document(document)], _secret_steps()).specifications
    return compiled


def test_secret_reference_is_resolved_only_at_execution(tmp_path: Path) -> None:
    compiled = _secret_compiled('When the user types "${SHOP_PASSWORD}"', 'Then outcome "pass"')
    assert compiled.specification.test_cases[0].steps[0].parameters == {"value": "${SHOP_PASSWORD}"}
    runner = _secret_runner(tmp_path, {"SHOP_PASSWORD": "hunter2-xyz"})

    report = runner.run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )

    assert "secret-step:hunter2-xyz" in EVENTS
    assert report.execution.status is S.PASSED
    assert "hunter2-xyz" not in report.model_dump_json()
    assert report.results[0].steps[0].text == 'the user types "${SHOP_PASSWORD}"'


def test_secret_values_are_masked_in_failure_messages(tmp_path: Path) -> None:
    compiled = _secret_compiled('When the user types "${TOKEN}"', 'Then outcome "pass"')
    runner = _secret_runner(tmp_path, {"TOKEN": "leak-me-please"})

    report = runner.run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )

    failure = report.results[0].failure
    assert failure is not None
    assert failure.message == "server echoed '********' back"
    assert "leak-me-please" not in report.model_dump_json()


def test_missing_secret_is_an_environment_error(tmp_path: Path) -> None:
    compiled = _secret_compiled('When the user types "${MISSING}"', 'Then outcome "pass"')
    report = _secret_runner(tmp_path, {}).run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )
    failure = report.results[0].failure
    assert failure is not None
    assert failure.classification is C.ENVIRONMENT_ERROR
    assert failure.message.startswith("secret MISSING is not set")
    assert not any(e.startswith("secret-step") for e in EVENTS)


def test_steps_can_mark_values_as_secret(tmp_path: Path) -> None:
    def typed_password(context: StepContext, value: str) -> None:
        context.mark_secret(value)
        raise StepFailure(f"login with {value} failed")

    steps = _steps()
    steps.register(
        "t.pw",
        "the password is {string}",
        typed_password,
        kind=StepKind.ACTION,
        capability="browser",
    )
    content = (
        'Feature: F\n  Scenario: S\n    When the password is "literal-pass"\n'
        '    Then outcome "pass"\n'
    )
    document = ScenarioDocument(
        path=PurePosixPath("scenarios/f.feature"), format=ScenarioFormat.GHERKIN,
        content=content, content_hash=content_hash(content.encode()),
    )  # fmt: skip
    [compiled] = compile_documents([parse_document(document)], steps).specifications
    runner = LocalRunner(steps, AdapterRegistry([Browser, Http]), evidence_root=tmp_path)

    report = runner.run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )

    assert "literal-pass" not in report.model_dump_json()
    assert report.results[0].steps[0].text == 'the password is "********"'


def test_secrets_never_corrupt_identifiers(tmp_path: Path) -> None:
    """A literal password that is a common word ('wrong') must not alter ids."""

    def typed_password(context: StepContext, value: str) -> None:
        context.mark_secret(value)
        raise StepFailure(f"{value} password rejected")

    steps = _steps()
    steps.register(
        "t.pw",
        "the password is {string}",
        typed_password,
        kind=StepKind.ACTION,
        capability="browser",
    )
    content = (
        'Feature: F\n  Scenario: Wrong password\n    When the password is "wrong"\n'
        '    Then outcome "pass"\n'
    )
    document = ScenarioDocument(
        path=PurePosixPath("scenarios/f.feature"), format=ScenarioFormat.GHERKIN,
        content=content, content_hash=content_hash(content.encode()),
    )  # fmt: skip
    [compiled] = compile_documents([parse_document(document)], steps).specifications
    runner = LocalRunner(steps, AdapterRegistry([Browser, Http]), evidence_root=tmp_path)

    report = runner.run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )

    [result] = report.results
    assert report.execution.specification_id == "scenarios.f.wrong-password"
    assert result.test_case_id == "scenarios.f.wrong-password"
    assert result.steps[0].action == "t.pw"
    assert result.name == "Wrong password"  # secrets are case-sensitive values
    assert result.failure is not None
    assert result.failure.message == "******** password rejected"


# --- Timeouts and safe cleanup (TASK-067, TASK-068) --------------------------


def _sleepy_steps() -> StepRegistry:
    def sleep_for(context: StepContext, seconds: float) -> None:
        time.sleep(seconds)

    steps = _steps()
    steps.register("t.sleep", "the user waits {float} seconds", sleep_for,
                   kind=StepKind.ACTION, capability="browser")  # fmt: skip
    return steps


def _timed_run(
    tmp_path: Path, body: str, *, step: float, total: float, rows: int = 0
) -> ExecutionReport:
    lines = "\n".join(f"    {s}" for s in body.splitlines())
    if rows:
        examples = "\n".join(f"      | {i} |" for i in range(rows))
        content = (
            f"Feature: F\n  Scenario Outline: S <n>\n{lines}\n"
            f"    Examples:\n      | n |\n{examples}\n"
        )
    else:
        content = f"Feature: F\n  Scenario: S\n{lines}\n"
    document = ScenarioDocument(
        path=PurePosixPath("scenarios/f.feature"), format=ScenarioFormat.GHERKIN,
        content=content, content_hash=content_hash(content.encode()),
    )  # fmt: skip
    steps = _sleepy_steps()
    [compiled] = compile_documents([parse_document(document)], steps).specifications
    plan = _plan(compiled, step_timeout_seconds=step, timeout_seconds=total)
    runner = LocalRunner(steps, AdapterRegistry([Browser, Http]), evidence_root=tmp_path)
    return runner.run(ExecutionRequest("shop", compiled, plan, Environment(name="local")))


def test_hanging_step_is_stopped_after_its_timeout(tmp_path: Path) -> None:
    started = time.monotonic()

    report = _timed_run(
        tmp_path, 'When the user waits 60 seconds\nThen outcome "pass"', step=0.3, total=60
    )

    assert time.monotonic() - started < 10
    [result] = report.results
    assert result.status is S.ERROR
    assert result.failure is not None
    assert result.failure.classification is C.ENVIRONMENT_ERROR
    assert result.failure.message == "step exceeded its timeout of 0.3s"
    assert result.failure.error_type == "StepTimeoutError"
    assert "browser.cleanup" in EVENTS


def test_execution_timeout_cancels_the_remaining_cases(tmp_path: Path) -> None:
    started = time.monotonic()

    report = _timed_run(
        tmp_path, 'When the user waits 0.4 seconds\nThen outcome "pass"', step=0.9, total=1, rows=5
    )

    assert time.monotonic() - started < 10
    statuses = [r.status for r in report.results]
    assert statuses[0] is S.PASSED
    assert statuses[-1] is S.CANCELLED
    assert "not run: execution timeout of 1s exceeded" in report.results[-1].notes
    assert report.failure is not None
    assert report.failure.message == "execution timeout of 1s exceeded"
    assert report.execution.status is S.ERROR  # never reported as passed


def test_step_cut_short_by_the_execution_deadline(tmp_path: Path) -> None:
    report = _timed_run(
        tmp_path, 'When the user waits 30 seconds\nThen outcome "pass"', step=0.5, total=0.5
    )
    [result] = report.results
    assert result.failure is not None
    assert result.failure.message == "execution timeout of 0.5s exceeded"
    assert report.execution.status is S.ERROR


def test_hanging_prepare_is_limited_by_the_execution_deadline(tmp_path: Path) -> None:
    class SlowStart(Browser):
        def prepare(self, context: ExecutionContext) -> None:
            time.sleep(30)

    compiled = _compiled(*PASSING)
    plan = _plan(compiled, step_timeout_seconds=0.2, timeout_seconds=0.5)
    runner = LocalRunner(_steps(), AdapterRegistry([SlowStart, Http]), evidence_root=tmp_path)

    report = runner.run(ExecutionRequest("shop", compiled, plan, Environment(name="local")))

    assert report.failure is not None
    assert (
        report.failure.message
        == "browser could not be prepared: execution timeout of 0.5s exceeded"
    )
    assert report.execution.status is S.ERROR


def test_hanging_cleanup_is_stopped_and_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qa_execution import runner as runner_module

    class StuckCleanup(Browser):
        def cleanup(self) -> None:
            time.sleep(30)

    monkeypatch.setattr(runner_module, "CLEANUP_SECONDS", 0.3)
    compiled = _compiled(*PASSING)
    runner = LocalRunner(_steps(), AdapterRegistry([StuckCleanup, Http]), evidence_root=tmp_path)

    report = runner.run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )

    assert report.execution.status is S.PASSED  # the outcome is not overwritten
    assert report.cleanup_errors == ("browser: cleanup did not finish within 0.3s",)


def test_hanging_evidence_collection_only_adds_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qa_execution import runner as runner_module

    class StuckEvidence(Browser):
        def collect_evidence(self, test_case: TestCase) -> list[EvidenceReference]:
            time.sleep(30)
            return []

    monkeypatch.setattr(runner_module, "HOOK_SECONDS", 0.2)
    compiled = _compiled(*PASSING)
    plan = _plan(compiled, step_timeout_seconds=0.1)
    runner = LocalRunner(_steps(), AdapterRegistry([StuckEvidence, Http]), evidence_root=tmp_path)

    report = runner.run(ExecutionRequest("shop", compiled, plan, Environment(name="local")))

    [result] = report.results
    assert result.status is S.PASSED
    assert result.notes == ("browser: evidence collection failed: evidence collection timed out",)


# --- Execution log (TASK-037) ------------------------------------------------


def _log_events(tmp_path: Path, report: ExecutionReport) -> list[dict[str, Any]]:
    path = tmp_path / "evidence" / report.execution.id / "execution.log"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_execution_log_records_the_whole_execution(tmp_path: Path) -> None:
    report = _run(tmp_path, _compiled('When the user does "pass"', 'Then outcome "fail"'))

    events = _log_events(tmp_path, report)
    assert [e["event"] for e in events] == [
        "execution-started", "adapter-prepared", "test-case-started",
        "step-finished", "step-finished", "test-case-finished",
        "cleanup-finished", "execution-finished",
    ]  # fmt: skip
    started = events[0]
    assert started["execution_id"] == report.execution.id
    assert started["specification_id"] == "f.s"
    assert started["scenario"] == "scenarios/f.feature:2"
    assert (started["mode"], started["environment"], started["adapters"]) == (
        "fe",
        "local",
        ["browser"],
    )
    failed_step = events[4]
    assert (failed_step["action"], failed_step["status"]) == ("t.check", "failed")
    assert failed_step["error"] == "expected 'Welcome', got 'Error'"
    finished_case = events[5]
    assert (finished_case["status"], finished_case["classification"]) == (
        "failed",
        "application_bug",
    )
    assert events[-1]["status"] == "failed"
    assert events[-1]["counts"] == {"failed": 1}
    assert all("time" in e for e in events)


def test_execution_log_masks_secrets(tmp_path: Path) -> None:
    compiled = _secret_compiled('When the user types "${TOKEN}"', 'Then outcome "pass"')
    report = _secret_runner(tmp_path, {"TOKEN": "leak-me-please"}).run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )
    text = (tmp_path / report.execution.id / "execution.log").read_text()
    assert "leak-me-please" not in text
    assert "********" in text


def test_log_records_cancelled_cases(tmp_path: Path) -> None:
    compiled = _compiled(
        'When the user does "pass"', 'Then outcome "<what>"', outline_rows=["fail", "pass"]
    )
    report = _run(tmp_path, compiled, fail_fast=True)
    cancelled = [e for e in _log_events(tmp_path, report) if e["event"] == "test-case-cancelled"]
    assert [e["test_case_id"] for e in cancelled] == ["f.s:2"]


def test_interrupted_execution_is_logged(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    compiled = _compiled('When the user does "interrupt"', 'Then outcome "pass"')
    with pytest.raises(KeyboardInterrupt):
        runner.run(ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local")))
    [log] = list((tmp_path / "evidence").glob("*/execution.log"))
    events = [json.loads(line)["event"] for line in log.read_text().splitlines()]
    assert events[-3:] == ["execution-interrupted", "cleanup-finished", "execution-finished"]


def test_environment_variables_are_resolved_without_masking(tmp_path: Path) -> None:
    compiled = _secret_compiled('When the user types "${SHOP_USER}"', 'Then outcome "pass"')
    runner = _secret_runner(tmp_path, {})
    environment = Environment(name="local", variables={"SHOP_USER": "alice-user"})

    report = runner.run(ExecutionRequest("shop", compiled, _plan(compiled), environment))

    assert report.execution.status is S.PASSED
    assert "secret-step:alice-user" in EVENTS
    assert report.results[0].steps[0].text == 'the user types "${SHOP_USER}"'


# --- Built-in values: ${RUN_ID}, ${UNIQUE} (TASK-056) ------------------------


def test_unique_is_one_value_per_test_case(tmp_path: Path) -> None:
    compiled = _compiled(
        'When the user does "user-${UNIQUE}"',
        'Then outcome "<what>-${UNIQUE}"',
        outline_rows=["a", "b"],
    )
    runner_ = _runner(tmp_path, id_factory=lambda now: "20260101-120000-abc123")

    report = runner_.run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )

    first, second = (r.unique for r in report.results)
    assert first == "20260101120000abc1231"
    assert second == "20260101120000abc1232"
    steps = [e.split(":")[1] for e in EVENTS if e.startswith("step:")]
    assert steps == [f"user-{first}", f"a-{first}", f"user-{second}", f"b-{second}"]


def test_run_id_and_unique_are_not_masked(tmp_path: Path) -> None:
    compiled = _compiled('When the user does "${RUN_ID}"', 'Then outcome "fail-${UNIQUE}"')
    report = _runner(tmp_path).run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )
    [result] = report.results
    assert f"step:{report.execution.id}:browser-resource" in EVENTS
    assert result.unique is not None and "*" not in result.unique
    log = (tmp_path / "evidence" / report.execution.id / "execution.log").read_text()
    assert f'"unique": "{result.unique}"' in log


def test_unique_outside_a_test_case(tmp_path: Path) -> None:
    from qa_core.redaction import MissingSecretError

    context = ExecutionContext(
        execution_id="e", environment=Environment(name="local"),
        settings=ExecutionSettings(), evidence_dir=tmp_path, builtins={"RUN_ID": "e"},
    )  # fmt: skip
    assert context.resolve("run ${RUN_ID}") == "run e"
    with pytest.raises(MissingSecretError, match=r"\$\{UNIQUE\} is only available in test case"):
        context.resolve("${UNIQUE}")


def test_read_only_guard_turns_a_passing_case_into_an_error(tmp_path: Path) -> None:
    from qa_execution.protection import ProtectedEnvironmentError

    class Guarded(Browser):
        def finish_test_case(self, test_case: TestCase, passed: bool) -> None:
            raise ProtectedEnvironmentError("blocked: POST /orders")

    compiled = _compiled(*PASSING)
    runner_ = LocalRunner(_steps(), AdapterRegistry([Guarded, Http]), evidence_root=tmp_path)

    report = runner_.run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )

    [result] = report.results
    assert result.status is ExecutionStatus.ERROR and result.notes == ()
    assert result.failure is not None
    assert result.failure.classification is FailureClassification.ENVIRONMENT_ERROR
    assert result.failure.message == "browser: blocked: POST /orders"
