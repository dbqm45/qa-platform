"""Contract mode: API responses checked against OpenAPI (TASK-054)."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from qa_cli.main import app
from qa_schemas.results import ExecutionReport

runner = CliRunner()
EXAMPLES = Path(__file__).parents[2] / "examples"
CONTRACT = EXAMPLES / "openapi" / "shop-api.yaml"


@pytest.fixture
def project(tmp_path: Path, shop_server: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    shop_server.state.reset()
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    (tmp_path / "openapi").mkdir()
    shutil.copy(CONTRACT, tmp_path / "openapi" / "shop-api.yaml")
    shutil.copy(EXAMPLES / "scenarios" / "api.feature", tmp_path / "scenarios" / "api.feature")
    _environment(tmp_path, services={"api": f"{shop_server.url}/api"},
                 contracts={"api": "openapi/shop-api.yaml"})  # fmt: skip
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _environment(project: Path, **fields: Any) -> None:
    config = project / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    data["project"]["environments"] = [{"name": "app", **fields}]
    data["project"]["default_environment"] = "app"
    config.write_text(yaml.safe_dump(data))


def _contract(project: Path, old: str, new: str) -> None:
    path = project / "openapi" / "shop-api.yaml"
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def _qa(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["test", *args])
    return result.exit_code, result.output


def test_example_api_keeps_its_contract(project: Path) -> None:
    code, output = _qa("-s", "api.feature", "--mode", "contract")

    assert code == 0, output
    assert "Ran 4 specifications from scenarios/api.feature on app: 4 passed" in output
    [evidence] = project.glob(".qa/executions/*/api.placing-an-order/http.json")
    assert json.loads(evidence.read_text())["contract_checks"] == [
        "api: POST /login 200", "api: POST /orders 201",
    ]  # fmt: skip


def test_body_that_breaks_the_contract_fails(project: Path) -> None:
    _contract(project, "total: {type: number, minimum: 0}", "total: {type: string}")

    code, output = _qa("-s", "api.feature", "--mode", "contract")

    assert code == 1
    assert (
        "application_bug: POST /orders (201): the body does not match the contract at "
        "$.total: 6.0 is not of type 'string'"
    ) in output
    assert "1 failed, 3 passed" in output


def test_undocumented_status(project: Path) -> None:
    _contract(
        project, '        "401": {$ref: "#/components/responses/Error"}\n    post:', "    post:"
    )
    code, output = _qa("-s", "api.feature", "--mode", "contract")
    assert code == 1
    assert "GET /orders: status 401 is not in the contract (documented: 200)" in output


def test_undocumented_operation_is_requirement_ambiguity(project: Path) -> None:
    (project / "scenarios" / "r.feature").write_text(
        'Feature: R\n  Scenario: R\n    When the client sends POST "/reset-everything"\n'
        "    Then the response status is 404\n"
    )
    code, output = _qa("-s", "r.feature", "--mode", "contract")
    assert code == 1
    assert "ERROR     R" in output
    assert (
        "requirement_ambiguity: contract 'api' does not describe POST /reset-everything" in output
    )


def test_other_modes_do_not_check_the_contract(project: Path) -> None:
    _contract(project, "total: {type: number, minimum: 0}", "total: {type: string}")
    code, _ = _qa("-s", "api.feature")  # be mode
    assert code == 0


def test_rerun_keeps_contract_mode(project: Path) -> None:
    _contract(project, "total: {type: number, minimum: 0}", "total: {type: string}")
    _, output = _qa("-s", "api.feature", "--mode", "contract")
    failed = next(line.split()[1].rstrip(":") for line in output.splitlines()
                  if "execution " in line and ": FAILED" in line)  # fmt: skip
    _contract(project, "total: {type: string}", "total: {type: number, minimum: 0}")

    result = runner.invoke(app, ["rerun", "--failed-only", failed])

    assert result.exit_code == 0, result.output
    report = next(
        ExecutionReport.model_validate_json(p.read_text())
        for p in project.glob(".qa/executions/*/results.json")
        if json.loads(p.read_text())["execution"].get("rerun_of") == failed
    )
    assert report.execution.mode.value == "contract"


# --- Without the full stack: mocks checked against the contract ----------------


def test_mock_checked_against_the_contract_without_the_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    (tmp_path / "openapi").mkdir()
    shutil.copy(CONTRACT, tmp_path / "openapi" / "shop-api.yaml")
    (tmp_path / "mocks").mkdir()
    mock = (
        "version: 1\nresponses:\n  - request: GET /health\n    json: {status: ok}\n"
        "  - request: GET /orders\n    json: {orders: [{id: 1, user: bob, product: kiwi,"
        " quantity: 2, total: 1.0}]}\n"
    )
    (tmp_path / "mocks" / "api.yaml").write_text(mock)
    _environment(
        tmp_path,
        services={"api": "http://127.0.0.1:9/api"},  # nothing runs there
        contracts={"api": "openapi/shop-api.yaml"},
        mocks={"api": "mocks/api.yaml"},
    )
    (tmp_path / "scenarios" / "m.feature").write_text(
        "Feature: M\n"
        '  Scenario: Health\n    When the client sends GET "/health"\n'
        "    Then the response status is 200\n"
        '  Scenario: Orders\n    When the client sends GET "/orders"\n'
        "    Then the response status is 200\n"
    )
    monkeypatch.chdir(tmp_path)

    code, output = _qa("-s", "m.feature", "--mode", "contract", "--mock", "api")

    assert code == 1
    assert "PASSED    Health" in output
    assert "$.orders[0].product: 'kiwi' is not one of ['apple', 'pear', 'plum']" in output
    assert "on app (mocked: api): 1 failed, 1 passed" in output


# --- Configuration problems -------------------------------------------------------


def test_contract_mode_needs_contracts(project: Path, shop_server: Any) -> None:
    _environment(project, services={"api": f"{shop_server.url}/api"})
    code, output = _qa("-s", "api.feature", "--mode", "contract")
    assert code == 1
    assert "contract mode needs contracts: in environment 'app'" in output


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "contract file not found"),
        ("swagger: '2.0'\npaths: {/a: {}}\n", "openapi must be 3.0.x or 3.1.x, got 'nothing'"),
        ("openapi: 3.1.0\n", "the document has no paths"),
        ("openapi: [unclosed\n", "invalid YAML"),
    ],
)
def test_unusable_contract_files(project: Path, content: str | None, message: str) -> None:
    path = project / "openapi" / "shop-api.yaml"
    if content is None:
        path.unlink()
    else:
        path.write_text(content)
    code, output = _qa("-s", "api.feature", "--mode", "contract")
    assert code == 1
    assert message in output


def test_contracts_must_describe_a_service(project: Path) -> None:
    _environment(project, services={"api": "http://x/api"}, contracts={"pay": "openapi/p.yaml"})
    code, output = _qa("-s", "api.feature", "--mode", "contract")
    assert code == 1
    assert "contracts for unknown services: ['pay']" in output
