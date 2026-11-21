"""Execution Plan generation (TASK-050, minimal)."""

from pathlib import Path
from typing import Any

import pytest

from qa_execution.adapters import ExecutionContext, TestAdapter
from qa_execution.planning import PlanningError, create_plan, infer_mode
from qa_execution.registry import AdapterRegistry
from qa_schemas.enums import ExecutionMode, TestCategory
from qa_schemas.project import Environment
from qa_schemas.specification import TestSpecification

ROOT = Path(__file__).parents[2]
FE, BE, FULL, CONTRACT = (
    ExecutionMode.FE,
    ExecutionMode.BE,
    ExecutionMode.FULL,
    ExecutionMode.CONTRACT,
)


class _Fake(TestAdapter):
    def prepare(self, context: ExecutionContext) -> None: ...

    def cleanup(self) -> None: ...

    @property
    def resource(self) -> Any:
        return None


class Browser(_Fake):
    name = "browser-adapter"
    capabilities = frozenset({"browser"})


class Http(_Fake):
    name = "http-adapter"
    capabilities = frozenset({"http"})


ADAPTERS = AdapterRegistry([Browser, Http])


def _spec(*capabilities: str) -> TestSpecification:
    spec = TestSpecification.model_validate_json(
        (ROOT / "tests/fixtures/login/login.spec.json").read_text()
    )
    return spec.model_copy(update={"required_capabilities": tuple(sorted(capabilities))})


@pytest.mark.parametrize(
    ("capabilities", "mode"),
    [({"browser"}, FE), ({"http"}, BE), ({"browser", "http"}, FULL), (set(), BE)],
)
def test_mode_is_inferred_from_capabilities(capabilities: set[str], mode: ExecutionMode) -> None:
    assert infer_mode(frozenset(capabilities)) is mode


def test_plan_for_a_browser_specification() -> None:
    plan = create_plan(_spec("browser"), Environment(name="local", timeout_seconds=12), ADAPTERS)

    assert plan.id == "login.successful-login.fe.local"
    assert (plan.mode, plan.category, plan.environment) == (FE, TestCategory.FUNCTIONAL, "local")
    assert plan.adapters == ("browser-adapter",)
    assert plan.settings.step_timeout_seconds == 12


def test_same_specification_different_plans() -> None:
    spec = _spec("browser", "http")
    local = create_plan(spec, Environment(name="local"), ADAPTERS)
    staging = create_plan(spec, Environment(name="staging"), ADAPTERS, mode=FULL)
    assert (local.mode, local.adapters) == (FULL, ("browser-adapter", "http-adapter"))
    assert local.id != staging.id
    assert local.specification_id == staging.specification_id


@pytest.mark.parametrize(
    ("capabilities", "mode", "message"),
    [
        ({"browser"}, BE, "be mode runs without a browser"),
        ({"browser", "http"}, FE, "fe mode runs browser steps only"),
        ({"http"}, FE, "fe mode runs browser steps only"),
        ({"browser"}, FULL, "use fe instead"),
        ({"http"}, FULL, "use be instead"),
        ({"browser"}, CONTRACT, "contract mode is not implemented yet"),
    ],
)
def test_unsupported_combinations_are_rejected(
    capabilities: set[str], mode: ExecutionMode, message: str
) -> None:
    with pytest.raises(PlanningError, match=message):
        create_plan(_spec(*capabilities), Environment(name="local"), ADAPTERS, mode=mode)


def test_only_functional_category_is_supported() -> None:
    with pytest.raises(
        PlanningError, match="only functional tests are supported so far, not visual"
    ):
        create_plan(
            _spec("browser"), Environment(name="local"), ADAPTERS, category=TestCategory.VISUAL
        )


def test_missing_adapter_is_rejected() -> None:
    with pytest.raises(PlanningError, match="not provided by any registered adapter: http"):
        create_plan(_spec("http"), Environment(name="local"), AdapterRegistry([Browser]))


def test_long_environment_timeout_extends_the_execution_timeout() -> None:
    plan = create_plan(_spec("browser"), Environment(name="slow", timeout_seconds=1200), ADAPTERS)
    assert plan.settings.step_timeout_seconds == 1200
    assert plan.settings.timeout_seconds >= 1200


def test_execution_timeout_can_be_overridden() -> None:
    environment = Environment(name="local", timeout_seconds=30)
    plan = create_plan(_spec("browser"), environment, ADAPTERS, execution_timeout=7200)
    assert plan.settings.timeout_seconds == 7200
    assert plan.settings.step_timeout_seconds == 30


def test_short_execution_timeout_also_limits_steps() -> None:
    environment = Environment(name="local", timeout_seconds=30)
    plan = create_plan(_spec("browser"), environment, ADAPTERS, execution_timeout=10)
    assert (plan.settings.timeout_seconds, plan.settings.step_timeout_seconds) == (10, 10)


def test_default_execution_timeout_is_bounded() -> None:
    plan = create_plan(_spec("browser"), Environment(name="local"), ADAPTERS)
    assert plan.settings.timeout_seconds == 600
