"""Environment setup and cleanup requests (TASK-056)."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from qa_cli.main import app
from qa_schemas.project import Environment
from qa_schemas.results import ExecutionReport

runner = CliRunner()

CAROL_SIGNS_IN = """\
Feature: Carol
  Scenario: Carol signs in
    When the client sends POST "/login" with:
      \"\"\"
      {"username": "carol", "password": "carol-password"}
      \"\"\"
    Then the response status is 200
"""

ORDER = """\
Feature: Order
  Scenario: Order
    When the client sends POST "/login" with:
      \"\"\"
      {"username": "bob", "password": "bob-password"}
      \"\"\"
    And the client uses the token from "token"
    And the client sends POST "/orders" with:
      \"\"\"
      {"product": "pear", "quantity": 1}
      \"\"\"
    Then the response status is 418
"""


@pytest.fixture
def project(tmp_path: Path, shop_server: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    shop_server.state.reset()
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    args = ["project", "env", "add", "app", "--service", f"api={shop_server.url}/api"]
    assert runner.invoke(app, [*args, "--default", "-c", str(tmp_path / "qa.yaml")]).exit_code == 0
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _hooks(project: Path, **hooks: Any) -> None:
    config = project / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    [environment] = [e for e in data["project"]["environments"] if e["name"] == "app"]
    environment.update(hooks)
    config.write_text(yaml.safe_dump(data))


def _test(project: Path, content: str) -> tuple[int, str, ExecutionReport]:
    (project / "scenarios" / "s.feature").write_text(content)
    result = runner.invoke(app, ["test", "-s", "s.feature"])
    line = next(line for line in result.output.splitlines() if "-> " in line)
    report = ExecutionReport.model_validate_json((project / line.rsplit("-> ", 1)[1]).read_text())
    return result.exit_code, result.output, report


def _lock_carol(shop_server: Any) -> None:
    for _ in range(3):
        shop_server.state.sign_in("carol", "wrong")
    assert shop_server.state.sign_in("carol", "carol-password") == (None, "Account locked")


def test_setup_runs_before_the_test_cases(project: Path, shop_server: Any) -> None:
    _lock_carol(shop_server)
    _hooks(project, setup=["POST /reset"])

    code, output, _ = _test(project, CAROL_SIGNS_IN)

    assert code == 0, output  # the reset unlocked carol first
    log = next((project / ".qa" / "executions").glob("*/execution.log")).read_text()
    assert '"event": "hook-finished", "phase": "setup", "request": "POST /reset"' in log


def test_cleanup_runs_after_a_failure(project: Path, shop_server: Any) -> None:
    _hooks(project, cleanup=["POST /reset"])

    code, _, report = _test(project, ORDER)  # places an order, then fails

    assert code == 1 and report.execution.status.value == "failed"
    assert shop_server.state.orders == []  # cleanup removed it
    assert report.cleanup_errors == ()


def test_failing_setup_stops_the_execution_but_cleanup_runs(
    project: Path, shop_server: Any
) -> None:
    _hooks(project, setup=["POST /nope"], cleanup=["POST /reset"])
    shop_server.state.orders.append({"product": "plum"})

    code, output, report = _test(project, CAROL_SIGNS_IN)

    assert code == 1
    message = "environment setup failed: setup POST /nope answered 404"
    [result] = report.results
    assert result.status.value == "error" and result.steps == ()
    assert result.failure is not None and result.failure.message == message
    assert result.failure.classification.value == "environment_error"
    assert message in output
    assert shop_server.state.orders == []


def test_failing_cleanup_does_not_change_the_result(project: Path) -> None:
    _hooks(project, cleanup=["POST /nope"])

    code, output, report = _test(project, CAROL_SIGNS_IN)

    assert code == 0  # the test passed; cleanup problems are reported separately
    assert report.cleanup_errors == ("environment: cleanup POST /nope answered 404",)
    assert "cleanup: environment: cleanup POST /nope answered 404" in output


def test_unreachable_setup_target(project: Path) -> None:
    _hooks(project, setup=["POST http://127.0.0.1:9/reset"])
    _, _, report = _test(project, CAROL_SIGNS_IN)
    assert report.failure is not None
    assert report.failure.message.startswith(
        "environment setup failed: setup POST http://127.0.0.1:9/reset failed:"
    )


def test_protected_environment_refuses_write_hooks(project: Path, shop_server: Any) -> None:
    _hooks(project, setup=["POST /reset"], protected=True)
    (project / "scenarios" / "s.feature").write_text(
        'Feature: H\n  Scenario: H\n    When the client sends GET "/health"\n'
        "    Then the response status is 200\n"
    )
    _lock_carol(shop_server)

    blocked = runner.invoke(app, ["test", "-s", "s.feature"]).output
    allowed = runner.invoke(app, ["test", "-s", "s.feature", "--allow-writes"])

    assert (
        "environment setup failed: setup POST /reset was not sent: environment 'app' is "
        "protected (read-only); use --allow-writes to run it anyway"
    ) in blocked
    assert allowed.exit_code == 0, allowed.output
    assert shop_server.state.sign_in("carol", "carol-password")[1] is None  # reset happened


@pytest.mark.parametrize("hook", ["RESET /x", "POST reset", "POST", "post /reset", "POST /a b"])
def test_invalid_hooks_are_rejected(hook: str) -> None:
    with pytest.raises(ValidationError, match="setup"):
        Environment(name="e", setup=(hook,))
