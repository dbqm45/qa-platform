"""Test Specification: a normalized, runner-independent description of what to verify (TASK-008).

A specification says *what* a test checks, never *how* or *where* it runs:
it contains no URLs, selectors, adapters or environment names. Those belong to
the Execution Plan (``qa_schemas.plan``).
"""

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import Field, PositiveInt, StringConstraints, model_validator

from qa_schemas.base import Identifier, NonEmptyStr, SchemaModel, StableId, find_duplicates
from qa_schemas.enums import StepKind

SPECIFICATION_SCHEMA_VERSION: Literal[1] = 1
"""Bump on any incompatible change to the specification format."""

ContentHash = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
"""Hash of the source content, e.g. ``sha256:9f86d0...``."""

StepText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

Tag = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")]
"""Tag without the leading ``@``, e.g. ``smoke`` or ``jira:SHOP-12``."""


class ScenarioSource(SchemaModel):
    """Where the specification came from (traceability, TASK-021)."""

    path: PurePosixPath
    """Source file path relative to the project root, with forward slashes."""
    feature: NonEmptyStr
    scenario: NonEmptyStr
    line: PositiveInt | None = None
    content_hash: ContentHash

    @model_validator(mode="after")
    def _path_is_relative(self) -> Self:
        if self.path.is_absolute() or ".." in self.path.parts:
            raise ValueError("source path must be relative to the project root")
        return self


class Step(SchemaModel):
    """A single step as written in the source. Interpretation happens in compilation."""

    kind: StepKind
    keyword: NonEmptyStr
    """Original keyword, e.g. ``Given`` or ``And``; kept for traceability."""
    text: StepText
    """Step text without the keyword."""
    line: PositiveInt | None = None


class TestCase(SchemaModel):
    """One executable case. A Scenario Outline yields one case per Examples row."""

    __test__ = False  # not a pytest test class despite the name

    id: StableId
    name: NonEmptyStr
    steps: Annotated[tuple[Step, ...], Field(min_length=1)]
    """All steps in source order, including Background steps."""
    parameters: dict[str, str] = Field(default_factory=dict)
    """Examples row values for Scenario Outline cases; empty otherwise."""

    @property
    def preconditions(self) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.kind is StepKind.PRECONDITION)

    @property
    def actions(self) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.kind is StepKind.ACTION)

    @property
    def expected_results(self) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.kind is StepKind.EXPECTATION)


class SpecificationMetadata(SchemaModel):
    tags: tuple[Tag, ...] = ()
    description: str | None = None

    @model_validator(mode="after")
    def _unique_tags(self) -> Self:
        if dup := find_duplicates(self.tags):
            raise ValueError(f"duplicate tags: {dup}")
        return self


class TestSpecification(SchemaModel):
    """What a scenario verifies, independent of any runner or environment."""

    __test__ = False

    schema_version: Literal[1] = SPECIFICATION_SCHEMA_VERSION
    id: StableId
    source: ScenarioSource
    test_cases: Annotated[tuple[TestCase, ...], Field(min_length=1)]
    required_capabilities: tuple[Identifier, ...] = ()
    """Capabilities an adapter must provide, e.g. ``browser`` or ``http``."""
    metadata: SpecificationMetadata = SpecificationMetadata()

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        if dup := find_duplicates(c.id for c in self.test_cases):
            raise ValueError(f"duplicate test case ids: {dup}")
        if dup := find_duplicates(self.required_capabilities):
            raise ValueError(f"duplicate required capabilities: {dup}")
        return self
