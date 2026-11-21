"""Parameter types shared by built-in steps; invalid values fail at compile time."""

from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator


def check_url(value: str) -> str:
    if value.startswith("/"):
        return value
    parts = urlsplit(value)
    if parts.scheme in ("http", "https") and parts.netloc:
        if parts.username or parts.password:
            raise ValueError("URL must not contain credentials")
        return value
    raise ValueError("must be an http(s) URL or a path starting with '/'")


Url = Annotated[str, AfterValidator(check_url)]
"""Absolute ``http(s)://`` URL or a path starting with ``/`` (resolved against a base URL)."""
