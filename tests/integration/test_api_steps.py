"""API steps against the Example Shop through the real runner (TASK-045..049)."""

import json
import socket
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from qa_core.scenarios.compilation import compile_documents
from qa_core.scenarios.parsing import parse_document
from qa_execution.builtin import builtin_adapters, builtin_registry
from qa_execution.planning import create_plan
from qa_execution.runner import ExecutionRequest, LocalRunner
from qa_schemas.compilation import CompiledSpecification
from qa_schemas.enums import (
    CompilationStatus,
    ExecutionStatus,
    FailureClassification,
    ScenarioFormat,
)
from qa_schemas.project import Environment
from qa_schemas.results import ExecutionReport, TestResult
from qa_schemas.scenario import ScenarioDocument, content_hash

S, C = ExecutionStatus, FailureClassification

SIGN_IN = """\
    Given the client sends POST "/login" with:
      \"\"\"
      {"username": "alice", "password": "correct-password"}
      \"\"\"
    And the client uses the token from "token"
"""


def _steps(*lines: str) -> str:
    """Scenario body: one step per argument, indented."""
    return "".join(f"    {line}\n" for line in lines)


def _compile(body: str) -> CompiledSpecification:
    content = f"Feature: API\n  Scenario: Call\n{body}"
    document = ScenarioDocument(
        path=PurePosixPath("scenarios/api.feature"),
        format=ScenarioFormat.GHERKIN,
        content=content,
        content_hash=content_hash(content.encode()),
    )
    [compiled] = compile_documents(
        [parse_document(document)],
        builtin_registry(),
        base=PurePosixPath("scenarios"),
        available_capabilities=builtin_adapters().available_capabilities,
    ).specifications
    return compiled


@pytest.fixture
def run(tmp_path: Path, shop_server: Any) -> Any:
    shop_server.state.reset()

    def _execute(body: str, *, api: str | None = None) -> ExecutionReport:
        compiled = _compile(body)
        assert compiled.status is CompilationStatus.READY, compiled.unresolved
        services: dict[str, Any] = {"api": api or f"{shop_server.url}/api"}
        environment = Environment(name="local", services=services, timeout_seconds=3)
        plan = create_plan(compiled.specification, environment, builtin_adapters())
        runner = LocalRunner(builtin_registry(), builtin_adapters(), evidence_root=tmp_path)
        return runner.run(ExecutionRequest("shop", compiled, plan, environment))

    return _execute


def _only(report: ExecutionReport) -> TestResult:
    [result] = report.results
    return result


def _failure(report: ExecutionReport) -> tuple[ExecutionStatus, FailureClassification, str]:
    result = _only(report)
    assert result.failure is not None, result
    return result.status, result.failure.classification, result.failure.message


# --- Successful requests (TASK-046, TASK-047) --------------------------------


def test_api_scenario_runs_in_be_mode_without_a_browser(run: Any) -> None:
    report = run(
        SIGN_IN
        + '    When the client sends POST "/orders" with:\n'
        + '      """\n      {"product": "plum", "quantity": 2}\n      """\n'
        + "    Then the response status is 201\n"
        + '    And the response field "total" is "1.6"\n'
        + '    And the response field "user" is "alice"\n'
        + '    And the response header "Content-Type" is "application/json"\n'
        + '    When the client sends GET "/orders"\n'
        + '    Then the response field "orders" has 1 items\n'
        + '    And the response field "orders[0].product" is "plum"\n'
        + '    And the response body contains "plum"\n'
    )
    assert report.execution.status is S.PASSED, _only(report)
    assert report.execution.mode.value == "be"


def test_methods_and_absolute_urls(run: Any, shop_server: Any) -> None:
    report = run(
        f'    When the client sends GET "{shop_server.url}/api/health"\n'
        "    Then the response status is 200\n"
        '    When the client sends DELETE "/health"\n'
        "    Then the response status is 501\n"
    )
    assert report.execution.status is S.PASSED, _only(report)


def test_explicit_header_and_bearer_token(run: Any) -> None:
    report = run(
        '    When the client sets header "Accept" to "application/json"\n'
        '    And the client uses bearer token "invalid-token-value"\n'
        '    And the client sends GET "/orders"\n'
        "    Then the response status is 401\n"
        '    And the response field "error" exists\n'
    )
    assert report.execution.status is S.PASSED, _only(report)


# --- Assertion failures with diagnostics -------------------------------------


@pytest.mark.parametrize(
    ("assertion", "message"),
    [
        ("Then the response status is 200", "expected status 200 (got 401 from GET "),
        (
            'Then the response field "error" is "nope"',
            'is "Missing or invalid token", expected "nope"',
        ),
        ('Then the response field "missing" exists', "response field 'missing' does not exist"),
        (
            'Then the response field "error" has 2 items',
            'is "Missing or invalid token", not a list',
        ),
        ('Then the response body contains "orders"', "response body does not contain 'orders'"),
        (
            'Then the response header "Content-Type" is "text/html"',
            "header 'Content-Type' is 'application/json'",
        ),
    ],
)
def test_failed_assertions(run: Any, assertion: str, message: str) -> None:
    status, classification, text = _failure(
        run(f'    When the client sends GET "/orders"\n    {assertion}\n')
    )
    assert (status, classification) == (S.FAILED, C.APPLICATION_BUG)
    assert message in text


def test_typed_comparison(run: Any) -> None:
    """'quantity' is the number 4, so the text "4" in quotes does not match."""
    status, _, text = _failure(
        run(
            SIGN_IN
            + '    When the client sends POST "/orders" with:\n'
            + '      """\n      {"product": "pear", "quantity": 4}\n      """\n'
            + '    Then the response field "quantity" is "\\"4\\""\n'
        )
    )
    assert status is S.FAILED
    assert 'is 4, expected "4"' in text


def test_non_json_response(run: Any, shop_server: Any) -> None:
    status, _, text = _failure(
        run(
            _steps(
                f'When the client sends GET "{shop_server.url}/login"',
                'Then the response field "x" exists',
            )
        )
    )
    assert status is S.FAILED
    assert text.startswith("response is not JSON (got 200 from GET ")


# --- Errors ------------------------------------------------------------------


def test_unreachable_api_is_an_environment_error(run: Any) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    status, classification, text = _failure(
        run(
            _steps('When the client sends GET "/health"', "Then the response status is 200"),
            api=f"http://127.0.0.1:{port}",
        )
    )
    assert (status, classification) == (S.ERROR, C.ENVIRONMENT_ERROR)
    assert text.startswith("cannot send GET /health: ")


def test_assertion_without_request_is_an_implementation_error(run: Any) -> None:
    report = run(
        '    When the client sets header "Accept" to "*/*"\n    Then the response status is 200\n'
    )
    status, classification, text = _failure(report)
    assert (status, classification) == (S.ERROR, C.TEST_IMPLEMENTATION_ERROR)
    assert text == "no request has been sent in this test case yet"


def test_missing_token_field_fails(run: Any) -> None:
    status, _, text = _failure(
        run(
            _steps(
                'When the client sends GET "/health"',
                'And the client uses the token from "token"',
                "Then the response status is 200",
            )
        )
    )
    assert status is S.FAILED
    assert text.startswith("response field 'token' is not a non-empty string")


@pytest.mark.parametrize(
    "step",
    [
        'When the client sends FETCH "/health"',
        'When the client sends get "/health"',
        'When the client sends GET "health"',
        'When the client sends GET "file:///etc/passwd"',
        'Then the response field "a..b" exists',
        "Then the response status is 999",
        'When the client sets header "Bad Header" to "x"',
    ],
)
def test_invalid_steps_are_rejected_at_compile_time(step: str) -> None:
    compiled = _compile(
        _steps('When the client sends GET "/health"', step, "Then the response status is 200")
    )
    assert compiled.status is CompilationStatus.BLOCKED
    assert "invalid value" in compiled.unresolved[0].reason


def test_invalid_json_body_is_rejected_at_compile_time() -> None:
    compiled = _compile(
        _steps(
            'When the client sends POST "/orders" with:',
            '  """',
            '  {"product": }',
            '  """',
            "Then the response status is 201",
        )
    )
    assert compiled.status is CompilationStatus.BLOCKED
    reason = compiled.unresolved[0].reason
    assert reason.startswith("api.send-json: invalid doc_string: request body is not valid JSON")


# --- Evidence and secrets (TASK-048) -----------------------------------------


def test_exchanges_are_recorded_with_secrets_masked(run: Any, tmp_path: Path) -> None:
    report = run(
        SIGN_IN
        + '    When the client sets header "X-Api-Key" to "key-123456"\n'
        + '    And the client sends GET "/orders"\n'
        + "    Then the response status is 200\n"
    )
    [ref] = _only(report).evidence
    assert (ref.kind, ref.description) == ("http-exchanges", "2 requests with responses")
    text = (tmp_path / report.execution.id / ref.path).read_text()
    exchanges = json.loads(text)["exchanges"]

    login, orders = exchanges
    assert login["request"]["method"] == "POST"
    assert login["request"]["url"].endswith("/api/login")
    assert login["response"]["status"] == 200
    assert orders["request"]["headers"]["authorization"] == "********"
    assert orders["request"]["headers"]["x-api-key"] == "********"
    assert isinstance(orders["duration_ms"], int)
    for secret in ("correct-password", "key-123456"):
        assert secret not in text
    token_free = json.loads(login["response"]["body"])
    assert token_free["token"] == "********"
    assert "correct-password" not in report.model_dump_json()


# --- Environment headers (TASK-055) ------------------------------------------


def _with_headers(
    shop_server: Any, tmp_path: Path, headers: dict[str, str], secrets: dict[str, str]
) -> ExecutionReport:
    compiled = _compile(
        _steps('When the client sends GET "/health"', "Then the response status is 200")
    )
    services: dict[str, Any] = {"api": f"{shop_server.url}/api"}
    environment = Environment(name="qa", services=services, headers=headers, timeout_seconds=3)
    plan = create_plan(compiled.specification, environment, builtin_adapters())
    runner = LocalRunner(
        builtin_registry(),
        builtin_adapters(),
        evidence_root=tmp_path,
        environment_variables=secrets,
    )
    return runner.run(ExecutionRequest("shop", compiled, plan, environment))


def test_environment_headers_are_sent_with_secrets_resolved(
    shop_server: Any, tmp_path: Path
) -> None:
    report = _with_headers(
        shop_server, tmp_path,
        {"X-Api-Key": "${SHOP_API_KEY}", "Accept-Language": "pl"},
        {"SHOP_API_KEY": "key-from-env-123"},
    )  # fmt: skip

    assert report.execution.status is S.PASSED, _only(report)
    [ref] = _only(report).evidence
    exchange = json.loads((tmp_path / report.execution.id / ref.path).read_text())["exchanges"][0]
    assert exchange["request"]["headers"]["x-api-key"] == "********"
    assert exchange["request"]["headers"]["accept-language"] == "pl"
    assert "key-from-env-123" not in (tmp_path / report.execution.id / ref.path).read_text()


def test_missing_secret_in_environment_headers(shop_server: Any, tmp_path: Path) -> None:
    report = _with_headers(shop_server, tmp_path, {"X-Api-Key": "${SHOP_API_KEY}"}, {})
    status, classification, message = _failure(report)
    assert (status, classification) == (S.ERROR, C.ENVIRONMENT_ERROR)
    assert message.startswith(
        "httpx could not start the test case: environment 'qa': secret SHOP_API_KEY"
    )
