"""TASK-072 — the first complete vertical slice, on the real examples.

    Gherkin file -> Scenario Parser -> Test Specification -> Step Registry
    -> Execution Plan -> Local Runner -> Playwright -> Test Results
    -> Evidence -> HTML Report

The examples (``examples/qa.yaml`` and ``examples/scenarios``) are copied into
a fresh directory and driven only through the ``qa`` command, exactly as a
user would, against the Example Shop in a real browser.
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from qa_cli.main import app
from qa_core.storage import ExecutionRepository, open_database
from qa_schemas.compilation import CompiledSpecification
from qa_schemas.enums import CompilationStatus, ExecutionStatus
from qa_schemas.results import ExecutionReport

ROOT = Path(__file__).parents[2]
runner = CliRunner()

EXPECTED_CASES = {
    "login.successful-login",
    "login.invalid-login",
    "login.account-is-locked-after-three-failed-sign-ins",
    "contact.sending-a-message",
    "contact.invalid-input-is-rejected-problem:1",
    "contact.invalid-input-is-rejected-problem:2",
}


@pytest.fixture
def project(
    tmp_path: Path,
    shop_server: Any,
    browser_config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """A copy of the examples pointing at the running Example Shop."""
    shop_server.state.reset()
    shutil.copy(ROOT / "examples/qa.yaml", tmp_path / "qa.yaml")
    shutil.copytree(ROOT / "examples/scenarios", tmp_path / "scenarios")
    config = tmp_path / "qa.yaml"
    text = config.read_text().replace("http://localhost:8000", shop_server.url)
    config.write_text(text + "\n" + yaml.safe_dump({"adapters": {"playwright": browser_config}}))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _qa(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def _reports(project: Path, output: str) -> list[ExecutionReport]:
    paths = [line.rsplit("-> ", 1)[1] for line in output.splitlines() if "-> " in line]
    return [ExecutionReport.model_validate_json((project / p).read_text()) for p in paths]


def _run_examples(project: Path) -> list[ExecutionReport]:
    reports = []
    for scenario in ("login.feature", "contact.feature"):
        code, output = _qa("test", "--scenario", scenario, "--environment", "local")
        assert code == 0, output
        reports.extend(_reports(project, output))
    return reports


def test_complete_vertical_slice(project: Path) -> None:
    # Project initialization
    code, output = _qa("init")
    assert code == 0, output

    # Gherkin file -> Scenario Parser (validation)
    code, output = _qa("scenario", "validate")
    assert (code, output.strip()) == (0, "Validated 2 files, 5 scenarios: 0 errors, 0 warnings")

    # -> Test Specification -> Step Registry (compilation)
    code, output = _qa("scenario", "compile")
    assert code == 0, output
    assert "Compiled 5 specifications from 2 files: 5 ready" in output
    compiled = CompiledSpecification.model_validate_json(
        (project / ".qa/specifications/login.successful-login.json").read_text()
    )
    assert compiled.status is CompilationStatus.READY
    actions = [s.action for s in compiled.specification.test_cases[0].steps]
    assert actions == [
        "browser.open", "ui.fill", "ui.fill", "ui.click",
        "ui.url-is", "ui.visible", "ui.text-present",
    ]  # fmt: skip
    assert compiled.specification.required_capabilities == ("browser",)

    # -> Execution Plan -> Local Runner -> Playwright -> Test Results
    reports = _run_examples(project)
    results = {r.test_case_id: r for report in reports for r in report.results}
    assert set(results) == EXPECTED_CASES
    assert {r.status for r in results.values()} == {ExecutionStatus.PASSED}
    assert {report.execution.mode.value for report in reports} == {"fe"}

    for report in reports:
        directory = project / ".qa/executions" / report.execution.id
        # -> Evidence
        for result in report.results:
            page_info = directory / result.test_case_id.replace(":", "_") / "page.json"
            assert json.loads(page_info.read_text())["url"].startswith("http://127.0.0.1")
        # -> HTML Report
        html = (directory / "report.html").read_text()
        assert report.execution.id in html and "status passed" in html

    # Execution history survives in the local database
    with open_database(project / ".qa/qa.db") as db:
        history = ExecutionRepository(db).list_for_project("shop")
    assert {e.id for e in history} == {r.execution.id for r in reports}
    assert {e.status for e in history} == {ExecutionStatus.PASSED}

    # The whole flow works without an LLM client
    assert not any(name.split(".")[0] in {"anthropic", "openai"} for name in sys.modules)


def test_results_are_deterministic(project: Path) -> None:
    """Running the same scenarios again against the same application gives the same results,
    including the lockout scenario, whose account stays locked."""
    assert _qa("init")[0] == 0

    first = _run_examples(project)
    second = _run_examples(project)

    def outcome(reports: list[ExecutionReport]) -> dict[str, tuple[str, int]]:
        return {
            r.test_case_id: (r.status.value, len(r.steps))
            for report in reports
            for r in report.results
        }

    assert outcome(first) == outcome(second)
    assert len({r.execution.id for r in first + second}) == len(first) * 2
