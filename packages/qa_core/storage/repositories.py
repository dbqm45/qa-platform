"""Repositories: the only place that translates between models and SQL rows."""

import sqlite3
from datetime import UTC, datetime

from pydantic import AwareDatetime

from qa_core.storage.database import StorageError
from qa_schemas.base import Identifier, NonEmptyStr, SchemaModel
from qa_schemas.execution import TestExecution
from qa_schemas.project import Project


class ProjectRecord(SchemaModel):
    """A project as registered in local storage."""

    id: Identifier
    name: NonEmptyStr
    created_at: AwareDatetime
    updated_at: AwareDatetime


def _to_db(value: datetime | None) -> str | None:
    """Store timestamps as fixed-width UTC ISO 8601, so text order equals time order."""
    return None if value is None else value.astimezone(UTC).isoformat(timespec="microseconds")


def _now() -> datetime:
    return datetime.now(UTC)


_PROJECT_FIELDS = ("id", "name", "created_at", "updated_at")
_PROJECT_COLUMNS = ", ".join(_PROJECT_FIELDS)


class ProjectRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def upsert(self, project: Project, *, now: datetime | None = None) -> ProjectRecord:
        """Register the project, or refresh its name if already registered."""
        timestamp = _to_db(now or _now())
        with self._db:
            self._db.execute(
                """
                INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE
                SET name = excluded.name, updated_at = excluded.updated_at
                WHERE projects.name IS NOT excluded.name
                """,
                (project.id, project.name, timestamp, timestamp),
            )
        record = self.get(project.id)
        if record is None:
            raise StorageError(f"project {project.id!r} was not stored")
        return record

    def get(self, project_id: str) -> ProjectRecord | None:
        row = self._db.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return None if row is None else self._record(row)

    def list(self) -> list[ProjectRecord]:
        rows = self._db.execute(f"SELECT {_PROJECT_COLUMNS} FROM projects ORDER BY id").fetchall()
        return [self._record(row) for row in rows]

    @staticmethod
    def _record(row: tuple[object, ...]) -> ProjectRecord:
        return ProjectRecord.model_validate(dict(zip(_PROJECT_FIELDS, row, strict=True)))


_EXECUTION_FIELDS = tuple(TestExecution.model_fields)
_EXECUTION_COLUMNS = ", ".join(_EXECUTION_FIELDS)


class ExecutionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def add(self, execution: TestExecution) -> None:
        try:
            with self._db:
                self._db.execute(
                    f"INSERT INTO executions ({_EXECUTION_COLUMNS}) "
                    f"VALUES ({', '.join('?' * len(_EXECUTION_FIELDS))})",
                    (
                        execution.id,
                        execution.project_id,
                        execution.specification_id,
                        execution.plan_id,
                        execution.mode.value,
                        execution.category.value,
                        execution.environment,
                        execution.status.value,
                        _to_db(execution.created_at),
                        _to_db(execution.started_at),
                        _to_db(execution.finished_at),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if self.get(execution.id) is not None:
                raise StorageError(f"execution {execution.id!r} already exists") from None
            raise StorageError(f"cannot store execution {execution.id!r}: {exc}") from None

    def update(self, execution: TestExecution) -> None:
        """Persist status and timestamps. Identity fields never change."""
        with self._db:
            cursor = self._db.execute(
                "UPDATE executions SET status = ?, started_at = ?, finished_at = ? WHERE id = ?",
                (
                    execution.status.value,
                    _to_db(execution.started_at),
                    _to_db(execution.finished_at),
                    execution.id,
                ),
            )
        if cursor.rowcount == 0:
            raise StorageError(f"execution {execution.id!r} does not exist")

    def get(self, execution_id: str) -> TestExecution | None:
        row = self._db.execute(
            f"SELECT {_EXECUTION_COLUMNS} FROM executions WHERE id = ?", (execution_id,)
        ).fetchone()
        return None if row is None else self._execution(row)

    def list_for_project(self, project_id: str, *, limit: int = 50) -> list[TestExecution]:
        """Most recent first."""
        rows = self._db.execute(
            f"SELECT {_EXECUTION_COLUMNS} FROM executions WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [self._execution(row) for row in rows]

    @staticmethod
    def _execution(row: tuple[object, ...]) -> TestExecution:
        return TestExecution.model_validate(dict(zip(_EXECUTION_FIELDS, row, strict=True)))
