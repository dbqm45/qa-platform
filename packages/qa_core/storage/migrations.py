"""Database schema migrations.

``MIGRATIONS[n]`` upgrades the schema from version ``n`` to ``n + 1``; the
current version is stored in ``PRAGMA user_version``.

Rules: never edit or reorder a released migration; add a new one instead.
Allowed values in CHECK constraints are written out literally, so a migration
keeps meaning the same thing even if enums change later (a unit test checks
they match the current enums).
"""

MIGRATIONS: tuple[str, ...] = (
    # 1: projects and execution metadata (TASK-016)
    """
    CREATE TABLE projects (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    ) STRICT;

    CREATE TABLE executions (
        id                TEXT PRIMARY KEY,
        project_id        TEXT NOT NULL REFERENCES projects (id),
        specification_id  TEXT NOT NULL,
        plan_id           TEXT NOT NULL,
        mode              TEXT NOT NULL CHECK (mode IN ('fe', 'be', 'full', 'contract')),
        category          TEXT NOT NULL CHECK (category IN (
                              'functional', 'visual', 'accessibility',
                              'performance', 'security', 'contract')),
        environment       TEXT NOT NULL,
        status            TEXT NOT NULL CHECK (status IN (
                              'pending', 'running', 'passed', 'failed', 'error', 'cancelled')),
        created_at        TEXT NOT NULL,
        started_at        TEXT,
        finished_at       TEXT
    ) STRICT;

    CREATE INDEX executions_by_project ON executions (project_id, created_at);
    """,
)

SCHEMA_VERSION = len(MIGRATIONS)
