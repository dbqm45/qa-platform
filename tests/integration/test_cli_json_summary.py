"""`qa test --json` (TASK-060): a versioned run summary for CI."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from qa_cli.main import app
from qa_schemas.results import ExecutionReport
from qa_schemas.summary import RunSummary
from tests.integration import test_cli_test as browser_cli

runner = CliRunner()
project_with_browser = browser_cli.project

API = """\
Feature: Orders
  Background:
    Given the client sends POST "/login" with:
      \"\"\"
      {"username": "bob", "password": "${SHOP_PASSWORD}"}
      \"\"\"
    And the client uses the token from "token"

  Scenario: Health
    When the client sends GET "/health"
    Then the response field "status" is "ok"

  Scenario: Wrong total
    When the client sends POST "/orders" with:
      \"\"\"
      {"product": "pear", "quantity": 4}
      \"\"\"
    Then the response field "total" is "7.0"

  Scenario: Unknown step
    When the client dances
    Then the response status is 200
"""


@pytest.fixture
def project(tmp_path: Path, shop_server: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    shop_server.state.reset()
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    api = f"api={shop_server.url}/api"
    args = ["project", "env", "add", "app", "--service", api, "--default", "-c"]
    assert runner.invoke(app, [*args, str(tmp_path / "qa.yaml")]).exit_code == 0
    (tmp_path / "scenarios" / "orders.feature").write_text(API)
    monkeypatch.setenv("SHOP_PASSWORD", "bob-password")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _summary(*args: str) -> tuple[int, str, RunSummary, dict[str, Any]]:
    result = runner.invoke(app, ["test", *args, "--json", "build/summary.json"])
    text = Path("build/summary.json").read_text()
    return result.exit_code, result.output, RunSummary.model_validate_json(text), json.loads(text)


def test_summary_of_a_mixed_run(project: Path) -> None:
    code, output, summary, raw = _summary("-s", "orders.feature")

    assert code == 1
    assert "summary: build/summary.json" in output
    assert raw["schema_version"] == 1
    assert (summary.project, summary.scenario, summary.environment) == (
        "shop", "scenarios/orders.feature", "app",
    )  # fmt: skip
    assert summary.ok is False
    assert summary.counts == {"failed": 1, "not_executed": 1, "passed": 1}
    health, total, unknown = summary.specifications

    assert (health.id, health.status, health.failures) == ("orders.health", "passed", ())
    assert health.source == "scenarios/orders.feature:9"
    assert health.results is not None and health.report is not None
    report = ExecutionReport.model_validate_json((project / health.results).read_text())
    assert report.execution.id == health.execution_id
    assert (project / health.report).is_file()
    assert health.duration_ms is not None

    [failure] = total.failures
    assert (failure.test_case_id, failure.classification.value, failure.step) == (
        "orders.wrong-total", "application_bug", 4,
    )  # fmt: skip
    assert failure.message == "response field 'total' is 6.0, expected 7.0"

    assert (unknown.compilation.value, unknown.status, unknown.execution_id) == (
        "blocked", None, None,
    )  # fmt: skip
    assert unknown.problem == "not executed (blocked): 1 step(s) cannot be resolved"


def test_secrets_are_masked_in_the_summary(project: Path) -> None:
    (project / "scenarios" / "orders.feature").write_text(
        API.replace('"/health"', '"/health?password=${SHOP_PASSWORD}"').replace(
            'the response field "status" is "ok"', 'the response field "status" is "bob-password"'
        )
    )
    _summary("-s", "orders.feature")
    text = Path("build/summary.json").read_text()
    assert "bob-password" not in text
    assert "********" in text


def test_validation_errors_are_in_the_summary(project: Path) -> None:
    (project / "scenarios" / "orders.feature").write_text("Feature: F\n  Scenario: Empty\n")

    code, _, summary, _ = _summary("-s", "orders.feature")

    assert code == 1
    assert summary.ok is False and summary.specifications == () and summary.counts == {}
    [error] = summary.errors
    assert (error.location, error.code) == ("scenarios/orders.feature:2", "scenario.no-steps")


def test_passing_run_is_ok(project: Path) -> None:
    (project / "scenarios" / "orders.feature").write_text(API.split("  Scenario: Wrong")[0])
    code, _, summary, _ = _summary("-s", "orders.feature")
    assert code == 0
    assert summary.ok is True and summary.counts == {"passed": 1}


def test_no_summary_when_the_request_is_invalid(project: Path) -> None:
    result = runner.invoke(app, ["test", "-s", "orders.feature", "-e", "nope", "--json", "s.json"])
    assert result.exit_code == 1
    assert not (project / "s.json").exists()


def test_unwritable_summary_is_an_error(project: Path) -> None:
    (project / "blocker").write_text("a file, not a directory")
    args = ["test", "-s", "orders.feature", "--json", "blocker/summary.json"]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "Error: cannot write blocker/summary.json" in result.output


def test_execution_level_failure_is_listed_once(project_with_browser: Path) -> None:
    config = project_with_browser / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    data["adapters"]["playwright"]["executable_path"] = "/nope/chrome"
    config.write_text(yaml.safe_dump(data))
    browser_cli._write(project_with_browser, browser_cli.LOGIN)

    _, _, summary, _ = _summary("-s", "login.feature")

    [spec] = summary.specifications
    [failure] = spec.failures  # the case's failure; the same execution failure is not repeated
    assert failure.test_case_id == "login.successful-login"
    assert failure.classification.value == "environment_error"
    assert failure.step is None
