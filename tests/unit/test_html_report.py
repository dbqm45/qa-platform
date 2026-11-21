"""HTML report (TASK-059)."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from qa_reporting.html import REPORT_FILENAME, render_html, write_html_report
from qa_schemas.enums import ExecutionMode, ExecutionStatus, FailureClassification, TestCategory
from qa_schemas.evidence import EvidenceReference
from qa_schemas.execution import TestExecution
from qa_schemas.results import ExecutionReport, Failure, StepResult, TestResult
from qa_schemas.specification import TestSpecification

ROOT = Path(__file__).parents[2]
T0 = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
S = ExecutionStatus


def _step(index: int, text: str, status: S = S.PASSED) -> StepResult:
    return StepResult(index=index, keyword="When", text=text, line=5 + index, action="ui.click",
                      status=status, duration_ms=120)  # fmt: skip


def _report(**changes: object) -> ExecutionReport:
    passed = TestResult(
        test_case_id="login.ok", name="Successful login", status=S.PASSED,
        duration_ms=1500, steps=(_step(0, 'the user clicks "Log in"'),), steps_total=1,
        evidence=(EvidenceReference(kind="page-info", path=PurePosixPath("login.ok/page.json")),),
    )  # fmt: skip
    failed = TestResult(
        test_case_id="login.bad", name="Wrong <password>", status=S.FAILED, duration_ms=3200,
        steps=(_step(0, "a"), _step(1, "b", S.FAILED)), steps_total=4,
        failure=Failure(classification=FailureClassification.APPLICATION_BUG,
                        message="the page does not show 'Welcome' <script>", step_index=1,
                        error_type="StepFailure"),
        evidence=(EvidenceReference(kind="screenshot", description="page at the end",
                                    path=PurePosixPath("login.bad/screenshot.png")),),
        notes=("playwright: evidence collection failed: x",),
    )  # fmt: skip
    data = {
        "execution": TestExecution(
            id="20261121-090000-abcdef",
            project_id="shop",
            specification_id="login.ok",
            plan_id="login.ok.fe.local",
            mode=ExecutionMode.FE,
            category=TestCategory.FUNCTIONAL,
            environment="local",
            status=S.FAILED,
            created_at=T0,
            started_at=T0,
            finished_at=T0 + timedelta(seconds=4.7),
        ),
        "results": (passed, failed),
    } | changes
    return ExecutionReport.model_validate(data)


def _spec() -> TestSpecification:
    return TestSpecification.model_validate_json(
        (ROOT / "tests/fixtures/login/login.spec.json").read_text()
    )


def test_summary() -> None:
    page = render_html(_report(), _spec())

    assert "<title>login.successful-login — failed</title>" in page
    assert "20261121-090000-abcdef" in page
    assert "Login — Successful login" in page and "scenarios/login.feature:7" in page
    assert "fe / functional" in page
    assert "4.7 s" in page
    assert re.search(r"status passed'>passed</span> 1</span>.*status failed'>failed</span> 1", page)


def test_cases_steps_and_failures() -> None:
    page = render_html(_report())

    assert "<h2>Successful login</h2>" in page
    assert "the user clicks &quot;Log in&quot;" in page
    assert "line 6" in page and "120 ms" in page
    assert "2 steps not run" in page
    assert "application_bug in step 2" in page
    assert "(StepFailure)" in page
    assert "Note: playwright: evidence collection failed: x" in page


def test_evidence_links_are_relative() -> None:
    page = render_html(_report())
    assert "<img class=shot src='login.bad/screenshot.png'" in page
    assert "<a href='login.ok/page.json'>page-info</a>" in page


def test_everything_is_escaped() -> None:
    page = render_html(_report())
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "Wrong &lt;password&gt;" in page


def test_self_contained() -> None:
    page = render_html(_report())
    assert "<script" not in page
    assert not re.search(r"(src|href)=['\"]?(https?:)?//", page)
    assert "<style>" in page


def test_execution_failure_and_cleanup_errors() -> None:
    failure = Failure(classification=FailureClassification.ENVIRONMENT_ERROR,
                      message="playwright could not be prepared")  # fmt: skip
    page = render_html(_report(failure=failure, cleanup_errors=("playwright: boom",)))
    assert "The execution could not run" in page
    assert "playwright could not be prepared" in page
    assert "Cleanup problems" in page and "playwright: boom" in page


def test_without_specification() -> None:
    page = render_html(_report())
    assert "<title>login.ok — failed</title>" in page
    assert "Scenario</dt>" not in page


def test_write_next_to_the_evidence(tmp_path: Path) -> None:
    path = write_html_report(_report(), tmp_path)
    assert path == tmp_path / REPORT_FILENAME
    assert path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_report_can_be_regenerated_from_results_json(tmp_path: Path) -> None:
    report = _report()
    restored = ExecutionReport.model_validate_json(report.model_dump_json())
    assert render_html(restored, _spec()) == render_html(report, _spec())
