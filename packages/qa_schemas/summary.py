"""Summary of one ``qa test`` run for CI/CD (TASK-060).

One ``qa test`` compiles a scenario file into several specifications and runs
each as its own execution. The summary lists them in one versioned document,
with paths relative to the project root, so a pipeline can decide, report and
upload artifacts without reading every ``results.json``.
"""

from typing import Literal

from pydantic import NonNegativeInt, PositiveInt

from qa_schemas.base import Identifier, SchemaModel, StableId
from qa_schemas.enums import CompilationStatus, ExecutionStatus, FailureClassification

SUMMARY_SCHEMA_VERSION: Literal[1] = 1


class SummaryIssue(SchemaModel):
    """A validation error that blocked the scenario file."""

    location: str
    code: str
    message: str


class SummaryFailure(SchemaModel):
    test_case_id: StableId | None
    """None for a failure of the whole execution (e.g. an adapter could not start)."""
    status: ExecutionStatus
    classification: FailureClassification
    message: str
    step: PositiveInt | None = None
    """1-based number of the failed step, as shown in reports."""


class SpecificationSummary(SchemaModel):
    id: StableId
    source: str
    """``path:line`` of the scenario."""
    compilation: CompilationStatus
    status: ExecutionStatus | None
    """None when the specification was not executed (see ``problem``)."""
    problem: str | None = None
    execution_id: str | None = None
    duration_ms: NonNegativeInt | None = None
    results: str | None = None
    """``results.json``, relative to the project root."""
    report: str | None = None
    """``report.html``, relative to the project root."""
    failures: tuple[SummaryFailure, ...] = ()


class RunSummary(SchemaModel):
    schema_version: Literal[1] = SUMMARY_SCHEMA_VERSION
    project: Identifier
    scenario: str
    environment: str
    ok: bool
    """True only if the file was valid and every specification ran and passed."""
    counts: dict[str, NonNegativeInt]
    """Specifications per outcome: execution statuses and ``not_executed``."""
    errors: tuple[SummaryIssue, ...] = ()
    specifications: tuple[SpecificationSummary, ...] = ()
