"""`qa rerun [--failed-only] <execution_id>` (TASK-064)."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qa_cli.main import app
from qa_core.storage import ExecutionRepository, open_database
from qa_schemas.results import ExecutionReport

runner = CliRunner()

ORDERS = """\
Feature: Orders
  Background:
    Given the client sends POST "/login" with:
      \"\"\"
      {"username": "bob", "password": "bob-password"}
      \"\"\"
    And the client uses the token from "token"

  Scenario Outline: Order <product>
    When the client sends POST "/orders" with:
      \"\"\"
      {"product": "<product>", "quantity": 2}
      \"\"\"
    Then the response status is <status>

    Examples:
      | product | status |
      | apple   | 201    |
      | kiwi    | 201    |
      | pear    | 201    |
"""


@pytest.fixture
def project(tmp_path: Path, shop_server: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    shop_server.state.reset()
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    args = ["project", "env", "add", "app", "--service", f"api={shop_server.url}/api"]
    assert runner.invoke(app, [*args, "--default", "-c", str(tmp_path / "qa.yaml")]).exit_code == 0
    (tmp_path / "scenarios" / "orders.feature").write_text(ORDERS)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _qa(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def _execution_ids(output: str) -> list[str]:
    return [line.split()[1].rstrip(":") for line in output.splitlines() if "  execution " in line]


def _report(project: Path, execution_id: str) -> ExecutionReport:
    path = project / ".qa" / "executions" / execution_id / "results.json"
    return ExecutionReport.model_validate_json(path.read_text())


def _failed_run(project: Path) -> str:
    code, output = _qa("test", "-s", "orders.feature")
    assert code == 1, output  # kiwi is not a product: 422
    [execution_id] = _execution_ids(output)
    return execution_id


def test_failed_only_reruns_just_the_failed_case(project: Path) -> None:
    original = _failed_run(project)
    assert [r.status.value for r in _report(project, original).results] == [
        "passed", "failed", "passed",
    ]  # fmt: skip

    code, output = _qa("rerun", "--failed-only", original)

    assert code == 1  # kiwi still fails
    [rerun] = _execution_ids(output)
    results = _report(project, rerun).results
    assert [(r.test_case_id, r.name) for r in results] == [("orders.order-product:2", "Order kiwi")]
    with open_database(project / ".qa" / "qa.db") as db:
        stored = ExecutionRepository(db).get(rerun)
    assert stored is not None and stored.rerun_of == original
    assert f"Rerun of      {original}" in _qa("execution", "show", rerun)[1]


def test_without_flag_everything_is_rerun_with_the_original_settings(project: Path) -> None:
    original = _failed_run(project)

    _, output = _qa("rerun", original[:-2])  # a unique prefix is enough

    [rerun] = _execution_ids(output)
    report = _report(project, rerun)
    assert len(report.results) == 3
    first = _report(project, original).execution
    assert (report.execution.mode, report.execution.category, report.execution.environment) == (
        first.mode, first.category, first.environment,
    )  # fmt: skip


def test_fixed_scenario_passes_and_the_change_is_reported(project: Path) -> None:
    original = _failed_run(project)
    scenario = project / "scenarios" / "orders.feature"
    scenario.write_text(ORDERS.replace("| kiwi    | 201    |", "| kiwi    | 422    |"))

    code, output = _qa("rerun", "--failed-only", original)

    assert code == 0, output
    assert output.startswith(
        f"Warning: scenario 'Order <product>' changed since execution {original}; "
        "running the current version\n"
    )


def test_failed_case_that_no_longer_exists(project: Path) -> None:
    original = _failed_run(project)
    scenario = project / "scenarios" / "orders.feature"
    scenario.write_text(ORDERS.replace("      | kiwi    | 201    |\n", ""))

    code, output = _qa("rerun", "--failed-only", original)

    assert code == 1
    # pear moved to position 2, kiwi's old id: it must not run in kiwi's place
    expected = "Error: no longer in the scenario: orders.order-product:2 (Order kiwi);"
    assert expected in output
    assert "PASSED" not in output


def test_some_failed_cases_gone_others_rerun(project: Path) -> None:
    scenario = project / "scenarios" / "orders.feature"
    scenario.write_text(ORDERS.replace("| pear    | 201    |", "| plum    | 400    |"))
    original = _failed_run(project)  # kiwi (2) and plum (3) fail
    scenario.write_text(ORDERS.replace("| pear    | 201    |", "| fig     | 201    |"))

    code, output = _qa("rerun", "--failed-only", original)

    skipped = "Warning: no longer in the scenario, skipped: orders.order-product:3 (Order plum)"
    assert skipped in output
    [rerun] = _execution_ids(output)
    assert [r.name for r in _report(project, rerun).results] == ["Order kiwi"]
    assert code == 1


def test_nothing_to_rerun_after_a_pass(project: Path) -> None:
    (project / "scenarios" / "orders.feature").write_text(
        ORDERS.replace("      | kiwi    | 201    |\n", "")
    )
    _, output = _qa("test", "-s", "orders.feature")
    [passed] = _execution_ids(output)

    assert _qa("rerun", "--failed-only", passed) == (
        0, f"Nothing to rerun: every test case of execution {passed} passed\n",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("remove-results", "has no results.json; it cannot be rerun"),
        ("old-results", "was recorded before reruns were supported"),
        ("remove-environment", "environment 'app' of execution"),
        ("rename-scenario", "is no longer in scenarios/orders.feature"),
    ],
)
def test_executions_that_cannot_be_rerun(project: Path, change: str, message: str) -> None:
    original = _failed_run(project)
    results = project / ".qa" / "executions" / original / "results.json"
    if change == "remove-results":
        results.unlink()
    elif change == "old-results":
        data = json.loads(results.read_text())
        del data["source"]
        results.write_text(json.dumps(data))
    elif change == "remove-environment":
        config = project / "qa.yaml"
        config.write_text(config.read_text().replace("name: app", "name: other"))
        config.write_text(config.read_text().replace("default_environment: app", ""))
    else:
        scenario = project / "scenarios" / "orders.feature"
        scenario.write_text(ORDERS.replace("Order <product>", "Buy <product>"))

    code, output = _qa("rerun", original)

    assert code == 1
    assert message in output


def test_rerun_writes_a_json_summary(project: Path) -> None:
    original = _failed_run(project)
    _qa("rerun", "--failed-only", original, "--json", "rerun.json")
    summary = json.loads((project / "rerun.json").read_text())
    assert summary["counts"] == {"failed": 1}
    assert summary["specifications"][0]["id"] == "orders.order-product"
