"""References to evidence files collected during execution (TASK-029).

The full result schema follows in TASK-057; evidence collection in TASK-044/048.
"""

from pathlib import PurePosixPath
from typing import Self

from pydantic import model_validator

from qa_schemas.base import Identifier, SchemaModel


class EvidenceReference(SchemaModel):
    kind: Identifier
    """What the file is, e.g. ``screenshot``, ``trace``, ``console-log``, ``http-exchange``."""
    path: PurePosixPath
    """Relative to the execution's evidence directory."""
    description: str = ""

    @model_validator(mode="after")
    def _path_is_relative(self) -> Self:
        if self.path.is_absolute() or ".." in self.path.parts:
            raise ValueError("evidence path must be relative to the evidence directory")
        return self
