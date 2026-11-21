"""Compilation output: a specification together with its compilation status (TASK-026).

This is the format stored in ``.qa/specifications/<id>.json``. Execution must
check ``status.is_executable`` before running anything.
"""

from typing import Literal

from pydantic import PositiveInt

from qa_schemas.base import SchemaModel, StableId
from qa_schemas.enums import CompilationStatus, StepKind
from qa_schemas.specification import TestSpecification

COMPILED_SCHEMA_VERSION: Literal[1] = 1


class UnresolvedStep(SchemaModel):
    """A step that no registered definition can execute."""

    test_case_id: StableId
    step_index: int
    line: PositiveInt | None = None
    kind: StepKind
    text: str
    reason: str


class CompiledSpecification(SchemaModel):
    schema_version: Literal[1] = COMPILED_SCHEMA_VERSION
    status: CompilationStatus
    reasons: tuple[str, ...] = ()
    """Why the status is not READY; empty when it is."""
    unresolved: tuple[UnresolvedStep, ...] = ()
    specification: TestSpecification
