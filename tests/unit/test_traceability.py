"""Scenario traceability and change detection (TASK-021)."""

from collections.abc import Callable
from pathlib import PurePosixPath

import pytest

from qa_core.scenarios.parsing import parse_document
from qa_schemas.enums import ScenarioFormat
from qa_schemas.scenario import ParsedFeature, Scenario, ScenarioDocument, content_hash

BASE = """\
Feature: Shop
  Background:
    Given the shop is open

  Scenario: Buy
    When the customer buys "apple"
    Then the order is confirmed

  Scenario Outline: Pay with <method>
    When the customer pays with <method>
    Then the payment is <result>

    Examples:
      | method | result   |
      | card   | accepted |
"""


def _feature(content: str, path: str = "features/shop.feature") -> ParsedFeature:
    result = parse_document(
        ScenarioDocument(
            path=PurePosixPath(path),
            format=ScenarioFormat.GHERKIN,
            content=content,
            content_hash=content_hash(content.encode()),
        )
    )
    assert result.feature is not None, result.issues
    return result.feature


def _by_name(content: str) -> dict[str, Scenario]:
    return {s.name: s for s in _feature(content).scenarios}


def _hashes(content: str) -> dict[str, str]:
    return {name: s.content_hash for name, s in _by_name(content).items()}


# --- Traceability ------------------------------------------------------------


def test_every_scenario_traces_back_to_its_source() -> None:
    feature = _feature(BASE)
    assert feature.path == PurePosixPath("features/shop.feature")
    assert feature.name == "Shop"
    assert feature.content_hash == content_hash(BASE.encode())
    assert [(s.name, s.line) for s in feature.scenarios] == [
        ("Buy", 5),
        ("Pay with <method>", 9),
    ]
    assert all(s.content_hash.startswith("sha256:") for s in feature.scenarios)


def test_hash_is_deterministic() -> None:
    assert _hashes(BASE) == _hashes(BASE)


def test_scenarios_have_different_hashes() -> None:
    hashes = _hashes(BASE)
    assert len(set(hashes.values())) == len(hashes)


# --- Changes that are not changes --------------------------------------------


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: "\n\n# a comment\n" + s,  # everything moves down
        lambda s: s.replace("  Scenario: Buy\n", "  Scenario: Buy\n    Some description.\n"),
        lambda s: s.replace("    When the customer buys", "        When the customer buys"),
    ],
    ids=["moved", "description", "indentation"],
)
def test_irrelevant_edits_keep_the_hash(edit: Callable[[str], str]) -> None:
    assert _hashes(edit(BASE)) == _hashes(BASE)


def test_editing_one_scenario_does_not_change_the_other() -> None:
    edited = BASE.replace('buys "apple"', 'buys "pear"')
    before, after = _hashes(BASE), _hashes(edited)

    assert after["Buy"] != before["Buy"]
    assert after["Pay with <method>"] == before["Pay with <method>"]
    assert _feature(edited).content_hash != _feature(BASE).content_hash  # file changed


def test_adding_a_scenario_keeps_existing_hashes() -> None:
    extended = (
        BASE + "\n  Scenario: Refund\n    When a refund is requested\n    Then money is returned\n"
    )
    hashes = _hashes(extended)
    assert {k: hashes[k] for k in _hashes(BASE)} == _hashes(BASE)


# --- Changes that are changes ------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "changed"),
    [
        ('buys "apple"', 'buys "pear"', {"Buy"}),
        ("When the customer buys", "Given the customer buys", {"Buy"}),
        ("Scenario: Buy\n", "@smoke\n  Scenario: Buy\n", {"Buy"}),
        ("| card   | accepted |", "| cash   | accepted |", {"Pay with <method>"}),
        ("the shop is open", "the shop is closed", {"Buy", "Pay with <method>"}),
    ],
    ids=["step-text", "keyword", "tag", "examples", "background"],
)
def test_relevant_edits_change_the_hash(old: str, new: str, changed: set[str]) -> None:
    edited = BASE.replace(old, new)
    assert edited != BASE
    before, after = _hashes(BASE), _hashes(edited)
    assert {name for name in before if before[name] != after[name]} == changed


def test_step_arguments_are_part_of_the_hash() -> None:
    with_table = "Feature: F\n  Scenario: S\n    Given items:\n      | a |\n"
    other_table = with_table.replace("| a |", "| b |")
    with_doc = 'Feature: F\n  Scenario: S\n    Given items:\n      """\n      a\n      """\n'

    hashes = {_hashes(c)["S"] for c in (with_table, other_table, with_doc)}
    assert len(hashes) == 3


def test_same_scenario_in_another_file_has_the_same_hash() -> None:
    """The hash describes content, not location; the path identifies the file."""
    a = _feature(BASE, "a.feature").scenarios[0]
    b = _feature(BASE, "b.feature").scenarios[0]
    assert a.content_hash == b.content_hash
