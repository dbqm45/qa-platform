"""Tests for the Test Specification schema (TASK-008)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qa_core.scenarios.parsing import parse_document
from qa_core.scenarios.sources import LocalFileSource
from qa_schemas.enums import StepKind
from qa_schemas.specification import SPECIFICATION_SCHEMA_VERSION, TestSpecification

ROOT = Path(__file__).parents[2]
SAMPLE = ROOT / "tests/fixtures/login/login.spec.json"


def _sample() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SAMPLE.read_text())
    return data


def _spec(**overrides: Any) -> TestSpecification:
    return TestSpecification.model_validate(_sample() | overrides)


# --- Sample file -------------------------------------------------------------


def test_sample_specification_is_valid_and_canonical() -> None:
    """The sample is exactly what serializing the model produces."""
    text = SAMPLE.read_text()
    spec = TestSpecification.model_validate_json(text)
    assert spec.model_dump_json(indent=2) + "\n" == text


def test_sample_traces_back_to_its_scenario() -> None:
    """The source hash is the scenario's content hash, so outdated specs can be detected."""
    spec = _spec()
    project = ROOT / "tests/fixtures/login"
    [document] = LocalFileSource(project, [Path("scenarios")]).discover().documents
    feature = parse_document(document).feature
    assert feature is not None
    [scenario] = feature.scenarios

    assert spec.source.path == document.path
    assert (spec.source.feature, spec.source.scenario) == (feature.name, scenario.name)
    assert spec.source.content_hash == scenario.content_hash


def test_json_round_trip() -> None:
    spec = _spec()
    assert TestSpecification.model_validate_json(spec.model_dump_json()) == spec


# --- Structure ---------------------------------------------------------------


def test_steps_are_grouped_by_kind_preserving_order() -> None:
    case = _spec().test_cases[0]
    assert [s.text for s in case.preconditions] == ["the login page is open"]
    assert len(case.actions) == 1
    assert [s.keyword for s in case.expected_results] == ["Then", "And"]
    assert [s.kind for s in case.steps] == [
        StepKind.PRECONDITION, StepKind.ACTION, StepKind.EXPECTATION, StepKind.EXPECTATION,
    ]  # fmt: skip


def test_specification_contains_no_execution_details() -> None:
    """Mode, environment, adapters and URLs belong to the Execution Plan."""
    fields = set(TestSpecification.model_fields)
    assert not fields & {"mode", "category", "environment", "adapters", "base_url", "settings"}


def test_case_without_expectations_is_representable() -> None:
    """Whether it may run is decided by compilation (TASK-026), not by the schema."""
    data = _sample()
    steps = data["test_cases"][0]["steps"]
    data["test_cases"][0]["steps"] = [s for s in steps if s["kind"] != "expectation"]
    assert TestSpecification.model_validate(data).test_cases[0].expected_results == ()


# --- Versioning --------------------------------------------------------------


def test_schema_version_defaults_to_current() -> None:
    data = _sample()
    del data["schema_version"]
    assert TestSpecification.model_validate(data).schema_version == SPECIFICATION_SCHEMA_VERSION


@pytest.mark.parametrize("version", [0, 2, "1"])
def test_unknown_schema_version_is_rejected(version: object) -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        _spec(schema_version=version)


# --- Invalid data ------------------------------------------------------------


def test_specification_requires_a_test_case() -> None:
    with pytest.raises(ValidationError, match="test_cases"):
        _spec(test_cases=[])


def test_test_case_requires_a_step() -> None:
    data = _sample()
    data["test_cases"][0]["steps"] = []
    with pytest.raises(ValidationError, match="steps"):
        TestSpecification.model_validate(data)


def test_duplicate_test_case_ids_are_rejected() -> None:
    case = _sample()["test_cases"][0]
    with pytest.raises(ValidationError, match="duplicate test case ids"):
        _spec(test_cases=[case, case])


def test_duplicate_capabilities_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate required capabilities"):
        _spec(required_capabilities=["browser", "browser"])


def test_duplicate_tags_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate tags"):
        _spec(metadata={"tags": ["smoke", "smoke"]})


@pytest.mark.parametrize("tag", ["@smoke", "", "with space"])
def test_invalid_tag_is_rejected(tag: str) -> None:
    with pytest.raises(ValidationError, match="tags"):
        _spec(metadata={"tags": [tag]})


@pytest.mark.parametrize("path", ["/abs/login.feature", "../outside/login.feature"])
def test_source_path_must_be_inside_project(path: str) -> None:
    source = _sample()["source"] | {"path": path}
    with pytest.raises(ValidationError, match="relative to the project root"):
        _spec(source=source)


@pytest.mark.parametrize("value", ["abc", "md5:" + "0" * 32, "sha256:" + "Z" * 64])
def test_invalid_content_hash_is_rejected(value: str) -> None:
    source = _sample()["source"] | {"content_hash": value}
    with pytest.raises(ValidationError, match="content_hash"):
        _spec(source=source)


def test_invalid_step_kind_is_rejected() -> None:
    data = _sample()
    data["test_cases"][0]["steps"][0]["kind"] = "given"
    with pytest.raises(ValidationError, match="kind"):
        TestSpecification.model_validate(data)


def test_blank_step_text_is_rejected() -> None:
    data = _sample()
    data["test_cases"][0]["steps"][0]["text"] = "   "
    with pytest.raises(ValidationError, match="text"):
        TestSpecification.model_validate(data)
