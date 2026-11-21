"""Editing an existing ``qa.yaml`` while preserving comments and layout (TASK-014).

Every edit follows the same steps:

1. the current file must be valid (otherwise nothing is touched);
2. the change is applied to a round-trip YAML document (comments kept);
3. the resulting text is validated with the regular loader;
4. only then is the file replaced, atomically.

Values are written as the user typed them, not in normalized form, so the
file stays readable; the models only validate them.
"""

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from qa_core.config import ConfigError, describe_validation_error, load_config, parse_config
from qa_core.files import write_text_atomically
from qa_schemas.config import ProjectConfig
from qa_schemas.project import Environment, Repository


class ConfigEditError(Exception):
    """The requested change cannot be applied."""


def add_repository(
    config_path: Path, name: str, *, path: str | None = None, url: str | None = None
) -> ProjectConfig:
    """Append a repository to ``project.repositories``."""
    entry = _entry(name=name, path=path, url=url)
    _validate_entry(Repository, entry, "repository")
    current = load_config(config_path)
    if any(r.name == name for r in current.project.repositories):
        raise ConfigEditError(f"repository {name!r} already exists in {config_path}")

    def change(project: CommentedMap) -> None:
        _list(project, "repositories").append(entry)

    return _edit(config_path, change)


def add_environment(
    config_path: Path,
    name: str,
    *,
    base_url: str | None = None,
    services: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
    make_default: bool = False,
    protected: bool = False,
) -> ProjectConfig:
    """Append an environment to ``project.environments``, optionally as the default."""
    entry = _entry(
        name=name,
        base_url=base_url,
        services=CommentedMap(services) if services else None,
        timeout_seconds=_plain_number(timeout_seconds),
        protected=True if protected else None,
    )
    _validate_entry(Environment, entry, "environment")
    current = load_config(config_path)
    if current.project.environment(name) is not None:
        raise ConfigEditError(f"environment {name!r} already exists in {config_path}")

    def change(project: CommentedMap) -> None:
        _list(project, "environments").append(entry)
        if make_default:
            project["default_environment"] = name

    return _edit(config_path, change)


# --- Internals ---------------------------------------------------------------


def _plain_number(value: float | None) -> float | int | None:
    """Write ``60`` rather than ``60.0``."""
    return int(value) if value is not None and value.is_integer() else value


def _entry(**values: Any) -> CommentedMap:
    return CommentedMap((k, v) for k, v in values.items() if v is not None)


def _validate_entry(model: type[Repository | Environment], entry: CommentedMap, kind: str) -> None:
    try:
        model.model_validate(dict(entry))
    except ValidationError as exc:
        problems = "; ".join(describe_validation_error(e) for e in exc.errors())
        raise ConfigEditError(f"invalid {kind}: {problems}") from None


def _list(project: CommentedMap, key: str) -> CommentedSeq:
    value = project.get(key)
    if value is None:  # key not present yet
        value = CommentedSeq()
        project[key] = value
    if not isinstance(value, CommentedSeq):
        raise ConfigEditError(f"project.{key} must be a list")
    return value


def _yaml() -> YAML:
    yaml = YAML()  # round-trip mode: safe, keeps comments, order and quotes
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _edit(config_path: Path, change: Callable[[CommentedMap], None]) -> ProjectConfig:
    yaml = _yaml()
    document = yaml.load(config_path.read_text(encoding="utf-8"))
    change(document["project"])

    buffer = io.StringIO()
    yaml.dump(document, buffer)
    new_text = buffer.getvalue()

    try:
        config = parse_config(new_text, config_path)
    except ConfigError as error:
        raise ConfigEditError(
            "the change would make the configuration invalid: " + "; ".join(error.issues)
        ) from None
    write_text_atomically(config_path, new_text, keep_mode=True)
    return config
