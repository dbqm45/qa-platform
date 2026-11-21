"""Execution fingerprints: what exactly was tested (TASK-061).

A fingerprint hashes everything that determines an execution's outcome,
part by part, so two executions can be compared and the difference named:

| Part            | Contents                                                         |
|-----------------|------------------------------------------------------------------|
| ``specification`` | the specification without its test cases (source and content hash) |
| test cases      | one hash per test case (steps, parameters), in ``test_cases``    |
| ``plan``        | mode, category, adapters, settings, mocked dependencies          |
| ``environment`` | URLs, services, variables, headers as written, hooks, protection |
| ``adapters``    | the ``adapters:`` section of ``qa.yaml``                         |
| ``mocks``       | the content of the mock files used                               |
| ``contracts``   | the content of the contracts used                                |
| ``options``     | e.g. ``--allow-writes``                                          |
| ``versions``    | Python, the platform and the libraries that execute steps        |
| ``repository <name>`` | the commit of each local repository of the application     |

Secret values never enter it: headers and URLs are hashed as written, with
their ``${NAME}`` references, so a fingerprint is stable across key rotation
and reveals nothing.
"""

import hashlib
import json
import platform
import subprocess
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from qa_schemas.plan import ExecutionPlan
from qa_schemas.project import Environment, Repository
from qa_schemas.results import Fingerprint
from qa_schemas.specification import TestSpecification

VERSIONED_PACKAGES = ("qa-platform", "playwright", "httpx", "jsonschema", "pydantic")
GIT_TIMEOUT_SECONDS = 5
UNKNOWN = "unknown"


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def versions() -> dict[str, str]:
    found = {"python": platform.python_version()}
    for package in VERSIONED_PACKAGES:
        try:
            found[package] = version(package)
        except PackageNotFoundError:
            found[package] = UNKNOWN
    return found


def repository_revisions(root: Path, repositories: tuple[Repository, ...]) -> dict[str, str]:
    """Commit of each repository with a local ``path``; read-only (``git rev-parse``).

    ``unknown`` for a repository without a path, outside git or when git fails;
    a ``+dirty`` suffix when the checkout has uncommitted changes.
    """
    revisions: dict[str, str] = {}
    for repository in repositories:
        if repository.path is None:
            revisions[repository.name] = UNKNOWN
            continue
        path = (root / repository.path).resolve()
        head = _git(path, "rev-parse", "HEAD")
        if head is None:
            revisions[repository.name] = UNKNOWN
            continue
        dirty = _git(path, "status", "--porcelain", "--untracked-files=no")
        revisions[repository.name] = head + ("+dirty" if dirty else "")
    return revisions


def _git(path: Path, *args: str) -> str | None:
    if not path.is_dir():
        return None
    try:
        result = subprocess.run(
            # --no-optional-locks: git status must not refresh the index, a write
            ["git", "--no-optional-locks", "-C", str(path), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def compute(
    specification: TestSpecification,
    plan: ExecutionPlan,
    environment: Environment,
    *,
    adapter_config: Mapping[str, Any],
    mocks: Mapping[str, Any],
    contracts: Mapping[str, Any],
    options: Mapping[str, Any],
    repositories: Mapping[str, str],
) -> Fingerprint:
    spec = specification.model_dump(mode="json")
    test_cases = {case["id"]: _digest(case) for case in spec.pop("test_cases")}
    plan_data = plan.model_dump(mode="json")
    plan_data.pop("specification_id", None)  # covered by the specification part
    parts = {
        "specification": _digest(spec),
        "plan": _digest(plan_data),
        "environment": _digest(environment.model_dump(mode="json")),
        "adapters": _digest(dict(adapter_config)),
        "mocks": _digest(dict(mocks)),
        "contracts": _digest(dict(contracts)),
        "options": _digest(dict(options)),
        "versions": _digest(versions()),
    }
    parts.update({f"repository {name}": _digest(rev) for name, rev in repositories.items()})
    value = _digest({"parts": parts, "test_cases": test_cases})
    return Fingerprint(
        value=f"sha256:{value}",
        parts=parts,
        test_cases=test_cases,
        versions=versions(),
        repositories=dict(repositories),
    )


def differences(a: Fingerprint, b: Fingerprint) -> list[str]:
    """What differs between two fingerprints, in readable lines (empty: the same inputs).

    Test cases are compared where both have them; cases only one side ran are
    listed, as ``qa rerun --failed-only`` runs a subset on purpose.
    """
    lines: list[str] = []
    for part in sorted(set(a.parts) | set(b.parts)):
        if a.parts.get(part) == b.parts.get(part):
            continue
        if part.startswith("repository "):
            name = part.removeprefix("repository ")
            lines.append(
                f"{part}: {_short(a.repositories.get(name))} -> {_short(b.repositories.get(name))}"
            )
        elif part == "versions":
            changed = [
                f"{k} {a.versions.get(k, '-')} -> {b.versions.get(k, '-')}"
                for k in sorted(set(a.versions) | set(b.versions))
                if a.versions.get(k) != b.versions.get(k)
            ]
            lines.append(f"versions: {', '.join(changed) or 'changed'}")
        else:
            lines.append(part)
    for case in sorted(set(a.test_cases) & set(b.test_cases)):
        if a.test_cases[case] != b.test_cases[case]:
            lines.append(f"test case {case}")
    return lines


def _short(revision: str | None) -> str:
    if revision is None:
        return "-"
    head, _, dirty = revision.partition("+")
    return head[:12] + (f"+{dirty}" if dirty else "")
