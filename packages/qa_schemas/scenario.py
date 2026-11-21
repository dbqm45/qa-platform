"""Scenario documents and parsed scenarios (TASK-017, TASK-019).

A ``ScenarioDocument`` is raw input as delivered by a scenario source; a
``ParseResult`` is what a parser makes of it.
"""

import hashlib
from pathlib import PurePosixPath
from typing import Self

from pydantic import PositiveInt, model_validator

from qa_schemas.base import ContentHash, SchemaModel
from qa_schemas.enums import IssueSeverity, ScenarioFormat, StepKeywordType


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


# --- Parsed scenarios (TASK-019) ---------------------------------------------
#
# These models mirror the source faithfully and are deliberately permissive:
# empty names, scenarios without steps or Examples without rows are
# representable, so validation (TASK-020) can report them with locations.


class DocString(SchemaModel):
    content: str
    media_type: str | None = None


class ScenarioStep(SchemaModel):
    keyword: str
    """Keyword as written, without trailing space, e.g. ``And`` or ``Zakładając``."""
    keyword_type: StepKeywordType
    text: str
    line: PositiveInt
    data_table: tuple[tuple[str, ...], ...] | None = None
    doc_string: DocString | None = None


class ExamplesRow(SchemaModel):
    line: PositiveInt
    values: tuple[str, ...]


class Examples(SchemaModel):
    name: str
    line: PositiveInt
    tags: tuple[str, ...] = ()
    header: tuple[str, ...] | None = None
    """None when the Examples section has no table at all."""
    rows: tuple[ExamplesRow, ...] = ()


class RuleReference(SchemaModel):
    """The ``Rule`` a scenario belongs to."""

    name: str
    line: PositiveInt
    tags: tuple[str, ...] = ()


class Scenario(SchemaModel):
    """One Scenario / Scenario Outline with everything needed to run it."""

    name: str
    keyword: str
    """``Scenario``, ``Example``, ``Scenario Outline``... in the file's language."""
    line: PositiveInt
    description: str = ""
    tags: tuple[str, ...] = ()
    """Tags written on the scenario itself, without ``@``."""
    rule: RuleReference | None = None
    background: tuple[ScenarioStep, ...] = ()
    """Feature Background steps, then Rule Background steps."""
    steps: tuple[ScenarioStep, ...] = ()
    is_outline: bool = False
    """Declared with the Scenario Outline / Template keyword of the file's language."""
    examples: tuple[Examples, ...] = ()


class ParsedFeature(SchemaModel):
    path: PurePosixPath
    content_hash: ContentHash
    language: str
    name: str
    keyword: str
    line: PositiveInt
    description: str = ""
    tags: tuple[str, ...] = ()
    scenarios: tuple[Scenario, ...] = ()
    """In source order, including scenarios inside Rules."""


class ParseIssue(SchemaModel):
    """A syntax error, with its location in the source file."""

    path: PurePosixPath
    line: PositiveInt | None = None
    column: PositiveInt | None = None
    message: str


class ParseResult(SchemaModel):
    document: PurePosixPath
    feature: ParsedFeature | None = None
    """None when the file has errors or contains no Feature."""
    issues: tuple[ParseIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues


# --- Validation (TASK-020) ---------------------------------------------------


class ValidationIssue(SchemaModel):
    path: PurePosixPath
    line: PositiveInt | None = None
    column: PositiveInt | None = None
    severity: IssueSeverity
    code: str
    """Stable identifier of the rule, e.g. ``scenario.missing-name``."""
    message: str

    def location(self) -> str:
        """``path:line:column`` as far as known, for display."""
        parts = [str(self.path)] + [str(n) for n in (self.line, self.column) if n is not None]
        return ":".join(parts)
