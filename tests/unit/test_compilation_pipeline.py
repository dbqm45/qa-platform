"""Compilation through the whole pipeline: parse -> validate -> convert -> resolve (TASK-028).

Where each TASK-028 requirement is covered:

| Requirement                    | Tests                                                          |
|--------------------------------|----------------------------------------------------------------|
| valid scenarios                | this file; test_compilation.py::test_fully_resolved_...        |
| invalid scenarios              | this file; test_compilation.py::test_validation_errors_...,    |
|                                | test_syntax_errors_...; test_scenario_validation.py            |
| unknown steps                  | this file; test_compilation.py::test_unresolved_step_blocks,   |
|                                | test_step_registry.py::test_unknown_step_...                   |
| missing expected results       | this file; test_compilation.py::test_scenario_without_...,     |
|                                | test_unknown_expectation_cannot_become_executable              |
| Scenario Outlines              | this file; test_conversion.py::test_outline_...                |
| multiple scenarios in a file   | this file                                                      |
| repeated compilation is stable | this file (models, JSON);                                      |
|                                | test_cli_scenario_compile.py::test_recompiling_... (files)     |
"""

from pathlib import PurePosixPath
from typing import Any

from qa_core.scenarios.compilation import CompilationReport, compile_documents
from qa_core.scenarios.parsing import parse_document
from qa_core.steps.registry import StepRegistry
from qa_schemas.enums import CompilationStatus, ScenarioFormat, StepKind
from qa_schemas.scenario import ScenarioDocument, content_hash

FEATURE = """\
@checkout
Feature: Checkout
  Background:
    Given the "shop" page is open

  Scenario: Pay by card
    When the user clicks "Pay"
    Then "Paid" is shown

  Scenario: Browse only
    When the user clicks "Products"

  Scenario: Pay by crypto
    When the user pays with crypto
    Then "Paid" is shown

  Rule: Vouchers
    Scenario Outline: Apply <code>
      When the user clicks "<code>"
      Then "<message>" is shown
      And the status is <status>

      Examples:
        | code   | message | status |
        | SAVE10 | Saved   | 200    |
        | WRONG  | Invalid | 400    |
"""


def _one(context: Any, value: Any) -> None: ...


def _registry() -> StepRegistry:
    registry = StepRegistry()
    a, e = StepKind.ACTION, StepKind.EXPECTATION
    registry.register("nav.open", "the {string} page is open", _one, kind=a, capability="browser")
    registry.register("ui.click", "the user clicks {string}", _one, kind=a, capability="browser")
    registry.register("ui.shown", "{string} is shown", _one, kind=e, capability="browser")
    registry.register("api.status", "the status is {int}", _one, kind=e, capability="http")
    return registry


def _compile(content: str = FEATURE) -> CompilationReport:
    document = ScenarioDocument(
        path=PurePosixPath("scenarios/checkout.feature"),
        format=ScenarioFormat.GHERKIN,
        content=content,
        content_hash=content_hash(content.encode()),
    )
    return compile_documents(
        [parse_document(document)], _registry(), base=PurePosixPath("scenarios")
    )


def test_multiple_scenarios_get_individual_statuses() -> None:
    report = _compile()

    statuses = {c.specification.id: c.status for c in report.specifications}
    assert statuses == {
        "checkout.pay-by-card": CompilationStatus.READY,
        "checkout.browse-only": CompilationStatus.NEEDS_REVIEW,
        "checkout.pay-by-crypto": CompilationStatus.BLOCKED,
        "checkout.apply-code": CompilationStatus.READY,
    }
    assert [c.specification.id for c in report.specifications] == list(statuses)  # source order


def test_one_blocked_scenario_does_not_affect_the_others() -> None:
    report = _compile()
    blocked = next(c for c in report.specifications if c.status is CompilationStatus.BLOCKED)

    [step] = blocked.unresolved
    assert (step.line, step.text) == (14, "the user pays with crypto")
    assert report.count(CompilationStatus.READY) == 2
    assert not report.ok


def test_outline_cases_are_resolved_with_substituted_values() -> None:
    outline = next(
        c for c in _compile().specifications if c.specification.id == "checkout.apply-code"
    )
    first, second = outline.specification.test_cases

    assert (first.id, first.name, second.id) == (
        "checkout.apply-code:1",
        "Apply SAVE10",
        "checkout.apply-code:2",
    )
    assert [(s.action, s.parameters) for s in second.steps] == [
        ("nav.open", {"value": "shop"}),
        ("ui.click", {"value": "WRONG"}),
        ("ui.shown", {"value": "Invalid"}),
        ("api.status", {"value": 400}),
    ]
    assert outline.specification.required_capabilities == ("browser", "http")
    assert outline.specification.metadata.tags == ("checkout",)


def test_background_is_part_of_every_specification() -> None:
    for compiled in _compile().specifications:
        for case in compiled.specification.test_cases:
            assert case.steps[0].text == 'the "shop" page is open'


def test_invalid_file_yields_no_specifications() -> None:
    report = _compile(FEATURE.replace("Scenario: Browse only", "Scenario:"))

    [document] = report.documents
    assert document.blocked
    assert report.specifications == ()
    assert [i.code for i in document.issues] == ["scenario.missing-name"]


def test_repeated_compilation_gives_equal_models_and_json() -> None:
    first, second = _compile(), _compile()  # independent parse and registry instances

    assert first == second
    assert [c.model_dump_json() for c in first.specifications] == [
        c.model_dump_json() for c in second.specifications
    ]


def test_editing_one_scenario_changes_only_its_specification() -> None:
    before = {c.specification.id: c for c in _compile().specifications}
    after = {
        c.specification.id: c
        for c in _compile(FEATURE.replace('clicks "Pay"', 'clicks "Pay now"')).specifications
    }

    changed = {spec_id for spec_id in before if before[spec_id] != after[spec_id]}
    assert changed == {"checkout.pay-by-card"}
    assert (
        before["checkout.pay-by-card"].specification.source.content_hash
        != after["checkout.pay-by-card"].specification.source.content_hash
    )
