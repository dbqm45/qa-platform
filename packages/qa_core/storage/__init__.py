"""Local persistence (SQLite). All SQL lives in this package (TASK-016)."""

from qa_core.storage.database import DATABASE_FILENAME, StorageError, open_database
from qa_core.storage.repositories import ExecutionRepository, ProjectRecord, ProjectRepository

__all__ = [
    "DATABASE_FILENAME",
    "ExecutionRepository",
    "ProjectRecord",
    "ProjectRepository",
    "StorageError",
    "open_database",
]
