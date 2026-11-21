"""Compilation statuses (TASK-026)."""

from pathlib import PurePosixPath
from typing import Any

import pytest

from qa_core.scenarios.compilation import CompilationReport, compile_documents
from qa_core.scenarios.parsing import parse_document
from qa_core.steps.registry import StepRegistry
from qa_schemas.compilation import CompiledSpecification
from qa_schemas.enums import CompilationStatus, ScenarioFormat, StepKind
from qa_schemas.scenario import ParseResult, ScenarioDocument, content_hash

READY, REVIEW, BLOCKED, UNSUPPORTED = (
    CompilationStatus.READY,
    CompilationStatus.NEEDS_REVIEW,
    CompilationStatus.BLOCKED,
    CompilationStatus.UNSUPPORTED,
)


def _registry() -> StepRegistry:
    registry = StepRegistry()
    a, e = StepKind.ACTION, StepKind.EXPECTATION
    registry.register("nav.open", "the {word} page is open", _one, kind=a, capability="browser")
    registry.register("ui.click", "the user clicks {string}", _one, kind=a, capability="browser")
    registry.register("ui.shown", "{string} is shown", _one, kind=e, capability="browser")
    registry.register("api.status", "the status is {int}", _one, kind=e, capability="http")
    return registry


def _one(context: Any, value: Any) -> None: ...


def _parsed(content: str, path: str = "scenarios/shop.feature") -> ParseResult:
    return parse_document(
        ScenarioDocument(
            path=PurePosixPath(path),
            format=ScenarioFormat.GHERKIN,
            content=content,
            content_hash=content_hash(content.encode()),
        )
    )


def _compile(content: str, **kwargs: Any) -> CompilationReport:
    return compile_documents(
        [_parsed(content)], _registry(), base=PurePosixPath("scenarios"), **kwargs
    )


def _only(content: str, **kwargs: Any) -> CompiledSpecification:
    [compiled] = _compile(content, **kwargs).specifications
    return compiled


READY_SCENARIO = (
    "Feature: Shop\n"
    "  Scenario: Buy\n"
    "    Given the shop page is open\n"
    '    When the user clicks "Buy"\n'
    '    Then "Thank you" is shown\n'
)


# --- Statuses ----------------------------------------------------------------


def test_fully_resolved_scenario_is_ready() -> None:
    compiled = _only(READY_SCENARIO)
    assert compiled.status is READY
    assert compiled.reasons == ()
    assert compiled.unresolved == ()
    assert compiled.status.is_executable
    assert compiled.specification.required_capabilities == ("browser",)


def test_unresolved_step_blocks() -> None:
    compiled = _only(READY_SCENARIO.replace('"Buy"', '"Buy" twice'))

    assert compiled.status is BLOCKED
    assert compiled.reasons == ("1 step(s) cannot be resolved",)
    [step] = compiled.unresolved
    assert (step.line, step.kind) == (4, StepKind.ACTION)
    assert not compiled.status.is_executable


def test_unknown_expectation_cannot_become_executable() -> None:
    """An unresolved Then must block, never be skipped or treated as passed."""
    compiled = _only(READY_SCENARIO.replace('"Thank you" is shown', "the customer is happy"))
    assert compiled.status is BLOCKED
    assert compiled.unresolved[0].kind is StepKind.EXPECTATION


def test_action_written_as_expectation_blocks() -> None:
    compiled = _only(
        READY_SCENARIO.replace('Then "Thank you" is shown', 'Then the user clicks "X"')
    )
    assert compiled.status is BLOCKED
    assert "cannot be used as a expectation step" in compiled.unresolved[0].reason


def test_scenario_without_expectation_needs_review() -> None:
    compiled = _only(
        "Feature: Shop\n  Scenario: Click only\n    Given the shop page is open\n"
        '    When the user clicks "Buy"\n'
    )
    assert compiled.status is REVIEW
    assert compiled.reasons == ("test case(s) without any expectation step: shop.click-only",)
    assert not compiled.status.is_executable


def test_missing_capability_is_unsupported_when_adapters_are_known() -> None:
    content = READY_SCENARIO + "    And the status is 200\n"

    assert _only(content).status is READY  # capability check skipped
    compiled = _only(content, available_capabilities={"browser"})
    assert compiled.status is UNSUPPORTED
    assert compiled.reasons == ("no adapter provides the required capabilities: http",)
    assert _only(content, available_capabilities={"browser", "http"}).status is READY


def test_blocked_takes_precedence_over_other_statuses() -> None:
    content = "Feature: Shop\n  Scenario: S\n    When something unknown happens\n"
    assert _only(content, available_capabilities=set()).status is BLOCKED


@pytest.mark.parametrize("status", list(CompilationStatus))
def test_only_ready_is_executable(status: CompilationStatus) -> None:
    assert status.is_executable is (status is READY)


# --- Documents ---------------------------------------------------------------


def test_validation_errors_block_the_whole_document() -> None:
    report = _compile(READY_SCENARIO + "  Scenario:\n    Given the shop page is open\n")

    [document] = report.documents
    assert document.blocked
    assert document.specifications == ()
    assert [i.code for i in document.issues] == ["scenario.missing-name"]
    assert not report.ok


def test_syntax_errors_block_the_document() -> None:
    [document] = _compile(
        "Feature: F\n  oops\n  Scenario: S\n    Given x\n   | a\n  ???\n"
    ).documents
    assert document.blocked
    assert document.issues[0].code == "syntax"


def test_warnings_do_not_block() -> None:
    content = (
        "Feature: Shop\n  Scenario Outline: Open <page>\n"
        "    Given the <page> page is open\n"
        '    Then "<page>" is shown\n'
        "    Examples:\n      | page | spare |\n      | home | x     |\n"
    )
    report = _compile(content)

    [document] = report.documents
    assert not document.blocked
    assert [i.code for i in document.issues] == ["examples.unused-column"]
    assert report.specifications[0].status is READY


def test_report_counts_and_ok() -> None:
    blocked = READY_SCENARIO.replace("Buy\n", "Other\n", 1).replace('"Buy"', '"Buy" now')
    report = compile_documents(
        [_parsed(READY_SCENARIO, "scenarios/a.feature"), _parsed(blocked, "scenarios/b.feature")],
        _registry(),
        base=PurePosixPath("scenarios"),
    )
    assert report.count(READY) == 1
    assert report.count(BLOCKED) == 1
    assert not report.ok

    assert _compile(READY_SCENARIO).ok


def test_needs_review_alone_is_ok() -> None:
    report = _compile("Feature: S\n  Scenario: S\n    Given the shop page is open\n")
    assert report.count(REVIEW) == 1
    assert report.ok
