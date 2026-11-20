"""Execution Plan: how and where a Test Specification is executed (TASK-009).

A plan references its specification by id instead of embedding it, so one
specification can have many plans (e.g. FULL on staging, BE locally) and plans
can be stored and validated on their own.

Checking that the mode, adapters and environment fit together is the job of
plan generation (TASK-050); this schema only validates the plan's own shape.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, PositiveFloat, model_validator

from qa_schemas.base import Identifier, SchemaModel, StableId, find_duplicates
from qa_schemas.enums import DependencyMode, ExecutionMode, TestCategory

PLAN_SCHEMA_VERSION: Literal[1] = 1
"""Bump on any incompatible change to the plan format."""


class Dependency(SchemaModel):
    """An external service the tests need, and whether it is real or mocked."""

    name: Identifier
    """Service name, matching an entry in the environment's ``services``."""
    mode: DependencyMode = DependencyMode.REAL


class ExecutionSettings(SchemaModel):
    timeout_seconds: Annotated[PositiveFloat, Field(le=86_400)] = 600.0
    """Upper bound for the whole execution."""
    step_timeout_seconds: Annotated[PositiveFloat, Field(le=3600)] = 30.0
    """Upper bound for a single step."""
    fail_fast: bool = False
    """Stop after the first failed test case."""

    @model_validator(mode="after")
    def _step_fits_in_execution(self) -> Self:
        if self.step_timeout_seconds > self.timeout_seconds:
            raise ValueError("step_timeout_seconds must not exceed timeout_seconds")
        return self


class ExecutionPlan(SchemaModel):
    schema_version: Literal[1] = PLAN_SCHEMA_VERSION
    id: StableId
    specification_id: StableId
    mode: ExecutionMode
    category: TestCategory
    environment: Identifier
    adapters: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    """Adapters selected for execution, e.g. ``("playwright", "httpx")``."""
    dependencies: tuple[Dependency, ...] = ()
    settings: ExecutionSettings = ExecutionSettings()

    @model_validator(mode="after")
    def _unique_names(self) -> Self:
        if dup := find_duplicates(self.adapters):
            raise ValueError(f"duplicate adapters: {dup}")
        if dup := find_duplicates(d.name for d in self.dependencies):
            raise ValueError(f"duplicate dependencies: {dup}")
        return self
