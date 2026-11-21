"""`qa test` end to end against the Example Shop in a real browser (TASK-062)."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from qa_cli.main import app
from qa_core.storage import ExecutionRepository, open_database
from qa_schemas.enums import ExecutionStatus
from qa_schemas.results import ExecutionReport

runner = CliRunner()

LOGIN = """\
Feature: Login
  Background:
    Given the user opens "/login"

  Scenario: Successful login
    When the user fills "Username" with "alice"
    And the user fills "Password" with "correct-password"
    And the user clicks "Log in"
    Then the URL is "/dashboard"
    And the page shows "Welcome, Alice"
"""

WRONG = """\
  Scenario: Wrong password shows the dashboard
    When the user fills "Username" with "bob"
    And the user fills "Password" with "wrong"
    And the user clicks "Log in"
    Then the page shows "Welcome"
"""


@pytest.fixture
def project(
    tmp_path: Path,
    shop_server: Any,
    browser_config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    shop_server.state.reset()
    assert (
        runner.invoke(app, ["init", str(tmp_path), "--id", "shop", "--name", "Shop"]).exit_code == 0
    )
    config = tmp_path / "qa.yaml"
    for args in (
        ["env", "add", "app", "--base-url", shop_server.url, "--timeout", "3", "--default"],
        ["env", "add", "down", "--base-url", "http://127.0.0.1:9"],
    ):
        assert runner.invoke(app, ["project", *args, "-c", str(config)]).exit_code == 0
    adapters = yaml.safe_dump({"adapters": {"playwright": browser_config}})
    config.write_text(config.read_text() + "\n" + adapters)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(project: Path, content: str, name: str = "login.feature") -> None:
    (project / "scenarios" / name).write_text(content)


def _test(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["test", *args])
    return result.exit_code, result.output


def _report(project: Path, output: str) -> ExecutionReport:
    line = next(line for line in output.splitlines() if "-> " in line)
    path = project / line.rsplit("-> ", 1)[1].strip()
    return ExecutionReport.model_validate_json(path.read_text())


def test_passing_scenario(project: Path) -> None:
    _write(project, LOGIN)

    code, output = _test("-s", "login.feature")

    assert code == 0, output
    assert "login.successful-login  (scenarios/login.feature:5)" in output
    assert "  PASSED    Successful login" in output
    assert "Ran 1 specification from scenarios/login.feature on app: 1 passed" in output
    report = _report(project, output)
    assert report.execution.status is ExecutionStatus.PASSED
    assert [s.action for s in report.results[0].steps][:2] == ["browser.open", "ui.fill"]


def test_results_and_status_are_persisted(project: Path) -> None:
    _write(project, LOGIN)
    _, output = _test("-s", "scenarios/login.feature")
    report = _report(project, output)

    execution_dir = project / ".qa" / "executions" / report.execution.id
    assert (execution_dir / "results.json").is_file()
    assert (execution_dir / "login.successful-login" / "page.json").is_file()
    with open_database(project / ".qa" / "qa.db") as db:
        stored = ExecutionRepository(db).get(report.execution.id)
    assert stored is not None and stored.status is ExecutionStatus.PASSED
    assert stored.environment == "app"


def test_failing_scenario(project: Path) -> None:
    _write(project, LOGIN + "\n" + WRONG)

    code, output = _test("-s", "login.feature")

    assert code == 1
    assert "  FAILED    Wrong password shows the dashboard" in output
    assert "application_bug: the page does not show 'Welcome'" in output
    assert "screenshot: .qa/executions/" in output
    assert "Ran 2 specifications from scenarios/login.feature on app: 1 failed, 1 passed" in output
    screenshot = output.split("screenshot: ", 1)[1].split()[0]
    assert (project / screenshot).read_bytes().startswith(b"\x89PNG")


def test_html_report_is_written_next_to_the_evidence(project: Path) -> None:
    _write(project, LOGIN + "\n" + WRONG)
    _, output = _test("-s", "login.feature")

    reports = [line.split("report: ", 1)[1] for line in output.splitlines() if "report: " in line]
    assert len(reports) == 2
    failed = (project / reports[1]).read_text()
    assert "Wrong password shows the dashboard" in failed
    assert "<img class=shot src='login.wrong-password-shows-the-dashboard/screenshot.png'" in failed
    assert (
        (project / reports[1])
        .parent.joinpath("login.wrong-password-shows-the-dashboard", "screenshot.png")
        .is_file()
    )


def test_unreachable_environment_is_an_error(project: Path) -> None:
    _write(project, LOGIN)
    code, output = _test("-s", "login.feature", "-e", "down")
    assert code == 1
    assert "  ERROR     Successful login" in output
    assert "environment_error: cannot open /login" in output


def test_blocked_specification_is_not_executed(project: Path) -> None:
    _write(project, LOGIN.replace("Then the URL is", "Then the user is happy and the URL is"))
    code, output = _test("-s", "login.feature")
    assert code == 1
    assert "NOT RUN  not executed (blocked): 1 step(s) cannot be resolved" in output
    assert (
        "           line 9: expectation 'the user is happy and the URL is \"/dashboard\"'" in output
    )
    assert "1 not executed" in output
    assert not (project / ".qa" / "executions").exists() or not any(
        (project / ".qa" / "executions").iterdir()
    )


def test_invalid_file_is_reported(project: Path) -> None:
    _write(project, 'Feature: F\n  Scenario:\n    Given the user opens "/login"\n')
    code, output = _test("-s", "login.feature")
    assert code == 1
    assert "[scenario.missing-name]" in output
    assert "nothing was executed" in output


def test_incompatible_mode_is_rejected(project: Path) -> None:
    _write(project, LOGIN)
    code, output = _test("-s", "login.feature", "--mode", "be")
    assert code == 1
    assert "NOT RUN  not executed: be mode runs without a browser" in output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["-s", "missing.feature"], "scenario file missing.feature not found"),
        (
            ["-s", "login.feature", "-e", "prod"],
            "unknown environment 'prod'; known: local, app, down",
        ),
        (["-s", "qa.yaml"], "unsupported file type; expected .feature"),
    ],
)
def test_bad_requests(project: Path, args: list[str], message: str) -> None:
    _write(project, LOGIN)
    code, output = _test(*args)
    assert code == 1
    assert message in output


def test_invalid_mode_is_a_usage_error(project: Path) -> None:
    code, _ = _test("-s", "login.feature", "--mode", "e2e")
    assert code == 2


def test_timeout_option(project: Path) -> None:
    _write(project, LOGIN)
    code, output = _test("-s", "login.feature", "--timeout", "120")
    assert code == 0, output
    plan_id = _report(project, output).execution.plan_id
    assert plan_id == "login.successful-login.fe.app"


@pytest.mark.parametrize("value", ["0", "-5", "100000"])
def test_invalid_timeout_is_a_usage_error(project: Path, value: str) -> None:
    code, _ = _test("-s", "login.feature", "--timeout", value)
    assert code == 2
