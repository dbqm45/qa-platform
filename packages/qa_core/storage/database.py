"""Opening the local SQLite database and applying migrations."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from qa_core.storage.migrations import MIGRATIONS, SCHEMA_VERSION

DATABASE_FILENAME = "qa.db"
"""Stored inside the project's ``.qa/`` directory."""

_MIN_SQLITE = (3, 37, 0)  # STRICT tables


class StorageError(Exception):
    """The local database cannot be opened, migrated or written."""


@contextmanager
def open_database(path: Path) -> Iterator[sqlite3.Connection]:
    """Open (creating if needed) and migrate the database; always closes it.

    The parent directory must already exist; ``qa init`` creates it.
    """
    if sqlite3.sqlite_version_info < _MIN_SQLITE:
        raise StorageError(
            f"SQLite {sqlite3.sqlite_version} is too old; "
            f"{'.'.join(map(str, _MIN_SQLITE))} or newer is required"
        )
    if not path.parent.is_dir():
        raise StorageError(f"directory {path.parent} does not exist; run `qa init`")
    try:
        connection = sqlite3.connect(path)
    except sqlite3.Error as exc:
        raise StorageError(f"cannot open database {path}: {exc}") from None
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        migrate(connection, path)
        yield connection
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"database {path} is unusable: {exc}") from None
    finally:
        connection.close()


def schema_version(connection: sqlite3.Connection) -> int:
    version: int = connection.execute("PRAGMA user_version").fetchone()[0]
    return version


def migrate(connection: sqlite3.Connection, path: Path | str = "database") -> int:
    """Apply pending migrations, each atomically. Returns how many were applied."""
    current = schema_version(connection)
    if current > SCHEMA_VERSION:
        raise StorageError(
            f"{path} has schema version {current}, but this version of the platform "
            f"supports up to {SCHEMA_VERSION}; upgrade qa-platform"
        )
    for version in range(current, SCHEMA_VERSION):
        # executescript() commits any open transaction first, so wrap explicitly:
        # the schema change and the version bump succeed or fail together.
        try:
            connection.executescript(
                f"BEGIN;\n{MIGRATIONS[version]}\nPRAGMA user_version = {version + 1};\nCOMMIT;"
            )
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.rollback()
            raise StorageError(f"migration to version {version + 1} failed: {exc}") from None
    return SCHEMA_VERSION - current
