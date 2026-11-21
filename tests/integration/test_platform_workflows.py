"""TASK-073 — end-to-end platform tests: coverage map and the remaining gaps.

Where each main workflow is tested:

| Workflow            | Tests                                                                 |
|---------------------|-----------------------------------------------------------------------|
| project init        | test_cli_init.py (empty dir, re-run, invalid config, database)        |
| scenario validation | test_cli_scenario_validate.py, unit/test_scenario_validation.py       |
| compilation         | test_cli_scenario_compile.py, unit/test_compilation*.py; this file    |
| execution           | unit/test_runner.py, test_browser_*.py, test_api_steps.py, this file  |
| result persistence  | test_runner_persistence.py, test_cli_test.py, test_cli_execution.py   |
| report generation   | unit/test_html_report.py, test_cli_test.py (report next to evidence)  |
| failure handling    | unit/test_runner.py (classification, timeouts, cleanup), this file    |
| the whole slice     | test_vertical_slice.py (all example features, fe/be/full, twice)      |

Coverage is measured with ``uv run pytest --cov`` (greenlet-aware, see
pyproject.toml). The tests below close the gaps that coverage showed in those
workflows.
"""

from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from qa_cli.main import app
from qa_core.scenarios import compilation
from qa_core.scenarios.compilation import compile_documents
from qa_core.scenarios.conversion import ConversionError
from qa_core.scenarios.parsing import parse_document
from qa_execution.adapters import ExecutionContext
from qa_execution.http.adapter import HttpxAdapter
from qa_execution.registry import AdapterRegistry
from qa_execution.runner import ExecutionRequest, LocalRunner
from qa_execution.service import TestRunError, run_scenario
from qa_schemas.enums import ExecutionStatus, FailureClassification, ScenarioFormat
from qa_schemas.plan import ExecutionSettings
from qa_schemas.project import Environment
from qa_schemas.results import Failure, StepResult, TestResult
from qa_schemas.scenario import ScenarioDocument, content_hash
from tests.integration import test_cli_test as cli
from tests.unit.test_runner import PASSING, Browser, Http, _compiled, _plan, _steps

S, C = ExecutionStatus, FailureClassification
runner = CliRunner()
project = cli.project


# --- Compilation: a conversion error blocks the document ---------------------


def test_conversion_error_blocks_the_document(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(feature: Any, base: Any) -> Any:
        raise ConversionError(PurePosixPath("scenarios/x.feature"), 3, "cannot convert this")

    monkeypatch.setattr(compilation, "convert_feature", fail)
    content = "Feature: F\n  Scenario: S\n    Given a\n"
    document = ScenarioDocument(
        path=PurePosixPath("scenarios/x.feature"), format=ScenarioFormat.GHERKIN,
        content=content, content_hash=content_hash(content.encode()),
    )  # fmt: skip

    report = compile_documents([parse_document(document)], _steps())

    [doc] = report.documents
    assert doc.blocked and doc.specifications == ()
    [issue] = doc.issues
    assert (issue.code, issue.line, issue.message) == ("conversion", 3, "cannot convert this")


# --- Result persistence: results cannot contradict themselves ----------------


def _failure() -> Failure:
    return Failure(classification=C.APPLICATION_BUG, message="x")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"status": S.RUNNING}, "must be final"),
        ({"status": S.FAILED}, "needs a failure"),
        ({"status": S.ERROR}, "needs a failure"),
        ({"status": S.PASSED, "failure": "f"}, "cannot have a failure"),
        ({"status": S.PASSED, "steps_total": 0, "steps": "one"}, "more step results than steps"),
    ],
)
def test_test_result_invariants(data: dict[str, Any], message: str) -> None:
    fields: dict[str, Any] = {"test_case_id": "a.b", "name": "N", "steps_total": 1} | data
    if fields.get("failure") == "f":
        fields["failure"] = _failure()
    if fields.get("steps") == "one":
        fields["steps"] = (
            StepResult(index=0, keyword="Given", text="t", status=S.PASSED, duration_ms=1),
        )
    with pytest.raises(ValidationError, match=message):
        TestResult.model_validate(fields)


def test_step_result_must_be_an_outcome() -> None:
    with pytest.raises(ValidationError, match="must be passed, failed or error"):
        StepResult(index=0, keyword="Given", text="t", status=S.CANCELLED, duration_ms=0)


# --- Failure handling in the runner ------------------------------------------


def test_adapter_whose_validation_crashes(tmp_path: Path) -> None:
    class Crashing(Browser):
        def validate(self, specification: Any) -> list[str]:
            raise RuntimeError("validator bug")

    compiled = _compiled(*PASSING)
    runner_ = LocalRunner(_steps(), AdapterRegistry([Crashing, Http]), evidence_root=tmp_path)

    report = runner_.run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )

    assert report.execution.status is S.ERROR
    assert report.failure is not None
    assert report.failure.message == "browser: validation failed: validator bug"


def test_stored_parameters_that_no_longer_validate(tmp_path: Path) -> None:
    """A specification compiled earlier can disagree with the current step definitions."""
    compiled = _compiled(*PASSING)
    case = compiled.specification.test_cases[0]
    steps = list(case.steps)
    steps[0] = steps[0].model_copy(update={"parameters": {"unexpected": 1}})
    spec = compiled.specification.model_copy(
        update={"test_cases": (case.model_copy(update={"steps": tuple(steps)}),)}
    )
    compiled = compiled.model_copy(update={"specification": spec})
    runner_ = LocalRunner(_steps(), AdapterRegistry([Browser, Http]), evidence_root=tmp_path)

    report = runner_.run(
        ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
    )

    [result] = report.results
    assert result.status is S.ERROR
    assert result.failure is not None
    assert result.failure.classification is C.TEST_IMPLEMENTATION_ERROR
    assert result.failure.message.startswith("t.do: expected parameters (what)")


def test_invalid_httpx_settings_are_an_environment_error(tmp_path: Path) -> None:
    from qa_execution.errors import TestEnvironmentError

    context = ExecutionContext(
        execution_id="e", environment=Environment(name="local"), settings=ExecutionSettings(),
        evidence_dir=tmp_path, adapter_config={"httpx": {"service": "Not Valid", "retries": 3}},
    )  # fmt: skip
    with pytest.raises(
        TestEnvironmentError, match=r"invalid adapters\.httpx configuration"
    ) as info:
        HttpxAdapter().prepare(context)
    assert "service" in str(info.value) and "retries" in str(info.value)


# --- qa test: request problems and execution-level failures ------------------


def test_no_environment_and_no_default(tmp_path: Path) -> None:
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "a.feature").write_text("Feature: F\n  Scenario: S\n    Given x\n")
    (tmp_path / "qa.yaml").write_text("project:\n  id: p\n  name: P\n")
    with pytest.raises(TestRunError, match=r"no --environment given and no default_environment"):
        run_scenario(tmp_path / "qa.yaml", Path("a.feature"))


def test_scenario_outside_the_project(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "qa.yaml").write_text("project:\n  id: p\n  name: P\n  environments: [{name: e}]\n")
    outside = tmp_path / "outside.feature"
    outside.write_text("Feature: F\n")
    with pytest.raises(TestRunError, match="is outside the project"):
        run_scenario(root / "qa.yaml", outside, environment="e")


def test_execution_level_failure_is_shown_by_qa_test_and_show(project: Path) -> None:
    config = project / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    data["adapters"]["playwright"]["executable_path"] = "/nope/chrome"
    config.write_text(yaml.safe_dump(data))
    cli._write(project, cli.LOGIN)

    result = runner.invoke(app, ["test", "-s", "login.feature"])

    assert result.exit_code == 1
    message = "environment_error: playwright could not be prepared: cannot launch chromium"
    assert result.output.count(message) == 1  # shown once, not per case and again overall
    execution_id = result.output.split("execution ", 1)[1].split(":", 1)[0]
    shown = runner.invoke(app, ["execution", "show", execution_id]).output
    assert "  environment_error: playwright could not be prepared" in shown
