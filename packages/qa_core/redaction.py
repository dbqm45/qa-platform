"""Secret references and redaction (TASK-066).

Secrets are written in scenarios as references, ``${NAME}``, and resolved from
environment variables only when a step runs. Their values never reach
specifications, results, reports or evidence: a :class:`Redactor` collects
every secret value of an execution and replaces it with ``********``.

Independent of known values, two patterns are always masked:

- URL query / form parameters with sensitive names (``password=...``,
  ``token=...``, ``api_key=...``, ...);
- JSON string fields with such names (``"password": "..."``, ``"token": "..."``);
- ``Authorization`` credentials (``Bearer ...``, ``Basic ...``).
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from qa_schemas.base import REFERENCE_PATTERN, SENSITIVE_NAMES

MASK = "********"

SECRET_REFERENCE = re.compile(REFERENCE_PATTERN)
"""``${NAME}`` -- an environment variable holding a secret."""

MIN_SECRET_LENGTH = 4
"""Shorter values are not masked as substrings (they would hide unrelated text);
the patterns below still mask them in parameters and headers."""

_SENSITIVE_PARAMETER = re.compile(rf"(?i)\b({SENSITIVE_NAMES})=([^&\s'\"#]*)")
_SENSITIVE_JSON_FIELD = re.compile(rf'(?i)("(?:{SENSITIVE_NAMES})"\s*:\s*)"((?:[^"\\]|\\.)*)"')
_AUTHORIZATION = re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{4,}")


class MissingSecretError(LookupError):
    """A ``${NAME}`` reference has no value."""

    def __init__(self, name: str) -> None:
        super().__init__(f"secret {name} is not set (export it as an environment variable)")
        self.name = name


class Redactor:
    """Masks known secret values and sensitive patterns in text."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets: set[str] = set()
        for secret in secrets:
            self.add(secret)

    def add(self, value: str) -> None:
        if len(value) >= MIN_SECRET_LENGTH:
            self._secrets.add(value)

    def redact(self, text: str) -> str:
        # Longest first, so a secret containing another one is masked as a whole.
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, MASK)
        text = _SENSITIVE_PARAMETER.sub(
            lambda m: f"{m.group(1)}={MASK}" if m.group(2) else m[0], text
        )
        text = _SENSITIVE_JSON_FIELD.sub(
            lambda m: f'{m.group(1)}"{MASK}"' if m.group(2) else m[0], text
        )
        return _AUTHORIZATION.sub(lambda m: f"{m.group(1)} {MASK}", text)

    def redact_data(self, data: Any) -> Any:
        """Redact every string inside JSON-like data (dicts, lists, strings)."""
        if isinstance(data, str):
            return self.redact(data)
        if isinstance(data, Mapping):
            return {key: self.redact_data(value) for key, value in data.items()}
        if isinstance(data, list | tuple):
            return [self.redact_data(value) for value in data]
        return data


def resolve_references(
    text: str,
    environment: Mapping[str, str],
    redactor: Redactor,
    plain: Mapping[str, str] | None = None,
) -> str:
    """Replace ``${NAME}`` with its value.

    ``plain`` (an environment's ``variables`` from ``qa.yaml``) is looked up
    first and is not secret. Otherwise the value comes from ``environment``
    (the process environment), is treated as a secret and registered with the
    redactor.
    """
    plain = plain or {}

    def value_of(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in plain:
            return plain[name]
        if name not in environment:
            raise MissingSecretError(name)
        value = environment[name]
        redactor.add(value)
        return value

    return SECRET_REFERENCE.sub(value_of, text)
