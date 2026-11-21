"""Build the CI summary of a ``qa test`` run (TASK-060)."""

from collections import Counter
from pathlib import Path

from qa_execution.service import SpecificationRun, TestRun
from qa_schemas.enums import ExecutionStatus
from qa_schemas.results import ExecutionReport, Failure
from qa_schemas.summary import RunSummary, SpecificationSummary, SummaryFailure, SummaryIssue

NOT_EXECUTED = "not_executed"


def summarize(run: TestRun, root: Path) -> RunSummary:
    """Summary of ``run``; paths become relative to the project ``root``."""
    specifications = tuple(_specification(spec_run, root.resolve()) for spec_run in run.runs)
    counts = Counter(s.status.value if s.status else NOT_EXECUTED for s in specifications)
    return RunSummary(
        project=run.project,
        scenario=str(run.scenario),
        environment=run.environment,
        ok=run.ok,
        counts=dict(sorted(counts.items())),
        errors=tuple(
            SummaryIssue(location=i.location(), code=i.code, message=i.message) for i in run.errors
        ),
        specifications=specifications,
    )


def _specification(spec_run: SpecificationRun, root: Path) -> SpecificationSummary:
    compiled = spec_run.compiled
    spec = compiled.specification
    base = SpecificationSummary(
        id=spec.id,
        source=f"{spec.source.path}:{spec.source.line}",
        compilation=compiled.status,
        status=None,
        problem=spec_run.problem,
    )
    report = spec_run.report
    if report is None:
        return base
    execution = report.execution
    duration = None
    if execution.started_at is not None and execution.finished_at is not None:
        duration = int((execution.finished_at - execution.started_at).total_seconds() * 1000)
    return base.model_copy(
        update={
            "status": execution.status,
            "execution_id": execution.id,
            "duration_ms": duration,
            "results": _relative(spec_run.results_path, root),
            "report": _relative(spec_run.report_path, root),
            "failures": _failures(report),
        }
    )


def _failures(report: ExecutionReport) -> tuple[SummaryFailure, ...]:
    failures = [
        _failure(result.test_case_id, result.status, result.failure)
        for result in report.results
        if result.failure is not None
    ]
    if report.failure is not None and not _same_as_every_case(report):
        failures.append(_failure(None, report.execution.status, report.failure))
    return tuple(failures)


def _same_as_every_case(report: ExecutionReport) -> bool:
    """The execution-level failure is what every failed case already reports.

    Same rule as the console output of ``qa test``, so both show it once.
    """
    assert report.failure is not None
    shown = {r.failure.message for r in report.results if r.failure is not None}
    return bool(report.results) and shown == {report.failure.message}


def _failure(case: str | None, status: ExecutionStatus, failure: Failure) -> SummaryFailure:
    return SummaryFailure(
        test_case_id=case,
        status=status,
        classification=failure.classification,
        message=failure.message,
        step=failure.step_index + 1 if failure.step_index is not None else None,
    )


def _relative(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    return resolved.relative_to(root).as_posix() if resolved.is_relative_to(root) else str(path)
