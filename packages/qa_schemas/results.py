"""Normalized execution results (TASK-006, TASK-036, TASK-038).

The same structure is produced for every adapter, so reporting does not need
to know which adapters ran a test.
"""

from typing import Literal, Self

from pydantic import AwareDatetime, NonNegativeInt, PositiveInt, model_validator

from qa_schemas.base import SchemaModel, StableId
from qa_schemas.enums import ExecutionStatus, FailureClassification
from qa_schemas.evidence import EvidenceReference
from qa_schemas.execution import TestExecution

RESULTS_SCHEMA_VERSION: Literal[1] = 1
"""Version of ``results.json`` (``ExecutionReport``)."""

_OUTCOMES = {ExecutionStatus.PASSED, ExecutionStatus.FAILED, ExecutionStatus.ERROR}


class Failure(SchemaModel):
    classification: FailureClassification
    message: str
    step_index: NonNegativeInt | None = None
    """Index of the step that failed; None when the failure is outside a step."""
    error_type: str | None = None
    """Exception type, e.g. ``TimeoutError``; useful to tell platform bugs apart."""


class StepResult(SchemaModel):
    index: NonNegativeInt
    keyword: str
    text: str
    line: PositiveInt | None = None
    action: StableId | None = None
    status: ExecutionStatus
    duration_ms: NonNegativeInt

    @model_validator(mode="after")
    def _is_outcome(self) -> Self:
        if self.status not in _OUTCOMES:
            raise ValueError(f"a step result must be passed, failed or error, not {self.status}")
        return self


class TestResult(SchemaModel):
    """Result of one test case."""

    __test__ = False  # not a pytest test class despite the name

    test_case_id: StableId
    name: str
    status: ExecutionStatus
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    duration_ms: NonNegativeInt = 0
    steps: tuple[StepResult, ...] = ()
    """Executed steps only; steps after a failure are not run."""
    steps_total: NonNegativeInt
    failure: Failure | None = None
    evidence: tuple[EvidenceReference, ...] = ()
    notes: tuple[str, ...] = ()
    """Secondary problems that did not change the outcome (e.g. evidence collection)."""

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not self.status.is_terminal:
            raise ValueError(f"a test result must be final, not {self.status}")
        needs_failure = self.status in (ExecutionStatus.FAILED, ExecutionStatus.ERROR)
        if needs_failure and self.failure is None:
            raise ValueError(f"a {self.status} result needs a failure")
        if self.status is ExecutionStatus.PASSED and self.failure is not None:
            raise ValueError("a passed result cannot have a failure")
        if len(self.steps) > self.steps_total:
            raise ValueError("more step results than steps")
        return self


class ExecutionReport(SchemaModel):
    """Everything an execution produced; stored as ``results.json``."""

    schema_version: Literal[1] = RESULTS_SCHEMA_VERSION
    """Absent in files written before it existed; they read as version 1."""
    execution: TestExecution
    results: tuple[TestResult, ...] = ()
    failure: Failure | None = None
    """Problem that affected the whole execution (e.g. an adapter could not start)."""
    cleanup_errors: tuple[str, ...] = ()
    """Cleanup problems; recorded separately so they never hide a test outcome."""
