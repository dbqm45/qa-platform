"""Loading and validating ``qa.yaml`` (TASK-012).

All failures are raised as :class:`ConfigError` with a message that names the
file, the field and the problem, so users can fix it without reading a traceback.
"""

import difflib
import re
import types
import typing
from collections.abc import Hashable, Iterator
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from qa_schemas.base import PATTERN_DESCRIPTIONS
from qa_schemas.config import ProjectConfig
from qa_schemas.mock import MockDefinition

CONFIG_FILENAME = "qa.yaml"

_URL_WITH_CREDENTIALS = re.compile(r"://[^/\s]*@")
_MAX_SHOWN_INPUT = 60


class ConfigError(Exception):
    """The configuration file is missing, unreadable or invalid."""

    def __init__(self, path: Path, issues: list[str]) -> None:
        self.path = path
        self.issues = issues
        lines = "\n".join(f"  - {issue}" for issue in issues)
        super().__init__(f"Invalid configuration in {path}:\n{lines}")


def load_config(path: Path) -> ProjectConfig:
    """Read, parse and validate a configuration file."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(path, ["file not found; run `qa init` to create it"]) from None
    except IsADirectoryError:
        raise ConfigError(path, ["is a directory, expected a YAML file"]) from None
    except UnicodeDecodeError:
        raise ConfigError(path, ["file is not valid UTF-8 text"]) from None
    except OSError as exc:
        raise ConfigError(path, [f"cannot read file: {exc.strerror}"]) from None
    return parse_config(text, path)


def parse_config(text: str, path: Path = Path(CONFIG_FILENAME)) -> ProjectConfig:
    """Parse and validate configuration text. ``path`` is used only in messages."""
    try:
        # _StrictLoader extends SafeLoader: no arbitrary Python objects are constructed.
        data = yaml.load(text, Loader=_StrictLoader)
    except yaml.MarkedYAMLError as exc:
        raise ConfigError(path, [_describe_yaml_error(exc)]) from None
    except yaml.YAMLError as exc:
        raise ConfigError(path, [f"invalid YAML: {exc}"]) from None

    if data is None:
        raise ConfigError(path, ["file is empty; expected at least a 'project' section"])
    if not isinstance(data, dict):
        raise ConfigError(path, [f"top level must be a mapping, got {type(data).__name__}"])

    try:
        return ProjectConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            path, [describe_validation_error(error) for error in exc.errors()]
        ) from None


# --- YAML --------------------------------------------------------------------


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate keys instead of keeping the last one."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        seen: set[Hashable] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _describe_yaml_error(exc: yaml.MarkedYAMLError) -> str:
    mark = exc.problem_mark
    where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark else ""
    return f"{where}invalid YAML: {exc.problem or exc}"


# --- Validation errors -------------------------------------------------------


def describe_validation_error(error: ErrorDetails) -> str:
    """One readable line for a Pydantic error: location, message and safe input."""
    location = _format_location(error["loc"])
    if error["type"] == "extra_forbidden":
        message = "unknown field"
        name = error["loc"][-1]
        if isinstance(name, str) and (match := difflib.get_close_matches(name, _known_fields())):
            message += f"; did you mean {match[0]!r}?"
        return f"{location}: {message}"

    message = error["msg"].removeprefix("Value error, ")
    if error["type"] == "string_pattern_mismatch":
        pattern = str(error.get("ctx", {}).get("pattern", ""))
        message = PATTERN_DESCRIPTIONS.get(pattern, message)
    shown = _safe_input(error.get("input"))
    if shown is not None and error["type"] != "missing":
        message += f" (got {shown})"
    return f"{location}: {message}" if location else message


def _format_location(loc: tuple[int | str, ...]) -> str:
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            parts.append(f".{item}" if parts else item)
    return "".join(parts)


def _safe_input(value: object) -> str | None:
    """Render a rejected input for the message, never echoing credentials."""
    if not isinstance(value, str | int | float | bool):
        return None
    text = repr(value)
    if isinstance(value, str) and _URL_WITH_CREDENTIALS.search(value):
        return None
    if len(text) > _MAX_SHOWN_INPUT:
        text = text[: _MAX_SHOWN_INPUT - 3] + "..."
    return text


def _known_fields() -> list[str]:
    return sorted(set(_field_names(ProjectConfig)))


def _field_names(model: type[BaseModel]) -> Iterator[str]:
    for name, field in model.model_fields.items():
        yield name
        for nested in _models_in(field.annotation):
            yield from _field_names(nested)


def _models_in(annotation: object) -> Iterator[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is not None:
        for arg in typing.get_args(annotation):
            yield from _models_in(arg)


# --- Other YAML files --------------------------------------------------------


def load_mock_definition(path: Path) -> MockDefinition:
    """Read and validate a mock file (TASK-051), with the same messages as ``qa.yaml``."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(path, ["mock file not found"]) from None
    except (IsADirectoryError, UnicodeDecodeError, OSError) as exc:
        raise ConfigError(path, [f"cannot read mock file: {exc}"]) from None
    try:
        data = yaml.load(text, Loader=_StrictLoader)
    except yaml.MarkedYAMLError as exc:
        raise ConfigError(path, [_describe_yaml_error(exc)]) from None
    except yaml.YAMLError as exc:
        raise ConfigError(path, [f"invalid YAML: {exc}"]) from None
    if not isinstance(data, dict):
        raise ConfigError(path, ["expected a mapping with 'responses'"])
    try:
        return MockDefinition.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            path, [describe_validation_error(error) for error in exc.errors()]
        ) from None


def load_openapi_document(path: Path) -> dict[str, Any]:
    """Read an OpenAPI document (YAML or JSON) for contract mode (TASK-054)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(path, ["contract file not found"]) from None
    except (IsADirectoryError, UnicodeDecodeError, OSError) as exc:
        raise ConfigError(path, [f"cannot read contract file: {exc}"]) from None
    try:
        data = yaml.load(text, Loader=_StrictLoader)
    except yaml.MarkedYAMLError as exc:
        raise ConfigError(path, [_describe_yaml_error(exc)]) from None
    except yaml.YAMLError as exc:
        raise ConfigError(path, [f"invalid YAML: {exc}"]) from None
    if not isinstance(data, dict):
        raise ConfigError(path, ["expected an OpenAPI document (a mapping)"])
    return data
