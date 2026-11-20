"""SQLite persistence against a real database file (TASK-016)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from qa_core.storage import (
    ExecutionRepository,
    ProjectRepository,
    StorageError,
    open_database,
)
from qa_core.storage.database import migrate, schema_version
from qa_core.storage.migrations import SCHEMA_VERSION
from qa_schemas.enums import ExecutionStatus
from qa_schemas.execution import TestExecution
from qa_schemas.project import Project

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
PROJECT = Project(id="shop", name="Shop")


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "qa.db"


def _execution(execution_id: str = "exec-1", **overrides: Any) -> TestExecution:
    data: dict[str, Any] = {
        "id": execution_id,
        "project_id": "shop",
        "specification_id": "login.successful-login",
        "plan_id": "login.successful-login.fe.local",
        "mode": "fe",
        "category": "functional",
        "environment": "local",
        "created_at": T0,
    }
    return TestExecution.model_validate(data | overrides)


# --- Database and migrations -------------------------------------------------


def test_new_database_is_created_and_migrated(db_path: Path) -> None:
    with open_database(db_path) as db:
        assert schema_version(db) == SCHEMA_VERSION
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"projects", "executions"} <= tables
    assert db_path.is_file()


def test_migrations_are_applied_only_once(db_path: Path) -> None:
    with open_database(db_path) as db:
        assert migrate(db) == 0


def test_missing_parent_directory(tmp_path: Path) -> None:
    with (
        pytest.raises(StorageError, match="does not exist; run `qa init`"),
        open_database(tmp_path / "missing" / "qa.db"),
    ):
        pass


def test_newer_schema_is_refused(db_path: Path) -> None:
    with sqlite3.connect(db_path) as raw:
        raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(StorageError, match="upgrade qa-platform"), open_database(db_path):
        pass


def test_corrupt_file_is_reported(db_path: Path) -> None:
    db_path.write_bytes(b"this is not a database" * 100)
    with pytest.raises(StorageError, match="unusable"), open_database(db_path):
        pass


def test_failed_migration_is_rolled_back(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from qa_core.storage import database

    broken = ("CREATE TABLE a (x TEXT) STRICT; CREATE TABLE a (x TEXT) STRICT;",)
    monkeypatch.setattr(database, "MIGRATIONS", broken)
    monkeypatch.setattr(database, "SCHEMA_VERSION", 1)

    with pytest.raises(StorageError, match="migration to version 1 failed"), open_database(db_path):
        pass
    with sqlite3.connect(db_path) as raw:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
        assert raw.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0


def test_strict_tables_reject_wrong_types(db_path: Path) -> None:
    with open_database(db_path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO projects VALUES (x'00', 'x', 'a', 'b')")


# --- Projects ----------------------------------------------------------------


def test_project_survives_reopening(db_path: Path) -> None:
    with open_database(db_path) as db:
        ProjectRepository(db).upsert(PROJECT, now=T0)
    with open_database(db_path) as db:
        record = ProjectRepository(db).get("shop")
    assert record is not None
    assert (record.id, record.name, record.created_at) == ("shop", "Shop", T0)


def test_upsert_updates_name_but_keeps_created_at(db_path: Path) -> None:
    later = T0 + timedelta(days=1)
    with open_database(db_path) as db:
        repo = ProjectRepository(db)
        repo.upsert(PROJECT, now=T0)
        unchanged = repo.upsert(PROJECT, now=later)
        renamed = repo.upsert(PROJECT.model_copy(update={"name": "New"}), now=later)
        assert len(repo.list()) == 1

    assert unchanged.updated_at == T0
    assert (renamed.name, renamed.created_at, renamed.updated_at) == ("New", T0, later)


def test_unknown_project(db_path: Path) -> None:
    with open_database(db_path) as db:
        assert ProjectRepository(db).get("nope") is None


# --- Executions --------------------------------------------------------------


def test_execution_survives_reopening(db_path: Path) -> None:
    execution = _execution()
    with open_database(db_path) as db:
        ProjectRepository(db).upsert(PROJECT)
        ExecutionRepository(db).add(execution)
    with open_database(db_path) as db:
        assert ExecutionRepository(db).get("exec-1") == execution


def test_status_update_is_persisted(db_path: Path) -> None:
    execution = _execution()
    finished = execution.model_copy(
        update={
            "status": ExecutionStatus.FAILED,
            "started_at": T0 + timedelta(seconds=1),
            "finished_at": T0 + timedelta(seconds=3),
        }
    )
    with open_database(db_path) as db:
        ProjectRepository(db).upsert(PROJECT)
        repo = ExecutionRepository(db)
        repo.add(execution)
        repo.update(finished)
    with open_database(db_path) as db:
        stored = ExecutionRepository(db).get("exec-1")
    assert stored == finished
    assert stored is not None and stored.status is ExecutionStatus.FAILED


def test_timestamps_in_other_timezones_round_trip(db_path: Path) -> None:
    warsaw = T0.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Warsaw"))
    with open_database(db_path) as db:
        ProjectRepository(db).upsert(PROJECT)
        ExecutionRepository(db).add(_execution(created_at=warsaw))
        stored = ExecutionRepository(db).get("exec-1")
    assert stored is not None
    assert stored.created_at == T0  # same instant, stored as UTC


def test_list_returns_most_recent_first(db_path: Path) -> None:
    with open_database(db_path) as db:
        ProjectRepository(db).upsert(PROJECT)
        repo = ExecutionRepository(db)
        for i, offset in enumerate([0, 0.5, 2, 1]):
            repo.add(_execution(f"exec-{i}", created_at=T0 + timedelta(seconds=offset)))
        ids = [e.id for e in repo.list_for_project("shop")]
        assert [e.id for e in repo.list_for_project("shop", limit=2)] == ids[:2]
        assert repo.list_for_project("other") == []
    assert ids == ["exec-2", "exec-3", "exec-1", "exec-0"]


def test_duplicate_execution_is_rejected(db_path: Path) -> None:
    with open_database(db_path) as db:
        ProjectRepository(db).upsert(PROJECT)
        repo = ExecutionRepository(db)
        repo.add(_execution())
        with pytest.raises(StorageError, match="already exists"):
            repo.add(_execution())


def test_execution_requires_registered_project(db_path: Path) -> None:
    with open_database(db_path) as db, pytest.raises(StorageError, match="cannot store"):
        ExecutionRepository(db).add(_execution(project_id="unregistered"))


def test_update_of_unknown_execution_is_rejected(db_path: Path) -> None:
    with open_database(db_path) as db, pytest.raises(StorageError, match="does not exist"):
        ExecutionRepository(db).update(_execution())
