"""Protected (read-only) environments and --allow-writes (TASK-056)."""

from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from qa_cli.main import app
from qa_core.redaction import Redactor
from qa_execution.http.adapter import HttpSession
from qa_execution.http.config import HttpConfig
from qa_execution.protection import ProtectedEnvironmentError
from tests.integration import test_cli_test as browser_cli

runner = CliRunner()
browser_project = browser_cli.project

READ = """\
Feature: Health
  Scenario: Health
    When the client sends GET "/health"
    Then the response field "status" is "ok"
"""

WRITE = """\
Feature: Orders
  Scenario Outline: Order <n>
    When the client sends POST "/orders" with:
      \"\"\"
      {"product": "pear", "quantity": <n>}
      \"\"\"
    Then the response status is 401

    Examples:
      | n |
      | 1 |
      | 2 |
"""


@pytest.fixture
def project(tmp_path: Path, shop_server: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    args = ["project", "env", "add", "prod", "--service", f"api={shop_server.url}/api"]
    result = runner.invoke(
        app, [*args, "--protected", "--default", "-c", str(tmp_path / "qa.yaml")]
    )
    assert result.exit_code == 0, result.output
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _qa(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def test_env_add_protected_and_project_show(project: Path) -> None:
    config = yaml.safe_load((project / "qa.yaml").read_text())
    [_, prod] = config["project"]["environments"]
    assert prod["protected"] is True
    assert "  prod  (default)  (protected: read-only)" in _qa("project", "show")[1]


def test_read_only_scenario_runs(project: Path) -> None:
    (project / "scenarios" / "health.feature").write_text(READ)
    code, output = _qa("test", "-s", "health.feature")
    assert code == 0, output


def test_writing_scenario_is_not_executed(project: Path) -> None:
    (project / "scenarios" / "orders.feature").write_text(WRITE)
    code, output = _qa("test", "-s", "orders.feature")

    assert code == 1
    assert (
        "NOT RUN  not executed: environment 'prod' is protected (read-only) and these steps "
        'would change data: line 3: When the client sends POST "/orders" with:; '
        "use --allow-writes to run it anyway"
    ) in output  # the outline step is listed once, not per example
    assert not (project / ".qa" / "executions").exists() or not any(
        (project / ".qa" / "executions").iterdir()
    )


def test_allow_writes_runs_it(project: Path) -> None:
    (project / "scenarios" / "orders.feature").write_text(WRITE)
    code, output = _qa("test", "-s", "orders.feature", "--allow-writes")
    assert code == 0, output  # 401 without a token, as the scenario expects


def test_http_session_refuses_writes_from_any_step() -> None:
    sent: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request.method)
        return httpx.Response(200)

    transport = httpx.MockTransport(handle)
    session = HttpSession(
        client=httpx.Client(transport=transport, base_url="http://shop"),
        config=HttpConfig(), redactor=Redactor(), base_url="http://shop",
        read_only=True, environment="prod",
    )  # fmt: skip

    session.send("GET", "/health")
    with pytest.raises(ProtectedEnvironmentError, match="DELETE /orders/1 was not sent"):
        session.send("delete", "/orders/1")

    assert sent == ["GET"]


def _protect(project: Path) -> None:
    config = project / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    for environment in data["project"]["environments"]:
        if environment["name"] == "app":
            environment["protected"] = True
    config.write_text(yaml.safe_dump(data))


def test_browser_blocks_a_form_that_a_click_submits(browser_project: Path) -> None:
    _protect(browser_project)
    browser_cli._write(
        browser_project,
        'Feature: F\n  Scenario: Click only\n    Given the user opens "/login"\n'
        '    When the user clicks "Log in"\n    Then the page shows "Log in"\n',
    )

    code, output = _qa("test", "-s", "login.feature")

    assert code == 1
    assert "ERROR     Click only" in output
    message = "environment_error: playwright: the page tried to change data in protected"
    assert f"{message} environment 'app'; blocked: POST http://127.0.0.1:" in output
    assert "/login; use --allow-writes" in output
    [result] = browser_cli._report(browser_project, output).results
    assert result.failure is not None and result.failure.step_index is None
    [note] = result.notes  # the assertion that failed because of the block
    assert note.startswith("step 3 then failed: the page does not show 'Log in'")


def test_browser_navigation_is_allowed(browser_project: Path) -> None:
    _protect(browser_project)
    browser_cli._write(
        browser_project,
        'Feature: F\n  Scenario: Look\n    Given the user opens "/login"\n'
        '    Then "Username" is visible\n',
    )
    code, output = _qa("test", "-s", "login.feature")
    assert code == 0, output
