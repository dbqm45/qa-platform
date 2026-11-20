"""Gherkin parsing into normalized scenario models (TASK-019)."""

from pathlib import Path, PurePosixPath

import pytest

from qa_core.scenarios.parsing import parse_document
from qa_schemas.enums import ScenarioFormat, StepKeywordType
from qa_schemas.scenario import ParsedFeature, ParseResult, ScenarioDocument, content_hash

ROOT = Path(__file__).parents[2]

FULL = """\
@billing @team:payments
Feature: Checkout
  Customers pay for their basket.

  Background:
    Given a customer is signed in

  Scenario: Pay by card
    Given the basket contains:
      | product | qty |
      | apple   | 2   |
    When the customer pays with:
      \"\"\"json
      {"card": "4242"}
      \"\"\"
    Then the order is confirmed
    But no email is sent
    * the basket is empty

  Rule: Vouchers reduce the price
    Background:
      Given a voucher "SAVE10" exists

    @smoke
    Scenario Outline: Apply voucher <code>
      When the customer applies "<code>"
      Then the total is <total>

      @valid
      Examples: Valid
        | code   | total |
        | SAVE10 | 90    |
        | SAVE20 | 80    |

      Examples: Invalid
        | code  | total |
        | WRONG | 100   |
"""


def _parse(content: str, path: str = "features/x.feature") -> ParseResult:
    document = ScenarioDocument(
        path=PurePosixPath(path),
        format=ScenarioFormat.GHERKIN,
        content=content,
        content_hash=content_hash(content.encode()),
    )
    return parse_document(document)


def _feature(content: str) -> ParsedFeature:
    result = _parse(content)
    assert result.ok, result.issues
    assert result.feature is not None
    return result.feature


# --- Structure ---------------------------------------------------------------


def test_example_login_feature() -> None:
    path = ROOT / "examples/scenarios/login.feature"
    feature = _feature(path.read_text())

    assert (feature.name, feature.tags, feature.language, feature.line) == (
        "Login",
        ("smoke",),
        "en",
        2,
    )
    [scenario] = feature.scenarios
    assert scenario.name == "Successful login"
    assert scenario.line == 7
    assert [(s.keyword, s.text, s.line) for s in scenario.background] == [
        ("Given", "the login page is open", 5)
    ]
    assert [(s.keyword, s.keyword_type) for s in scenario.steps] == [
        ("When", StepKeywordType.ACTION),
        ("Then", StepKeywordType.OUTCOME),
        ("And", StepKeywordType.CONJUNCTION),
    ]


def test_feature_metadata() -> None:
    feature = _feature(FULL)
    assert feature.path == PurePosixPath("features/x.feature")
    assert feature.content_hash == content_hash(FULL.encode())
    assert feature.tags == ("billing", "team:payments")
    assert feature.description == "Customers pay for their basket."
    assert [s.name for s in feature.scenarios] == ["Pay by card", "Apply voucher <code>"]


def test_step_arguments_and_keyword_types() -> None:
    card = _feature(FULL).scenarios[0]
    given, when, then, but, star = card.steps

    assert given.data_table == (("product", "qty"), ("apple", "2"))
    assert when.doc_string is not None
    assert when.doc_string.content == '{"card": "4242"}'
    assert when.doc_string.media_type == "json"
    assert then.data_table is None and then.doc_string is None
    assert (but.keyword, but.keyword_type) == ("But", StepKeywordType.CONJUNCTION)
    assert (star.keyword, star.keyword_type) == ("*", StepKeywordType.UNKNOWN)


def test_rule_background_is_appended_to_feature_background() -> None:
    card, voucher = _feature(FULL).scenarios

    assert card.rule is None
    assert [s.text for s in card.background] == ["a customer is signed in"]
    assert voucher.rule is not None
    assert voucher.rule.name == "Vouchers reduce the price"
    assert [s.text for s in voucher.background] == [
        "a customer is signed in",
        'a voucher "SAVE10" exists',
    ]


def test_scenario_outline_with_examples() -> None:
    voucher = _feature(FULL).scenarios[1]

    assert voucher.is_outline
    assert voucher.tags == ("smoke",)
    assert voucher.steps[0].text == 'the customer applies "<code>"'
    valid, invalid = voucher.examples
    assert (valid.name, valid.tags, valid.header) == ("Valid", ("valid",), ("code", "total"))
    assert [(r.line, r.values) for r in valid.rows] == [
        (32, ("SAVE10", "90")),
        (33, ("SAVE20", "80")),
    ]
    assert invalid.rows[0].values == ("WRONG", "100")


def test_scenario_and_example_keywords_are_not_outlines() -> None:
    feature = _feature("Feature: F\n  Scenario: A\n    Given x\n  Example: B\n    Given y\n")
    assert [(s.keyword, s.is_outline) for s in feature.scenarios] == [
        ("Scenario", False),
        ("Example", False),
    ]


def test_other_language() -> None:
    feature = _feature(
        "# language: pl\n"
        "Właściwość: Logowanie\n"
        "  Szablon scenariusza: Logowanie <user>\n"
        "    Zakładając, że strona logowania jest otwarta\n"
        "    Gdy użytkownik loguje się jako <user>\n"
        "    Wtedy widzi pulpit\n"
        "    Oraz widzi powitanie\n"
        "    Przykłady:\n"
        "      | user  |\n"
        "      | alice |\n"
    )
    [scenario] = feature.scenarios
    assert feature.language == "pl"
    assert scenario.is_outline
    assert [s.keyword_type for s in scenario.steps] == [
        StepKeywordType.CONTEXT,
        StepKeywordType.ACTION,
        StepKeywordType.OUTCOME,
        StepKeywordType.CONJUNCTION,
    ]
    assert scenario.steps[0].keyword == "Zakładając, że"


# --- Permissive representation (validated in TASK-020) -----------------------


def test_incomplete_scenarios_are_represented_not_rejected() -> None:
    feature = _feature(
        "Feature: F\n"
        "  Scenario:\n"
        "  Scenario Outline: No examples\n"
        "    Given <x>\n"
        "  Scenario Outline: Examples without table\n"
        "    Given <x>\n"
        "    Examples:\n"
    )
    unnamed, no_examples, no_table = feature.scenarios
    assert (unnamed.name, unnamed.steps) == ("", ())
    assert no_examples.is_outline and no_examples.examples == ()
    assert no_table.examples[0].header is None
    assert no_table.examples[0].rows == ()


@pytest.mark.parametrize("content", ["", "\n\n", "# just a comment\n"])
def test_file_without_feature(content: str) -> None:
    result = _parse(content)
    assert result.ok
    assert result.feature is None


# --- Errors ------------------------------------------------------------------


def test_syntax_error_has_location_and_readable_message() -> None:
    result = _parse("Feature: F\n  Scenario: A\n    Given x\n  oops\n")

    assert result.feature is None
    [issue] = result.issues
    assert (issue.path, issue.line, issue.column) == (PurePosixPath("features/x.feature"), 4, 3)
    assert issue.message.startswith("unexpected 'oops'; expected ")
    assert "#" not in issue.message


def test_all_errors_are_reported_in_file_order() -> None:
    result = _parse("Feature: F\n  Scenario: A\n    Given x\n    | a | b |\n    | c |\n  garbage\n")
    assert [issue.line for issue in result.issues] == [5, 6]
    assert result.issues[0].message == "inconsistent cell count within the table"


def test_unknown_language_is_an_error() -> None:
    [issue] = _parse("# language: xx\nFeature: F\n").issues
    assert issue.message == "Language not supported: xx"


def test_parsing_is_deterministic() -> None:
    assert _parse(FULL) == _parse(FULL)
