"""Scenario -> Test Specification conversion (TASK-023)."""

from pathlib import Path, PurePosixPath

import pytest

from qa_core.scenarios.conversion import ConversionError, convert_feature, slugify
from qa_core.scenarios.parsing import parse_document
from qa_schemas.enums import ScenarioFormat, StepKind
from qa_schemas.scenario import ParsedFeature, ScenarioDocument, content_hash
from qa_schemas.specification import TestSpecification

ROOT = Path(__file__).parents[2]
BASE = PurePosixPath("scenarios")

P, A, E = StepKind.PRECONDITION, StepKind.ACTION, StepKind.EXPECTATION


def _feature(content: str, path: str = "scenarios/shop.feature") -> ParsedFeature:
    result = parse_document(
        ScenarioDocument(
            path=PurePosixPath(path),
            format=ScenarioFormat.GHERKIN,
            content=content,
            content_hash=content_hash(content.encode()),
        )
    )
    assert result.ok and result.feature is not None, result.issues
    return result.feature


def _specs(content: str, path: str = "scenarios/shop.feature") -> list[TestSpecification]:
    return convert_feature(_feature(content, path), BASE)


OUTLINE = """\
@shop
Feature: Shop
  Background:
    Given a voucher "<code>" placeholder stays literal

  @vouchers
  Scenario Outline: Apply <code>
    When the customer applies "<code>"
    Then the total is <total>
    And the receipt shows:
      | code   | total   |
      | <code> | <total> |
    And the email says:
      \"\"\"text
      You saved with <code>.
      \"\"\"

    @valid
    Examples: Valid
      | code   | total |
      | SAVE10 | 90    |
      | SAVE20 | 80    |

    Examples: Invalid
      | code  | total |
      | WRONG | 100   |
"""


# --- Example project ---------------------------------------------------------


def test_example_feature_compiles_to_the_sample_specification() -> None:
    feature = _feature(
        (ROOT / "examples/scenarios/login.feature").read_text(), "scenarios/login.feature"
    )
    first, *_ = convert_feature(feature, BASE)  # the sample is the first scenario

    sample = (ROOT / "examples/specifications/login.spec.json").read_text()
    assert first.model_dump_json(indent=2) + "\n" == sample


# --- Steps -------------------------------------------------------------------


def test_conjunctions_take_the_previous_kind() -> None:
    [spec] = _specs(
        "Feature: F\n"
        "  Background:\n    Given a\n    And b\n"
        "  Scenario: S\n    When c\n    But d\n    * e\n    Then f\n    And g\n    * h\n"
    )
    steps = spec.test_cases[0].steps
    assert [(s.keyword, s.kind) for s in steps] == [
        ("Given", P), ("And", P), ("When", A), ("But", A), ("*", A),
        ("Then", E), ("And", E), ("*", E),
    ]  # fmt: skip


def test_conjunction_continues_from_background() -> None:
    [spec] = _specs(
        "Feature: F\n  Background:\n    Given a\n  Scenario: S\n    And b\n    Then c\n"
    )
    assert [s.kind for s in spec.test_cases[0].steps] == [P, P, E]


def test_ambiguous_first_step_raises_with_location() -> None:
    with pytest.raises(ConversionError, match=r"scenarios/shop.feature:3: .*'And'") as info:
        _specs("Feature: F\n  Scenario: S\n    And a\n")
    assert info.value.line == 3


def test_step_arguments_are_kept() -> None:
    [spec] = _specs(
        "Feature: F\n  Scenario: S\n    Given items:\n      | a | b |\n      | 1 | 2 |\n"
        '    Then body:\n      """json\n      {}\n      """\n'
    )
    given, then = spec.test_cases[0].steps
    assert given.data_table == (("a", "b"), ("1", "2"))
    assert then.doc_string is not None
    assert (then.doc_string.content, then.doc_string.media_type) == ("{}", "json")


# --- Scenario Outline --------------------------------------------------------


def test_outline_yields_one_case_per_row_across_examples() -> None:
    [spec] = _specs(OUTLINE)

    assert spec.id == "shop.apply-code"
    assert [(c.id, c.name, c.parameters) for c in spec.test_cases] == [
        ("shop.apply-code:1", "Apply SAVE10", {"code": "SAVE10", "total": "90"}),
        ("shop.apply-code:2", "Apply SAVE20", {"code": "SAVE20", "total": "80"}),
        ("shop.apply-code:3", "Apply WRONG", {"code": "WRONG", "total": "100"}),
    ]


def test_values_are_substituted_in_texts_tables_and_doc_strings() -> None:
    case = _specs(OUTLINE)[0].test_cases[1]
    background, when, then, table, email = case.steps

    assert when.text == 'the customer applies "SAVE20"'
    assert then.text == "the total is 80"
    assert table.data_table == (("code", "total"), ("SAVE20", "80"))
    assert email.doc_string is not None
    assert email.doc_string.content == "You saved with SAVE20."
    assert background.text == 'a voucher "<code>" placeholder stays literal'


def test_repeated_case_names_are_numbered() -> None:
    [spec] = _specs(
        "Feature: F\n  Scenario Outline: Same name\n    Given <x>\n"
        "    Examples:\n      | x |\n      | 1 |\n      | 2 |\n"
    )
    assert [c.name for c in spec.test_cases] == ["Same name #1", "Same name #2"]


def test_scenario_with_examples_is_expanded() -> None:
    [spec] = _specs(
        "Feature: F\n  Scenario: S <x>\n    Given <x>\n    Examples:\n      | x |\n      | 1 |\n"
    )
    assert [c.id for c in spec.test_cases] == ["shop.s-x:1"]
    assert spec.test_cases[0].steps[0].text == "1"


def test_plain_scenario_has_a_single_case_with_the_spec_id() -> None:
    [spec] = _specs("Feature: F\n  Scenario: Buy\n    Given a\n")
    [case] = spec.test_cases
    assert (case.id, case.name, case.parameters) == ("shop.buy", "Buy", {})


# --- Ids and metadata --------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("scenarios/login.feature", "login.ok"),
        ("scenarios/auth/Admin Login.feature", "auth.admin-login.ok"),
        ("other/login.feature", "other.login.ok"),
    ],
)
def test_ids_come_from_path_and_name(path: str, expected: str) -> None:
    [spec] = _specs("Feature: F\n  Scenario: OK!\n    Given a\n", path)
    assert spec.id == expected


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Successful login", "successful-login"),
        ("Logowanie użytkownika \u2013 Łódź", "logowanie-uzytkownika-lodz"),
        ("  Café: 50% off!  ", "cafe-50-off"),
        ("<code> applied", "code-applied"),
        ("日本語", ""),
        ("x" * 200, "x" * 80),
    ],
)
def test_slugify(text: str, slug: str) -> None:
    assert slugify(text) == slug


def test_colliding_slugs_get_suffixes_in_source_order() -> None:
    specs = _specs(
        "Feature: F\n"
        "  Scenario: Login!\n    Given a\n"
        "  Scenario: Login?\n    Given b\n"
        "  Scenario: 日本語\n    Given c\n"
    )
    assert [s.id for s in specs] == ["shop.login", "shop.login-2", "shop.scenario-6"]


def test_source_reference_and_metadata() -> None:
    feature = _feature(OUTLINE)
    [spec] = convert_feature(feature, BASE)

    assert spec.source.path == PurePosixPath("scenarios/shop.feature")
    assert (spec.source.feature, spec.source.scenario, spec.source.line) == (
        "Shop", "Apply <code>", 7,
    )  # fmt: skip
    assert spec.source.content_hash == feature.scenarios[0].content_hash
    assert spec.metadata.tags == ("shop", "vouchers")
    assert spec.required_capabilities == ()


def test_tags_from_feature_rule_and_scenario_are_merged() -> None:
    [spec] = _specs(
        "@a @b\nFeature: F\n  @b @c\n  Rule: R\n    @a @d\n    Scenario: S\n      Given x\n"
    )
    assert spec.metadata.tags == ("a", "b", "c", "d")


def test_description_is_kept() -> None:
    [spec] = _specs("Feature: F\n  Scenario: S\n    Why this matters.\n    Given x\n")
    assert spec.metadata.description == "Why this matters."


def test_invalid_tag_raises_conversion_error() -> None:
    """Normally caught by validation (tag.invalid); conversion still refuses it."""
    with pytest.raises(ConversionError, match=r"shop.feature:3: tags"):
        _specs("Feature: F\n  @bad/tag\n  Scenario: S\n    Given x\n")


# --- Determinism -------------------------------------------------------------


def test_conversion_is_deterministic() -> None:
    assert _specs(OUTLINE) == _specs(OUTLINE)
    first = [s.model_dump_json() for s in _specs(OUTLINE)]
    assert first == [s.model_dump_json() for s in _specs(OUTLINE)]


def test_every_scenario_produces_a_valid_specification() -> None:
    specs = _specs(OUTLINE + "\n  Scenario: Plain\n    Given a\n    Then b\n")
    assert len(specs) == 2
    for spec in specs:
        assert TestSpecification.model_validate_json(spec.model_dump_json()) == spec
