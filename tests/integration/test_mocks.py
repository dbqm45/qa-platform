"""Mocked dependencies: qa test --mock (TASK-051)."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from qa_cli.main import app
from qa_schemas.results import ExecutionReport

runner = CliRunner()

MOCK = """\
version: 1
responses:
  - request: GET /health
    json: {"status": "mocked"}
  - request: POST /orders
    status: 201
    json: {"id": 99, "product": "pear", "quantity": 4, "total": 6.0}
  - request: GET /orders
    json: [{"product": "apple", "quantity": 3}]
"""

HEALTH = """\
Feature: Health
  Scenario: Health
    When the client sends GET "/health"
    Then the response field "status" is "mocked"
"""


@pytest.fixture
def project(tmp_path: Path, shop_server: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    shop_server.state.reset()
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    (tmp_path / "mocks").mkdir()
    (tmp_path / "mocks" / "api.yaml").write_text(MOCK)
    _environment(tmp_path, {
        "name": "app", "services": {"api": f"{shop_server.url}/api"},
        "mocks": {"api": "mocks/api.yaml"},
    })  # fmt: skip
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _environment(project: Path, environment: dict[str, Any], **extra: Any) -> None:
    config = project / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    data["project"]["environments"] = [environment]
    data["project"]["default_environment"] = environment["name"]
    data.update(extra)
    config.write_text(yaml.safe_dump(data))


def _qa(project: Path, scenario: str, *args: str) -> tuple[int, str]:
    (project / "scenarios" / "s.feature").write_text(scenario)
    result = runner.invoke(app, ["test", "-s", "s.feature", *args])
    return result.exit_code, result.output


def _report(project: Path, output: str) -> ExecutionReport:
    line = next(line for line in output.splitlines() if "-> " in line)
    return ExecutionReport.model_validate_json((project / line.rsplit("-> ", 1)[1]).read_text())


def test_mocked_service_answers_instead_of_the_real_one(project: Path) -> None:
    code, output = _qa(project, HEALTH, "--mock", "api")

    assert code == 0, output
    assert "on app (mocked: api): 1 passed" in output
    report = _report(project, output)
    assert report.mocked == ("api",)
    [result] = report.results
    [evidence] = [e for e in result.evidence if e.kind == "http-exchanges"]
    exchange = json.loads((project / _results_dir(output) / evidence.path).read_text())
    assert exchange["exchanges"][0]["response"]["headers"]["x-qa-mock"] == "api"


def _results_dir(output: str) -> Path:
    line = next(line for line in output.splitlines() if "-> " in line)
    return Path(line.rsplit("-> ", 1)[1]).parent


def test_without_mock_the_real_service_is_used(project: Path) -> None:
    code, output = _qa(project, HEALTH)
    assert code == 1  # the real service says "ok"
    assert 'response field \'status\' is "ok", expected "mocked"' in output
    assert "mocked" not in output.split("Ran ", 1)[1].split(":")[0]


def test_request_the_mock_does_not_know_is_a_dependency_error(project: Path) -> None:
    scenario = HEALTH.replace('"/health"', '"/unknown?x=1"')

    code, output = _qa(project, scenario, "--mock", "api")

    assert code == 1
    assert (
        "dependency_error: mock 'api' has no response for GET /unknown "
        "(it knows: GET /health, POST /orders, GET /orders)"
    ) in output


def test_execution_show_and_json_summary_name_the_mocks(project: Path) -> None:
    _, output = _qa(project, HEALTH, "--mock", "api", "--json", "s.json")
    execution_id = output.split("execution ", 1)[1].split(":", 1)[0]
    assert "Mocked        api" in runner.invoke(app, ["execution", "show", execution_id]).output
    assert json.loads((project / "s.json").read_text())["mocked"] == ["api"]


def test_rerun_mocks_the_same_services(project: Path) -> None:
    _, output = _qa(project, HEALTH.replace('"mocked"', '"wrong"'), "--mock", "api")
    execution_id = output.split("execution ", 1)[1].split(":", 1)[0]
    (project / "scenarios" / "s.feature").write_text(HEALTH)

    result = runner.invoke(app, ["rerun", "--failed-only", execution_id])

    assert result.exit_code == 0, result.output
    assert "(mocked: api)" in result.output


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("unknown-name", "environment 'app' has no mock for 'payments' (mocks: api)"),
        ("missing-file", "mocks/api.yaml"),
        ("invalid-file", "responses[1].status: Input should be less than or equal to 599"),
        ("outside", "is outside the project"),
    ],
)
def test_mock_problems_are_reported(project: Path, change: str, message: str) -> None:
    args = ["--mock", "api"]
    if change == "unknown-name":
        args = ["--mock", "payments"]
    elif change == "missing-file":
        (project / "mocks" / "api.yaml").unlink()
    elif change == "invalid-file":
        (project / "mocks" / "api.yaml").write_text(MOCK.replace("status: 201", "status: 1000"))
    else:
        data = yaml.safe_load((project / "qa.yaml").read_text())
        data["project"]["environments"][0]["mocks"]["api"] = "../api.yaml"
        (project / "qa.yaml").write_text(yaml.safe_dump(data))

    code, output = _qa(project, HEALTH, *args)

    assert code == 1
    assert message in output


def test_mocks_must_replace_a_service(project: Path) -> None:
    data = yaml.safe_load((project / "qa.yaml").read_text())
    data["project"]["environments"][0]["mocks"]["payments"] = "mocks/p.yaml"
    (project / "qa.yaml").write_text(yaml.safe_dump(data))
    code, output = _qa(project, HEALTH, "--mock", "api")
    assert code == 1
    assert "mocks for unknown services: ['payments']" in output


def test_protected_environment_may_write_to_a_mock(project: Path, shop_server: Any) -> None:
    data = yaml.safe_load((project / "qa.yaml").read_text())
    data["project"]["environments"][0]["protected"] = True
    data["project"]["environments"][0]["setup"] = ["POST /reset"]  # skipped: mocked
    (project / "qa.yaml").write_text(yaml.safe_dump(data))
    order = (
        'Feature: O\n  Scenario: O\n    When the client sends POST "/orders" with:\n'
        '      """\n      {"product": "pear", "quantity": 4}\n      """\n'
        "    Then the response status is 201\n"
    )

    refused_code, refused = _qa(project, order)
    code, output = _qa(project, order, "--mock", "api")

    assert refused_code == 1 and "is protected (read-only)" in refused
    assert code == 0, output
    assert shop_server.state.orders == []  # nothing reached the real service
    log = next(
        p for p in (project / ".qa" / "executions").glob("*/execution.log")
        if '"mocked": ["api"]' in p.read_text()
    ).read_text()  # fmt: skip
    assert '"event": "hook-skipped", "phase": "setup", "request": "POST /reset"' in log


# --- Browser: the page's own API calls ---------------------------------------

APP_PAGE = """<!doctype html><title>Orders</title><body><ul id="orders"></ul><script>
fetch("https://api.example.invalid/v1/orders")
  .then(r => r.json())
  .then(items => { for (const i of items) {
      document.getElementById("orders").innerHTML += `<li>${i.product}</li>`; } })
  .catch(e => { document.body.innerHTML += "<p>failed: " + e + "</p>"; });
fetch("https://api.example.invalid/v1/orders", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: "{}"})
  .then(r => r.json()).then(o => { document.body.innerHTML += `<p>order ${o.id}</p>`; });
</script></body>"""


@pytest.fixture
def browser_project(
    tmp_path: Path,
    web_root: Path,
    web_server: str,
    browser_config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    (web_root / "orders-app.html").write_text(APP_PAGE)
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    (tmp_path / "mocks").mkdir()
    (tmp_path / "mocks" / "api.yaml").write_text(MOCK)
    _environment(
        tmp_path,
        {"name": "app", "base_url": web_server, "timeout_seconds": 3,
         "services": {"api": "https://api.example.invalid/v1"},
         "mocks": {"api": "mocks/api.yaml"}},
        adapters={"playwright": browser_config},
    )  # fmt: skip
    monkeypatch.chdir(tmp_path)
    return tmp_path


PAGE_SHOWS = """\
Feature: Orders page
  Scenario: Orders page
    Given the user opens "/orders-app.html"
    Then the page shows "apple"
    And the page shows "order 99"
"""


def test_browser_requests_to_a_mocked_service_are_answered(browser_project: Path) -> None:
    code, output = _qa(browser_project, PAGE_SHOWS, "--mock", "api")
    assert code == 0, output  # the real host does not even exist


def test_browser_request_the_mock_does_not_know(browser_project: Path) -> None:
    (browser_project / "mocks" / "api.yaml").write_text(
        'version: 1\nresponses:\n  - request: POST /orders\n    status: 201\n    json: {"id": 99}\n'
    )

    code, output = _qa(browser_project, PAGE_SHOWS, "--mock", "api")

    assert code == 1
    assert "ERROR     Orders page" in output  # not "failed": the application is not to blame
    assert (
        "dependency_error: playwright: mock 'api' has no response for GET /v1/orders" not in output
    )
    assert "dependency_error: playwright: mock 'api' has no response for GET /orders" in output
