"""Scenario source documents (TASK-017).

A ``ScenarioDocument`` is raw, unparsed input as delivered by a scenario
source. Parsing it into scenarios happens in TASK-019.
"""

import hashlib
from pathlib import PurePosixPath
from typing import Self

from pydantic import model_validator

from qa_schemas.base import ContentHash, SchemaModel
from qa_schemas.enums import ScenarioFormat


def content_hash(data: bytes) -> str:
    """Hash used for traceability and change detection: ``sha256:<hex>``."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ScenarioDocument(SchemaModel):
    path: PurePosixPath
    """Location relative to the project root, with forward slashes."""
    format: ScenarioFormat
    content: str
    content_hash: ContentHash
    """Hash of the raw bytes as stored on disk."""

    @model_validator(mode="after")
    def _path_is_relative(self) -> Self:
        if self.path.is_absolute() or ".." in self.path.parts:
            raise ValueError("document path must be relative to the project root")
        return self
