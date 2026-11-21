"""Execution history: list past executions and show one (TASK-063, TASK-058).

Metadata comes from ``.qa/qa.db``; details from the files next to the
evidence (``results.json``, ``report.html``, ``execution.log``).
"""

from dataclasses import dataclass
from pathlib import Path

from qa_core.config import load_config
from qa_core.init import PLATFORM_DIRNAME
from qa_core.storage import DATABASE_FILENAME, ExecutionRepository, open_database
from qa_execution.log import LOG_FILENAME
from qa_execution.service import RESULTS_FILENAME, executions_dir
from qa_reporting.html import REPORT_FILENAME
from qa_schemas.execution import TestExecution
from qa_schemas.results import ExecutionReport

_SEARCH_LIMIT = 10_000


class ExecutionNotFoundError(LookupError):
    """No execution, or more than one, matches the given id."""


@dataclass(frozen=True)
class ExecutionDetails:
    execution: TestExecution
    report: ExecutionReport | None
    """None when ``results.json`` is missing (e.g. an interrupted execution)."""
    directory: Path
    results_path: Path | None
    report_path: Path | None
    log_path: Path | None


def list_executions(config_path: Path, limit: int = 20) -> list[TestExecution]:
    """Most recent first."""
    config = load_config(config_path)
    with open_database(_database(config_path)) as db:
        return ExecutionRepository(db).list_for_project(config.project.id, limit=limit)


def show_execution(config_path: Path, execution_id: str) -> ExecutionDetails:
    """Details of one execution; a unique prefix of the id is enough."""
    config = load_config(config_path)
    with open_database(_database(config_path)) as db:
        repo = ExecutionRepository(db)
        execution = repo.get(execution_id)
        if execution is None:
            candidates = [
                e
                for e in repo.list_for_project(config.project.id, limit=_SEARCH_LIMIT)
                if e.id.startswith(execution_id)
            ]
            if not candidates:
                raise ExecutionNotFoundError(f"no execution matches {execution_id!r}")
            if len(candidates) > 1:
                ids = ", ".join(e.id for e in candidates[:5])
                raise ExecutionNotFoundError(
                    f"{execution_id!r} matches {len(candidates)} executions ({ids}"
                    f"{', ...' if len(candidates) > 5 else ''}); give more of the id"
                )
            execution = candidates[0]

    directory = executions_dir(config_path) / execution.id

    def existing(name: str) -> Path | None:
        path = directory / name
        return path if path.is_file() else None

    results_path = existing(RESULTS_FILENAME)
    report = (
        ExecutionReport.model_validate_json(results_path.read_text(encoding="utf-8"))
        if results_path
        else None
    )
    return ExecutionDetails(
        execution=execution,
        report=report,
        directory=directory,
        results_path=results_path,
        report_path=existing(REPORT_FILENAME),
        log_path=existing(LOG_FILENAME),
    )


def _database(config_path: Path) -> Path:
    return config_path.resolve().parent / PLATFORM_DIRNAME / DATABASE_FILENAME
