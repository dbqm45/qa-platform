"""Shared building blocks for all platform schemas."""

from collections import Counter
from collections.abc import Iterable
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, HttpUrl, StringConstraints


class SchemaModel(BaseModel):
    """Base class for every platform schema.

    - Unknown fields are rejected, so typos in configuration fail loudly.
    - Instances are immutable; use ``model_copy(update=...)`` to derive new ones.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
STABLE_ID_PATTERN = r"^[a-z0-9][a-z0-9_.:-]{0,199}$"

PATTERN_DESCRIPTIONS: dict[str, str] = {
    IDENTIFIER_PATTERN: (
        "must start with a lowercase letter and contain only lowercase letters, "
        "digits, '-' or '_' (max 64 characters)"
    ),
    STABLE_ID_PATTERN: (
        "must start with a lowercase letter or digit and contain only lowercase "
        "letters, digits, '.', ':', '-' or '_' (max 200 characters)"
    ),
}
"""Human-readable explanations of the patterns above, used in error messages."""

Identifier = Annotated[str, StringConstraints(pattern=IDENTIFIER_PATTERN)]
"""Stable machine identifier: lowercase letter, then letters, digits, ``-`` or ``_``; max 64."""

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
"""Human-readable label; surrounding whitespace is stripped."""


def _reject_credentials(url: HttpUrl) -> HttpUrl:
    if url.username or url.password:
        raise ValueError("URL must not contain credentials; reference secrets separately")
    return url


SafeHttpUrl = Annotated[HttpUrl, AfterValidator(_reject_credentials)]
"""HTTP(S) URL that cannot carry embedded credentials (``https://user:token@host``)."""

StableId = Annotated[str, StringConstraints(pattern=STABLE_ID_PATTERN)]
"""Deterministic identifier of generated artifacts, e.g. ``login.successful-login``."""


def find_duplicates(values: Iterable[str]) -> list[str]:
    """Return the values that occur more than once, sorted."""
    return sorted(value for value, count in Counter(values).items() if count > 1)
