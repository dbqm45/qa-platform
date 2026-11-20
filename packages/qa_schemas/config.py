"""Schema of the project configuration file, ``qa.yaml`` (TASK-012)."""

from typing import Literal

from qa_schemas.base import SchemaModel
from qa_schemas.project import Project

CONFIG_SCHEMA_VERSION: Literal[1] = 1


class ProjectConfig(SchemaModel):
    """Root of ``qa.yaml``.

    Credentials have no place here: unknown fields are rejected, and URLs with
    embedded credentials fail validation. Secrets are referenced via TASK-055.
    """

    version: Literal[1] = CONFIG_SCHEMA_VERSION
    project: Project
