"""Execution Plan generation (TASK-050, minimal).

A plan is derived from a specification, an environment and optionally an
explicit mode. The mode must fit the capabilities the specification needs:

| Mode     | Requires                          | Inferred when the specification needs |
|----------|-----------------------------------|---------------------------------------|
| fe       | ``browser``                       | ``browser`` only                      |
| be       | no ``browser``                    | anything without ``browser``          |
| full     | ``browser`` and something else    | ``browser`` and something else        |
| contract | ``http``, no ``browser``; contracts | never: chosen with ``--mode contract`` |
"""

from collections.abc import Collection

from qa_execution.registry import AdapterRegistry, AdapterSelectionError
from qa_schemas.enums import DependencyMode, ExecutionMode, TestCategory
from qa_schemas.plan import Dependency, ExecutionPlan, ExecutionSettings
from qa_schemas.project import Environment
from qa_schemas.specification import TestSpecification

BROWSER = "browser"
HTTP = "http"
_DEFAULT_EXECUTION_TIMEOUT = ExecutionSettings().timeout_seconds


class PlanningError(Exception):
    """No valid plan exists for the requested combination."""


def infer_mode(capabilities: frozenset[str]) -> ExecutionMode:
    if BROWSER not in capabilities:
        return ExecutionMode.BE
    return ExecutionMode.FE if capabilities == {BROWSER} else ExecutionMode.FULL


def check_mode(mode: ExecutionMode, capabilities: frozenset[str]) -> None:
    """Raise ``PlanningError`` if ``mode`` cannot run a specification needing ``capabilities``."""
    needs = ", ".join(sorted(capabilities)) or "nothing"
    if mode is ExecutionMode.CONTRACT and (BROWSER in capabilities or HTTP not in capabilities):
        raise PlanningError(
            f"contract mode checks API responses without a browser, but the specification "
            f"needs: {needs}"
        )
    if mode is ExecutionMode.FE and capabilities != {BROWSER}:
        raise PlanningError(
            f"fe mode runs browser steps only, but the specification needs: {needs}"
        )
    if mode is ExecutionMode.BE and BROWSER in capabilities:
        raise PlanningError(f"be mode runs without a browser, but the specification needs: {needs}")
    if mode is ExecutionMode.FULL and not (BROWSER in capabilities and len(capabilities) > 1):
        raise PlanningError(
            f"full mode combines the browser with other components, but the specification needs: "
            f"{needs}; use {infer_mode(capabilities).value} instead"
        )


def create_plan(
    specification: TestSpecification,
    environment: Environment,
    adapters: AdapterRegistry,
    *,
    mode: ExecutionMode | None = None,
    category: TestCategory = TestCategory.FUNCTIONAL,
    execution_timeout: float | None = None,
    mocked: Collection[str] = (),
) -> ExecutionPlan:
    """A validated plan, or ``PlanningError`` explaining why none is possible.

    ``execution_timeout`` overrides the limit for the whole execution (default
    600 s, or the environment's step timeout if that is longer).
    """
    if category is not TestCategory.FUNCTIONAL:
        raise PlanningError(f"only functional tests are supported so far, not {category.value}")
    capabilities = frozenset(specification.required_capabilities)
    chosen = mode or infer_mode(capabilities)
    check_mode(chosen, capabilities)
    if chosen is ExecutionMode.CONTRACT and not environment.contracts:
        raise PlanningError(
            f"contract mode needs contracts: in environment {environment.name!r} "
            "(service -> OpenAPI file)"
        )
    try:
        selection = adapters.select(capabilities)
    except AdapterSelectionError as error:
        raise PlanningError(str(error)) from None
    return ExecutionPlan(
        id=f"{specification.id}.{chosen.value}.{environment.name}",
        specification_id=specification.id,
        mode=chosen,
        category=category,
        environment=environment.name,
        adapters=selection.names,
        settings=_settings(environment, execution_timeout),
        dependencies=tuple(Dependency(name=n, mode=DependencyMode.MOCK) for n in sorted(mocked)),
    )


def _settings(environment: Environment, execution_timeout: float | None) -> ExecutionSettings:
    step = environment.timeout_seconds
    total = execution_timeout or max(_DEFAULT_EXECUTION_TIMEOUT, step)
    try:
        return ExecutionSettings(step_timeout_seconds=min(step, total), timeout_seconds=total)
    except ValueError as error:
        raise PlanningError(f"invalid execution timeout {total:g}s: {error}") from None
