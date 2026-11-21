"""Scenario validation rules (TASK-020)."""

from pathlib import Path, PurePosixPath

import pytest

from qa_core.scenarios.parsing import parse_document
from qa_core.scenarios.validation import ValidationReport, validate, validate_result
from qa_schemas.enums import IssueSeverity, ScenarioFormat
from qa_schemas.scenario import ParseResult, ScenarioDocument, ValidationIssue, content_hash

ROOT = Path(__file__).parents[2]
PATH = "features/x.feature"


def _parsed(content: str) -> ParseResult:
    return parse_document(
        ScenarioDocument(
            path=PurePosixPath(PATH),
            format=ScenarioFormat.GHERKIN,
            content=content,
            content_hash=content_hash(content.encode()),
        )
    )


def _issues(content: str) -> list[ValidationIssue]:
    return validate_result(_parsed(content))


def _codes(content: str) -> list[tuple[str, int | None]]:
    return [(i.code, i.line) for i in _issues(content)]


VALID = """\
Feature: Login
  Background:
    Given the login page is open

  Scenario: Successful login
    When the user signs in
    Then the dashboard is shown
    And a greeting is shown

  Scenario Outline: Login as <role>
    When the user signs in as "<user>"
    Then the page shows:
      \"\"\"
      Welcome <user>
      \"\"\"
    And the menu contains:
      | item   |
      | <item> |

    Examples:
      | role  | user  | item     |
      | admin | alice | Settings |
"""


# --- Valid input -------------------------------------------------------------


def test_valid_feature_has_no_issues() -> None:
    assert _issues(VALID) == []


def test_example_project_scenarios_are_valid() -> None:
    path = ROOT / "examples/scenarios/login.feature"
    assert _issues(path.read_text()) == []


def test_conjunction_after_background_is_fine() -> None:
    content = "Feature: F\n  Background:\n    Given a\n  Scenario: S\n    And b\n    Then c\n"
    assert _issues(content) == []


# --- Document and feature ----------------------------------------------------


def test_syntax_errors_become_validation_errors() -> None:
    [issue] = _issues("Feature: F\n  Scenario: S\n    Given a\n  oops\n")
    assert (issue.code, issue.severity, issue.line, issue.column) == (
        "syntax", IssueSeverity.ERROR, 4, 3,
    )  # fmt: skip
    assert issue.location() == f"{PATH}:4:3"


def test_file_without_feature() -> None:
    [issue] = _issues("# nothing here\n")
    assert (issue.code, issue.line, issue.location()) == ("document.no-feature", None, PATH)


def test_feature_without_name_and_scenarios() -> None:
    issues = _issues("Feature:\n")
    assert [(i.code, i.severity) for i in issues] == [
        ("feature.missing-name", IssueSeverity.ERROR),
        ("feature.no-scenarios", IssueSeverity.WARNING),
    ]


# --- Scenarios and steps -----------------------------------------------------


def test_scenario_without_name() -> None:
    assert _codes("Feature: F\n  Scenario:\n    Given a\n") == [("scenario.missing-name", 2)]


def test_duplicate_scenario_names() -> None:
    content = "Feature: F\n  Scenario: Same\n    Given a\n  Scenario: Same \n    Given b\n"
    assert _codes(content) == [("scenario.duplicate-name", 2), ("scenario.duplicate-name", 4)]


def test_scenarios_in_different_rules_still_need_unique_names() -> None:
    content = (
        "Feature: F\n"
        "  Rule: A\n    Scenario: Same\n      Given a\n"
        "  Rule: B\n    Scenario: Same\n      Given b\n"
    )
    assert [c for c, _ in _codes(content)] == ["scenario.duplicate-name"] * 2


def test_scenario_without_steps() -> None:
    content = "Feature: F\n  Background:\n    Given a\n  Scenario: Empty\n"
    assert _codes(content) == [("scenario.no-steps", 4)]


def test_step_without_text() -> None:
    content = "Feature: F\n  Scenario: S\n    Given a\n    Then \n"
    assert _codes(content) == [("step.empty", 4)]


@pytest.mark.parametrize(
    "content",
    [
        "Feature: F\n  Scenario: S\n    Given\n    When a\n    Then b\n",
        "# language: pl\nWłaściwość: F\n  Scenariusz: S\n    Zakładając\n    Gdy a\n",
    ],
)
def test_bare_keyword_is_not_silently_ignored(content: str) -> None:
    [issue] = _issues(content)
    assert issue.code == "step.empty"
    assert "silently ignored" in issue.message


def test_description_text_is_not_mistaken_for_a_step() -> None:
    content = "Feature: F\n  Scenario: S\n    Given the user\n    Then ok\n"
    assert _issues(content) == []
    described = "Feature: F\n  Scenario: S\n    Users who are Given access\n    Given a\n"
    assert _issues(described) == []


@pytest.mark.parametrize("keyword", ["And", "But", "*"])
def test_first_step_must_have_a_clear_kind(keyword: str) -> None:
    [issue] = _issues(f"Feature: F\n  Scenario: S\n    {keyword} a\n    Then b\n")
    assert (issue.code, issue.line) == ("step.ambiguous-kind", 3)
    assert repr(keyword) in issue.message


def test_background_issue_is_reported_once() -> None:
    content = (
        "Feature: F\n  Background:\n    And a\n"
        "  Scenario: One\n    Then b\n  Scenario: Two\n    Then c\n"
    )
    assert _codes(content) == [("step.ambiguous-kind", 3)]


def test_star_after_another_step_is_fine() -> None:
    assert _issues("Feature: F\n  Scenario: S\n    Given a\n    * b\n") == []


# --- Scenario Outline and Examples -------------------------------------------


def test_outline_without_examples() -> None:
    assert _codes("Feature: F\n  Scenario Outline: O\n    Given <x>\n") == [
        ("outline.no-examples", 2)
    ]


def test_examples_without_table_or_rows() -> None:
    content = (
        "Feature: F\n"
        "  Scenario Outline: O\n"
        "    Given <x>\n"
        "    Examples: No table\n"
        "    Examples: No rows\n"
        "      | x |\n"
    )
    assert _codes(content) == [("examples.no-table", 4), ("examples.no-rows", 5)]


def test_placeholder_without_column_is_an_error() -> None:
    content = (
        "Feature: F\n"
        "  Scenario Outline: O\n"
        "    Given user <user>\n"
        "    Then <result> is shown\n"
        "    Examples:\n"
        "      | user |\n"
        "      | bob  |\n"
    )
    [issue] = _issues(content)
    assert (issue.code, issue.line, issue.severity) == (
        "examples.missing-column",
        4,
        IssueSeverity.ERROR,
    )
    assert "<result>" in issue.message


def test_missing_column_is_checked_per_examples_table() -> None:
    content = (
        "Feature: F\n"
        "  Scenario Outline: O\n"
        "    Given <a> and <b>\n"
        "    Examples: Full\n"
        "      | a | b |\n"
        "      | 1 | 2 |\n"
        "    Examples: Partial\n"
        "      | a |\n"
        "      | 1 |\n"
    )
    [issue] = _issues(content)
    assert issue.code == "examples.missing-column"
    assert "Examples at line 7" in issue.message


def test_unused_column_is_a_warning() -> None:
    content = (
        "Feature: F\n"
        "  Scenario Outline: O\n"
        "    Given <a>\n"
        "    Examples:\n"
        "      | a | spare |\n"
        "      | 1 | 2     |\n"
    )
    [issue] = _issues(content)
    assert (issue.code, issue.severity) == ("examples.unused-column", IssueSeverity.WARNING)


def test_placeholders_in_name_table_and_doc_string_count_as_used() -> None:
    assert _issues(VALID) == []  # role in name, item in table, user in doc string


def test_placeholders_in_background_are_not_substituted() -> None:
    content = (
        "Feature: F\n"
        "  Background:\n    Given <bg>\n"
        "  Scenario Outline: O\n    Given <a>\n"
        "    Examples:\n      | a | bg |\n      | 1 | 2  |\n"
    )
    assert [c for c, _ in _codes(content)] == ["examples.unused-column"]


def test_duplicate_and_empty_columns() -> None:
    content = (
        "Feature: F\n"
        "  Scenario Outline: O\n"
        "    Given <a>\n"
        "    Examples:\n"
        "      | a | a | |\n"
        "      | 1 | 2 | 3 |\n"
    )
    assert sorted(c for c, _ in _codes(content)) == [
        "examples.duplicate-column",
        "examples.empty-column",
    ]


def test_scenario_keyword_with_examples_is_validated_as_outline() -> None:
    content = "Feature: F\n  Scenario: S\n    Given <a>\n    Examples:\n      | b |\n      | 1 |\n"
    assert [c for c, _ in _codes(content)] == ["examples.missing-column", "examples.unused-column"]


# --- Report ------------------------------------------------------------------


def test_report_counts_and_ok() -> None:
    report = validate([_parsed(VALID), _parsed("Feature:\n")])

    assert isinstance(report, ValidationReport)
    assert (report.documents, report.scenarios) == (2, 2)
    assert [i.code for i in report.errors] == ["feature.missing-name"]
    assert [i.code for i in report.warnings] == ["feature.no-scenarios"]
    assert not report.ok


def test_warnings_alone_are_ok() -> None:
    report = validate([_parsed("Feature: F\n")])
    assert report.warnings and report.ok


def test_issues_are_in_source_order() -> None:
    content = (
        "Feature: F\n"
        "  Scenario:\n    Given a\n"
        "  Scenario: Empty\n"
        "  Scenario Outline: O\n    Given <x>\n"
    )
    lines = [line or 0 for _, line in _codes(content)]
    assert lines == sorted(lines)


def test_invalid_tags_are_reported_where_they_are_written() -> None:
    content = (
        "@ok @bad/feature\nFeature: F\n"
        "  @bad!rule\n  Rule: R\n"
        "    @fine @bad,scenario\n    Scenario: S\n      Given x\n"
    )
    issues = _issues(content)
    assert [(i.code, i.line) for i in issues] == [
        ("tag.invalid", 2), ("tag.invalid", 4), ("tag.invalid", 6),
    ]  # fmt: skip
    assert "@bad/feature must start with a letter or digit" in issues[0].message
