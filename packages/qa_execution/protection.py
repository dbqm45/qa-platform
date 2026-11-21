"""Read-only guard for protected environments (TASK-056).

An environment with ``protected: true`` is treated as production-like: tests
must not change its data unless ``--allow-writes`` is given. The guard works
in two layers:

1. Before execution, ``data_changing_steps`` finds built-in steps that would
   change data (API requests with a write method, form input in the
   browser); such a specification is not executed at all.
2. During execution, the adapters refuse what slips through (custom steps, a
   click that submits a form): the HTTP adapter does not send write methods,
   the browser blocks non-GET/HEAD requests of the page.

It is a guard against accidents, not a security boundary: a read request can
still have side effects in a badly designed application.
"""

from qa_execution.errors import TestEnvironmentError
from qa_schemas.specification import Step, TestSpecification

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
"""Methods that must not change data (RFC 9110 "safe" methods)."""

DATA_ENTRY_ACTIONS = frozenset({"ui.fill", "ui.select", "ui.check", "ui.uncheck", "ui.submit"})
"""Browser steps that enter data; their purpose is to send it somewhere."""

REQUEST_ACTIONS = frozenset({"api.send", "api.send-json"})

ALLOW_HINT = "use --allow-writes to run it anyway"


class ProtectedEnvironmentError(TestEnvironmentError):
    """Something tried to change data in a protected environment."""


def changes_data(step: Step) -> bool:
    if step.action in DATA_ENTRY_ACTIONS:
        return True
    if step.action in REQUEST_ACTIONS:
        method = str(step.parameters.get("method", "")).upper()
        return method not in SAFE_METHODS
    return False


def data_changing_steps(specification: TestSpecification) -> list[Step]:
    """Distinct source steps that would change data, in order (outline rows repeat them)."""
    found: dict[tuple[int | None, str], Step] = {}
    for case in specification.test_cases:
        for step in case.steps:
            if changes_data(step):
                found.setdefault((step.line, step.text), step)
    return list(found.values())


def describe_refusal(environment: str, steps: list[Step]) -> str:
    listed = "; ".join(f"line {s.line}: {s.keyword} {s.text}" for s in steps[:3])
    more = f" (and {len(steps) - 3} more)" if len(steps) > 3 else ""
    return (
        f"environment {environment!r} is protected (read-only) and these steps would "
        f"change data: {listed}{more}; {ALLOW_HINT}"
    )
