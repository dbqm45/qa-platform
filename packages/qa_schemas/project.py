"""Project-level domain models: Project, Repository, Environment (TASK-006, TASK-055)."""

import re
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, PositiveFloat, StringConstraints, model_validator

from qa_schemas.base import (
    BUILTIN_VARIABLES,
    REFERENCE_PATTERN,
    SENSITIVE_NAMES,
    VARIABLE_NAME_PATTERN,
    Identifier,
    NonEmptyStr,
    SafeHttpUrl,
    SchemaModel,
    find_duplicates,
)

VariableName = Annotated[str, StringConstraints(pattern=VARIABLE_NAME_PATTERN)]
HeaderName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")]
HookRequest = Annotated[
    str,
    StringConstraints(pattern=r"^(GET|HEAD|OPTIONS|POST|PUT|PATCH|DELETE) (/|https?://)\S*$"),
]
"""``METHOD path`` (or an absolute URL) sent before/after an execution, e.g. ``POST /reset``."""

SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token"}
)
"""Headers whose values are credentials: masked in evidence, never plain in qa.yaml."""

_SENSITIVE = re.compile(rf"(?i)(?:{SENSITIVE_NAMES}|key)")
_REFERENCE = re.compile(REFERENCE_PATTERN)


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
    variables: dict[VariableName, str] = Field(default_factory=dict)
    """Plain values for ``${NAME}`` references in scenarios, e.g. ``{"SHOP_USER": "alice"}``.
    Not secret: they appear in results. Secrets come from environment variables."""
    headers: dict[HeaderName, str] = Field(default_factory=dict)
    """HTTP headers sent with every API request, e.g. ``{"X-Api-Key": "${SHOP_API_KEY}"}``."""
    protected: bool = False
    """Read-only: tests must not change data here unless ``--allow-writes`` is given."""
    setup: tuple[HookRequest, ...] = ()
    """Requests sent before every execution, e.g. to reset test data (TASK-056)."""
    cleanup: tuple[HookRequest, ...] = ()
    """Requests sent after every execution, also when it failed."""
    mocks: dict[Identifier, Path] = Field(default_factory=dict)
    """Service name -> mock file (relative to the project root) that can replace it
    with ``qa test --mock NAME`` (TASK-051)."""

    @model_validator(mode="after")
    def _mocks_replace_services(self) -> Self:
        if unknown := sorted(set(self.mocks) - set(self.services)):
            raise ValueError(
                f"mocks for unknown services: {unknown}; a mock replaces an entry of services"
            )
        return self

    @model_validator(mode="after")
    def _no_plaintext_secrets(self) -> Self:
        for name in self.variables:
            if name in BUILTIN_VARIABLES:
                raise ValueError(
                    f"variable {name} is provided by the platform during an execution "
                    "and cannot be defined in qa.yaml"
                )
            if _SENSITIVE.search(name):
                raise ValueError(
                    f"variable {name} looks like a secret; do not put secrets in qa.yaml, "
                    f"export {name} as an environment variable instead"
                )
        for name, value in self.headers.items():
            if name.lower() in SENSITIVE_HEADERS and not _REFERENCE.search(value):
                raise ValueError(
                    f"header {name} must reference a secret, e.g. ${{SHOP_API_KEY}}, "
                    "instead of containing the value"
                )
        return self


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
        if dup := find_duplicates(r.name for r in self.repositories):
            raise ValueError(f"duplicate repository names: {dup}")
        if dup := find_duplicates(e.name for e in self.environments):
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
