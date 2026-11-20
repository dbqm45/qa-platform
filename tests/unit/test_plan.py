"""Tests for the Execution Plan schema (TASK-009, TASK-010)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qa_schemas.enums import DependencyMode, ExecutionMode, TestCategory
from qa_schemas.plan import PLAN_SCHEMA_VERSION, ExecutionPlan
from qa_schemas.specification import TestSpecification

ROOT = Path(__file__).parents[2]
PLANS = sorted((ROOT / "examples/plans").glob("*.plan.json"))
SPEC = ROOT / "examples/specifications/login.spec.json"


def _plan(**overrides: Any) -> ExecutionPlan:
    data: dict[str, Any] = {
        "id": "login.full.staging",
        "specification_id": "login.successful-login",
        "mode": "full",
        "category": "functional",
        "environment": "staging",
        "adapters": ["playwright", "httpx"],
    }
    return ExecutionPlan.model_validate(data | overrides)


# --- Sample files ------------------------------------------------------------


@pytest.mark.parametrize("path", PLANS, ids=lambda p: p.name)
def test_sample_plans_are_valid_and_canonical(path: Path) -> None:
    text = path.read_text()
    plan = ExecutionPlan.model_validate_json(text)
    assert plan.model_dump_json(indent=2) + "\n" == text


def test_one_specification_has_several_plans() -> None:
    spec = TestSpecification.model_validate_json(SPEC.read_text())
    plans = [ExecutionPlan.model_validate_json(p.read_text()) for p in PLANS]

    assert len(plans) >= 2
    assert {p.specification_id for p in plans} == {spec.id}
    assert len({(p.mode, p.environment) for p in plans}) == len(plans)


def test_plan_is_validated_without_its_specification() -> None:
    """Only the reference is stored; the specification is not needed to validate."""
    plan = _plan(specification_id="not-loaded-anywhere")
    assert plan.specification_id == "not-loaded-anywhere"


# --- Mode and category (TASK-010, TASK-011) ----------------------------------


def test_mode_and_category_are_stored_as_enums() -> None:
    plan = _plan()
    assert plan.mode is ExecutionMode.FULL
    assert plan.category is TestCategory.FUNCTIONAL
    assert json.loads(plan.model_dump_json())["mode"] == "full"


@pytest.mark.parametrize("mode", ["e2e", "FULL", ""])
def test_invalid_mode_is_rejected(mode: str) -> None:
    with pytest.raises(ValidationError, match="mode"):
        _plan(mode=mode)


def test_invalid_category_is_rejected() -> None:
    with pytest.raises(ValidationError, match="category"):
        _plan(category="smoke")


# --- Defaults and round trip -------------------------------------------------


def test_defaults() -> None:
    plan = _plan()
    assert plan.schema_version == PLAN_SCHEMA_VERSION
    assert plan.dependencies == ()
    assert plan.settings.timeout_seconds == 600
    assert plan.settings.step_timeout_seconds == 30
    assert plan.settings.fail_fast is False


def test_dependency_defaults_to_real() -> None:
    plan = _plan(dependencies=[{"name": "api"}])
    assert plan.dependencies[0].mode is DependencyMode.REAL


def test_json_round_trip() -> None:
    plan = _plan(dependencies=[{"name": "api", "mode": "mock"}], settings={"fail_fast": True})
    assert ExecutionPlan.model_validate_json(plan.model_dump_json()) == plan


# --- Invalid data ------------------------------------------------------------


@pytest.mark.parametrize("version", [0, 2])
def test_unknown_schema_version_is_rejected(version: int) -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        _plan(schema_version=version)


@pytest.mark.parametrize("missing", ["specification_id", "mode", "category", "environment"])
def test_required_fields(missing: str) -> None:
    data = _plan().model_dump()
    del data[missing]
    with pytest.raises(ValidationError, match=missing):
        ExecutionPlan.model_validate(data)


def test_plan_requires_an_adapter() -> None:
    with pytest.raises(ValidationError, match="adapters"):
        _plan(adapters=[])


def test_duplicate_adapters_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate adapters"):
        _plan(adapters=["httpx", "httpx"])


def test_duplicate_dependencies_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate dependencies"):
        _plan(dependencies=[{"name": "api"}, {"name": "api", "mode": "mock"}])


def test_invalid_dependency_mode_is_rejected() -> None:
    with pytest.raises(ValidationError, match="mode"):
        _plan(dependencies=[{"name": "api", "mode": "stub"}])


@pytest.mark.parametrize(
    "settings",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": 86_401},
        {"step_timeout_seconds": -1},
        {"timeout_seconds": 10, "step_timeout_seconds": 20},
    ],
)
def test_invalid_settings_are_rejected(settings: dict[str, float]) -> None:
    with pytest.raises(ValidationError, match="timeout"):
        _plan(settings=settings)


def test_unknown_setting_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _plan(settings={"headless": True})
