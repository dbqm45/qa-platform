"""Project-level domain models: Project, Repository, Environment (TASK-006)."""

from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, PositiveFloat, model_validator

from qa_schemas.base import Identifier, NonEmptyStr, SafeHttpUrl, SchemaModel


def _duplicates(names: Iterable[str]) -> list[str]:
    return sorted(name for name, count in Counter(names).items() if count > 1)


class Repository(SchemaModel):
    """A source repository of the application under test. The platform only reads it."""

    name: Identifier
    path: Path | None = None
    """Local checkout location."""
    url: SafeHttpUrl | None = None
    """Remote location, e.g. the hosting page of the repository."""

    @model_validator(mode="after")
    def _requires_location(self) -> Self:
        if self.path is None and self.url is None:
            raise ValueError("repository needs at least one of 'path' or 'url'")
        return self


class Environment(SchemaModel):
    """A deployment of the application under test that tests can target."""

    name: Identifier
    base_url: SafeHttpUrl | None = None
    """Entry point for browser tests."""
    services: dict[Identifier, SafeHttpUrl] = Field(default_factory=dict)
    """Named service endpoints, e.g. ``{"api": "http://localhost:8000"}``."""
    timeout_seconds: Annotated[PositiveFloat, Field(le=3600)] = 30.0
    """Default timeout for operations against this environment."""


class Project(SchemaModel):
    """A system under test, with its repositories and target environments."""

    id: Identifier
    name: NonEmptyStr
    repositories: tuple[Repository, ...] = ()
    environments: tuple[Environment, ...] = ()
    default_environment: Identifier | None = None
    scenario_dir: Path = Path("scenarios")
    """Directory with scenario files, relative to the project root."""

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        if dup := _duplicates(r.name for r in self.repositories):
            raise ValueError(f"duplicate repository names: {dup}")
        if dup := _duplicates(e.name for e in self.environments):
            raise ValueError(f"duplicate environment names: {dup}")
        if (
            self.default_environment is not None
            and self.environment(self.default_environment) is None
        ):
            known = [e.name for e in self.environments]
            raise ValueError(
                f"default_environment {self.default_environment!r} is not defined; "
                f"known environments: {known}"
            )
        return self

    def environment(self, name: str) -> Environment | None:
        """Return the environment with the given name, or None."""
        return next((e for e in self.environments if e.name == name), None)
