"""Playwright adapter and navigation steps against a real browser (TASK-039, TASK-040)."""

import socket
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from qa_core.scenarios.compilation import compile_documents
from qa_core.scenarios.parsing import parse_document
from qa_core.steps.registry import StepRegistry
from qa_execution.builtin import builtin_adapters, builtin_registry
from qa_execution.errors import StepFailure
from qa_execution.runner import ExecutionRequest, LocalRunner, StepContext
from qa_schemas.compilation import CompiledSpecification
from qa_schemas.enums import (
    CompilationStatus,
    ExecutionMode,
    ExecutionStatus,
    FailureClassification,
    ScenarioFormat,
    StepKind,
    TestCategory,
)
from qa_schemas.plan import ExecutionPlan, ExecutionSettings
from qa_schemas.project import Environment
from qa_schemas.results import ExecutionReport
from qa_schemas.scenario import ScenarioDocument, content_hash

S, C = ExecutionStatus, FailureClassification


def _title_is(context: StepContext, title: str) -> None:
    actual = context.resource("browser").title()
    if actual != title:
        raise StepFailure(f"title is {actual!r}, expected {title!r}")


def _remember(context: StepContext) -> None:
    context.resource("browser").evaluate("document.cookie = 'seen=1; path=/'")


def _not_remembered(context: StepContext) -> None:
    if "seen=1" in context.resource("browser").evaluate("document.cookie"):
        raise StepFailure("cookie from another test case is visible")


def _registry() -> StepRegistry:
    """Built-in steps plus test-only checks (UI assertions arrive in TASK-042)."""
    registry = builtin_registry()
    e, a = StepKind.EXPECTATION, StepKind.ACTION
    registry.register("t.title", "the title is {string}", _title_is, kind=e, capability="browser")
    registry.register(
        "t.remember", "the browser remembers me", _remember, kind=a, capability="browser"
    )
    registry.register(
        "t.forgotten",
        "the browser does not remember me",
        _not_remembered,
        kind=e,
        capability="browser",
    )
    return registry


def _compile(*steps: str, rows: int = 0) -> CompiledSpecification:
    body = "\n".join(f"    {s}" for s in steps)
    if rows:
        examples = "\n".join(f"      | {i} |" for i in range(rows))
        content = (
            f"Feature: Nav\n  Scenario Outline: Visit <n>\n{body}\n"
            f"    Examples:\n      | n |\n{examples}\n"
        )
    else:
        content = f"Feature: Nav\n  Scenario: Visit\n{body}\n"
    document = ScenarioDocument(
        path=PurePosixPath("scenarios/nav.feature"),
        format=ScenarioFormat.GHERKIN,
        content=content,
        content_hash=content_hash(content.encode()),
    )
    [compiled] = compile_documents(
        [parse_document(document)],
        _registry(),
        base=PurePosixPath("scenarios"),
        available_capabilities=builtin_adapters().available_capabilities,
    ).specifications
    return compiled


def _run(
    tmp_path: Path,
    compiled: CompiledSpecification,
    config: dict[str, Any],
    base_url: str | None,
) -> ExecutionReport:
    assert compiled.status is CompilationStatus.READY, compiled.unresolved
    runner = LocalRunner(
        _registry(),
        builtin_adapters(),
        evidence_root=tmp_path,
        adapter_config={"playwright": config},
    )
    plan = ExecutionPlan(
        id="nav.local",
        specification_id=compiled.specification.id,
        mode=ExecutionMode.FE,
        category=TestCategory.FUNCTIONAL,
        environment="local",
        adapters=("playwright",),
        settings=ExecutionSettings(step_timeout_seconds=5),
    )
    environment = Environment(name="local", base_url=base_url)  # type: ignore[arg-type]
    return runner.run(ExecutionRequest("shop", compiled, plan, environment))


def _failure(report: ExecutionReport) -> tuple[ExecutionStatus, FailureClassification | None, str]:
    [result] = report.results
    failure = result.failure
    return (
        result.status,
        failure.classification if failure else None,
        failure.message if failure else "",
    )


# --- Successful navigation ---------------------------------------------------


def test_open_relative_url(tmp_path: Path, web_server: str, browser_config: dict[str, Any]) -> None:
    compiled = _compile('Given the user opens "/index.html"', 'Then the title is "Home"')
    report = _run(tmp_path, compiled, browser_config, web_server)
    assert report.execution.status is S.PASSED, report.results


def test_navigate_reload_and_back(
    tmp_path: Path, web_server: str, browser_config: dict[str, Any]
) -> None:
    compiled = _compile(
        'Given the user opens "/index.html"',
        f'When the user navigates to "{web_server}/second.html"',
        'Then the title is "Second"',
        "When the user reloads the page",
        'Then the title is "Second"',
        "When the user goes back",
        'Then the title is "Home"',
    )
    report = _run(tmp_path, compiled, browser_config, web_server)
    assert report.execution.status is S.PASSED, report.results
    assert len(report.results[0].steps) == 7


def test_test_cases_do_not_share_browser_state(
    tmp_path: Path, web_server: str, browser_config: dict[str, Any]
) -> None:
    compiled = _compile(
        'Given the user opens "/index.html"',
        "Then the browser does not remember me",
        "When the browser remembers me",
        rows=2,
    )
    report = _run(tmp_path, compiled, browser_config, web_server)
    assert [r.status for r in report.results] == [S.PASSED, S.PASSED]


# --- Navigation failures -----------------------------------------------------


def test_http_error_is_an_application_failure(
    tmp_path: Path, web_server: str, browser_config: dict[str, Any]
) -> None:
    compiled = _compile('Given the user opens "/missing.html"', 'Then the title is "Home"')
    status, classification, message = _failure(_run(tmp_path, compiled, browser_config, web_server))
    assert (status, classification) == (S.FAILED, C.APPLICATION_BUG)
    assert "/missing.html responded with HTTP 404" in message
    assert "current page: " in message


def test_unreachable_server_is_an_environment_error(
    tmp_path: Path, browser_config: dict[str, Any]
) -> None:
    with socket.socket() as sock:  # a port nothing listens on
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    compiled = _compile('Given the user opens "/index.html"', 'Then the title is "Home"')

    status, classification, message = _failure(
        _run(tmp_path, compiled, browser_config, f"http://127.0.0.1:{port}")
    )

    assert (status, classification) == (S.ERROR, C.ENVIRONMENT_ERROR)
    assert message.startswith("cannot open /index.html: ")
    assert "ERR_CONNECTION_REFUSED" in message


def test_relative_url_needs_base_url(tmp_path: Path, browser_config: dict[str, Any]) -> None:
    compiled = _compile('Given the user opens "/index.html"', 'Then the title is "Home"')
    status, classification, message = _failure(_run(tmp_path, compiled, browser_config, None))
    assert (status, classification) == (S.ERROR, C.ENVIRONMENT_ERROR)
    assert message == "cannot open relative URL '/index.html': environment 'local' has no base_url"


def test_going_back_without_history_fails(
    tmp_path: Path, web_server: str, browser_config: dict[str, Any]
) -> None:
    compiled = _compile(
        'Given the user opens "/index.html"', "When the user goes back", 'Then the title is "Home"'
    )
    status, classification, message = _failure(_run(tmp_path, compiled, browser_config, web_server))
    assert (status, classification) == (S.FAILED, C.APPLICATION_BUG)
    assert message.startswith("there is no previous page to go back to")


# --- Adapter problems --------------------------------------------------------


def test_browser_that_cannot_start_is_an_environment_error(tmp_path: Path, web_server: str) -> None:
    compiled = _compile('Given the user opens "/index.html"', 'Then the title is "Home"')
    report = _run(tmp_path, compiled, {"executable_path": "/nonexistent/chrome"}, web_server)

    assert report.execution.status is S.ERROR
    assert report.failure is not None
    assert report.failure.classification is C.ENVIRONMENT_ERROR
    assert "playwright could not be prepared: cannot launch chromium" in report.failure.message
    assert "playwright install chromium" in report.failure.message
    assert report.cleanup_errors == ()


def test_invalid_browser_configuration(tmp_path: Path, web_server: str) -> None:
    compiled = _compile('Given the user opens "/index.html"', 'Then the title is "Home"')
    report = _run(tmp_path, compiled, {"browser": "netscape", "headles": True}, web_server)

    assert report.failure is not None
    assert "invalid adapters.playwright configuration" in report.failure.message
    assert "browser:" in report.failure.message
    assert "headles:" in report.failure.message


# --- Compile-time checks (no browser needed) ---------------------------------


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "javascript:alert(1)", "index.html", "https://user:pw@example.com/"],
)
def test_unsafe_or_ambiguous_urls_are_rejected_at_compile_time(url: str) -> None:
    compiled = _compile(f'Given the user opens "{url}"', 'Then the title is "Home"')
    assert compiled.status is CompilationStatus.BLOCKED
    assert "invalid value" in compiled.unresolved[0].reason
