"""Per-scenario content hashes for change detection (TASK-021).

A file hash says *that* a file changed; a scenario hash says *which* scenario
changed. The hash covers everything that affects what a scenario tests and
ignores what does not: line numbers (moving a scenario is not a change) and
free-text descriptions.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic_core import to_jsonable_python

IGNORED_KEYS = frozenset({"line", "column", "description", "content_hash"})


def scenario_content_hash(fields: Mapping[str, Any]) -> str:
    """Hash of a scenario's meaningful content, given its model fields."""
    canonical = json.dumps(
        _strip(to_jsonable_python(dict(fields))),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in IGNORED_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value
