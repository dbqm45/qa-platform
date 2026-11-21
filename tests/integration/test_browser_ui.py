"""UI interactions, assertions, locators and evidence on a real browser (TASK-041..044)."""

import json
from pathlib import Path
from typing import Any

import pytest

from qa_schemas.enums import CompilationStatus, ExecutionStatus, FailureClassification
from qa_schemas.results import ExecutionReport, TestResult
from tests.integration.test_browser_navigation import _compile, _run

S, C = ExecutionStatus, FailureClassification
OPEN = 'Given the user opens "/form.html"'


@pytest.fixture
def run(tmp_path: Path, web_server: str, browser_config: dict[str, Any]) -> Any:
    def _execute(*steps: str, **config: Any) -> ExecutionReport:
        compiled = _compile(OPEN, *steps)
        assert compiled.status is CompilationStatus.READY, compiled.unresolved
        return _run(tmp_path, compiled, browser_config | config, web_server, timeout=1)

    return _execute


def _only(report: ExecutionReport) -> TestResult:
    [result] = report.results
    return result


def _message(report: ExecutionReport) -> str:
    result = _only(report)
    assert result.failure is not None, result
    return result.failure.message


# --- Interactions and assertions (TASK-041, TASK-042) ------------------------


def test_login_form_flow(run: Any) -> None:
    report = run(
        'When the user fills "Email" with "alice@example.com"',
        'And the user fills "Password" with "s3cret"',
        'And the user selects "Poland" in "Country"',
        'And the user checks "Remember me"',
        'Then "Email" has value "alice@example.com"',
        'And "Country" has value "pl"',
        'When the user clicks "Log in"',
        'Then the URL contains "/welcome.html"',
        'And the URL contains "country=pl"',
        'And the page shows "Welcome"',
    )
    assert report.execution.status is S.PASSED, _only(report)


def test_submit_the_form_of_the_focused_field(run: Any) -> None:
    report = run(
        'When the user fills "Email" with "bob@example.com"',
        "And the user submits the form",
        'Then the URL contains "email=bob%40example.com"',
    )
    assert report.execution.status is S.PASSED, _only(report)


def test_uncheck(run: Any) -> None:
    report = run(
        'When the user checks "Remember me"',
        'And the user unchecks "Remember me"',
        'Then "Log in" is visible',
    )
    assert report.execution.status is S.PASSED, _only(report)


def test_url_is_matches_path_or_full_url(run: Any, web_server: str) -> None:
    report = run('Then the URL is "/form.html"', f'And the URL is "{web_server}/form.html"')
    assert report.execution.status is S.PASSED, _only(report)


def test_enabled_and_disabled(run: Any) -> None:
    assert run('Then "Delete" is disabled', 'And "Log in" is enabled').execution.status is S.PASSED
    report = run('Then "Delete" is enabled')
    assert _only(report).status is S.FAILED
    assert _message(report).startswith("'Delete' is not enabled")


def test_hidden_and_late_elements_wait_deterministically(run: Any) -> None:
    report = run(
        'Then "Secret" is hidden',
        'And "css:#toast" is hidden',  # removed after 300 ms
        'And "text:Loaded later" is visible',  # added after 300 ms
        'And the page shows "Loaded later"',
    )
    assert report.execution.status is S.PASSED, _only(report)


# --- Assertion failures have diagnostics -------------------------------------


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ('Then "Email" has value "x"', "'Email' has value '', expected 'x'"),
        ('Then the page shows "Goodbye"', "the page does not show 'Goodbye'"),
        ('Then the URL is "/other.html"', "expected '/other.html'"),
        ('Then the URL contains "admin"', "does not contain 'admin'"),
        ('Then "Hello" is hidden', "'Hello' is still visible"),
    ],
)
def test_failed_assertions_explain_what_was_found(run: Any, step: str, message: str) -> None:
    report = run(step)
    assert _only(report).status is S.FAILED
    assert _only(report).failure.classification is C.APPLICATION_BUG  # type: ignore[union-attr]
    assert message in _message(report)


def test_password_values_are_masked(run: Any) -> None:
    report = run(
        'When the user fills "Password" with "s3cret"', 'Then "Password" has value "other"'
    )
    assert "s3cret" not in _message(report)
    assert "other" not in _message(report)
    assert "********" in _message(report)


def test_interaction_with_disabled_element_fails(run: Any) -> None:
    report = run('When the user clicks "Delete"', 'Then "Log in" is visible')
    assert _only(report).status is S.FAILED
    assert _message(report).startswith("cannot click 'Delete': ")


# --- Locator strategy (TASK-043) ---------------------------------------------


def test_explicit_strategies(run: Any) -> None:
    report = run(
        'Then "testid:login-button" is visible',
        'And "role:button=Log in" is visible',
        'And "label:Email" is visible',
        'And "text:Hello" is visible',
        'And "css:#hello" is visible',
        'And "role:heading=Hello" is visible',
    )
    assert report.execution.status is S.PASSED, _only(report)


def test_testid_is_preferred_over_text(run: Any) -> None:
    """'Profile' is both a data-testid (span) and a link; testid comes first."""
    report = run('When the user clicks "Profile"', 'Then the URL is "/form.html"')
    assert report.execution.status is S.PASSED, _only(report)


def test_ambiguous_locator_is_reported(run: Any) -> None:
    report = run('When the user clicks "Save"', 'Then "Log in" is visible')
    assert _only(report).status is S.FAILED
    message = _message(report)
    assert message.startswith("'Save' is ambiguous: 2 visible elements match by role")
    assert '<button> "Save"' in message


def test_missing_element_lists_the_strategies_tried(run: Any) -> None:
    report = run('When the user clicks "Nope"', 'Then "Log in" is visible')
    assert _message(report).startswith(
        "no visible element matches 'Nope' (tried: testid, role, label, text; page: "
    )


def test_strategy_order_is_configurable(run: Any) -> None:
    report = run('Then "login-button" is visible', locator_strategies=["text", "role"])
    assert "tried: text, role" in _message(report)
    assert run('Then "login-button" is visible').execution.status is S.PASSED


def test_hidden_elements_never_match(run: Any) -> None:
    report = run('When the user clicks "Secret"', 'Then "Log in" is visible')
    assert "no visible element matches 'Secret'" in _message(report)


@pytest.mark.parametrize("locator", ["css:", "role:=Save", "role:button="])
def test_malformed_locators_are_rejected_at_compile_time(locator: str) -> None:
    compiled = _compile(OPEN, f'When the user clicks "{locator}"')
    assert compiled.status is CompilationStatus.BLOCKED
    assert "invalid value" in compiled.unresolved[0].reason


# --- Evidence (TASK-044) -----------------------------------------------------


def _evidence(tmp_path: Path, report: ExecutionReport) -> dict[str, Path]:
    base = tmp_path / report.execution.id
    return {ref.kind: base / ref.path for ref in _only(report).evidence}


def test_failure_evidence(run: Any, tmp_path: Path) -> None:
    report = run('Then the page shows "Goodbye"')

    files = _evidence(tmp_path, report)
    assert set(files) == {"page-info", "screenshot"}
    assert files["screenshot"].read_bytes().startswith(b"\x89PNG")
    info = json.loads(files["page-info"].read_text())
    assert info["url"].endswith("/form.html")
    assert info["title"] == "Login"
    assert "analytics failed to load" in info["console_errors"]
    assert files["screenshot"].parent.name == "nav.visit"  # per test case


def test_passing_case_has_no_screenshot_by_default(run: Any, tmp_path: Path) -> None:
    report = run('Then "Log in" is visible')
    assert set(_evidence(tmp_path, report)) == {"page-info"}


def test_screenshots_and_traces_on_request(run: Any, tmp_path: Path) -> None:
    report = run('Then "Log in" is visible', screenshot="always", trace="always")
    files = _evidence(tmp_path, report)
    assert set(files) == {"page-info", "screenshot", "trace"}
    assert files["trace"].stat().st_size > 0


def test_evidence_does_not_change_the_outcome(run: Any) -> None:
    passed = run('Then "Log in" is visible', screenshot="always")
    failed = run('Then the page shows "Goodbye"', screenshot="off")
    assert _only(passed).status is S.PASSED
    assert _only(failed).status is S.FAILED
