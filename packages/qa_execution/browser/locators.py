"""Element locators for browser steps (TASK-043).

A locator in a step is either plain text or ``<strategy>:<value>``:

| Written as                 | Finds                                                   |
|----------------------------|---------------------------------------------------------|
| ``Log in``                 | tries the configured strategies in order (below)        |
| ``testid:login-button``    | element with ``data-testid="login-button"``             |
| ``role:button=Log in``     | element with ARIA role ``button`` and name ``Log in``   |
| ``label:Email``            | form control labelled ``Email``                         |
| ``text:Welcome``           | element whose text is exactly ``Welcome``               |
| ``css:#login > button``    | CSS selector (only when written explicitly)             |

Plain text tries ``testid``, ``role``, ``label`` and ``text`` (configurable).
The first strategy that finds visible elements decides: exactly one element is
used; several are reported as ambiguous. CSS is never tried implicitly, so it
cannot silently win over semantic locators.
"""

import time
from dataclasses import dataclass
from typing import Any, Literal, cast, get_args

from playwright.sync_api import Locator, Page

from qa_execution.errors import StepFailure

Strategy = Literal["testid", "role", "label", "text"]
ExplicitStrategy = Strategy | Literal["css"]

DEFAULT_STRATEGIES: tuple[Strategy, ...] = ("testid", "role", "label", "text")
EXPLICIT: frozenset[str] = frozenset(get_args(Strategy)) | {"css"}

IMPLICIT_ROLES = (
    "button", "link", "textbox", "checkbox", "radio", "combobox", "listbox",
    "option", "menuitem", "tab", "switch", "searchbox", "spinbutton", "heading",
)  # fmt: skip
"""Roles tried for plain-text locators: elements a scenario usually talks about."""

_POLL_MS = 50


@dataclass(frozen=True)
class LocatorSpec:
    text: str
    """As written in the step."""
    strategies: tuple[ExplicitStrategy, ...]
    value: str
    role: str | None = None

    @property
    def explicit(self) -> bool:
        return len(self.strategies) == 1 and self.text != self.value


def parse_locator(text: str, strategies: tuple[Strategy, ...] = DEFAULT_STRATEGIES) -> LocatorSpec:
    """Interpret a locator written in a step; raises ValueError if it is malformed."""
    prefix, sep, rest = text.partition(":")
    if sep and prefix in EXPLICIT:
        if not rest.strip():
            raise ValueError(f"locator {text!r} has no value after '{prefix}:'")
        if prefix == "role":
            role, eq, name = rest.partition("=")
            if not role.strip() or (eq and not name.strip()):
                raise ValueError(f"role locator must look like 'role:button=Log in', got {text!r}")
            return LocatorSpec(text, ("role",), name.strip(), role=role.strip())
        return LocatorSpec(text, (prefix,), rest)  # type: ignore[arg-type]
    if not text.strip():
        raise ValueError("locator is empty")
    return LocatorSpec(text, strategies, text)


def _candidates(page: Page, spec: LocatorSpec, strategy: ExplicitStrategy) -> Locator:
    value = spec.value
    match strategy:
        case "testid":
            locator = page.get_by_test_id(value)
        case "label":
            locator = page.get_by_label(value, exact=True)
        case "text":
            locator = page.get_by_text(value, exact=True)
        case "css":
            locator = page.locator(value)
        case "role":
            roles = (spec.role,) if spec.role is not None else IMPLICIT_ROLES
            locator = _by_role(page, roles[0], value)
            for role in roles[1:]:
                locator = locator.or_(_by_role(page, role, value))
    return locator.filter(visible=True)


def _by_role(page: Page, role: str, name: str) -> Locator:
    # Roles come from scenario text; Playwright rejects unknown ones at run time.
    return page.get_by_role(cast(Any, role), name=name or None, exact=True)


def find_matches(page: Page, spec: LocatorSpec) -> tuple[ExplicitStrategy, Locator, int] | None:
    """The first strategy with visible matches, its locator and match count; no waiting."""
    for strategy in spec.strategies:
        locator = _candidates(page, spec, strategy)
        count = locator.count()
        if count:
            return strategy, locator, count
    return None


def resolve(page: Page, spec: LocatorSpec, timeout_seconds: float) -> Locator:
    """Exactly one visible element, waiting up to ``timeout_seconds`` for it to appear.

    Raises ``StepFailure`` when nothing matches in time or the match is ambiguous.
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        found = find_matches(page, spec)
        if found is not None:
            strategy, locator, count = found
            if count == 1:
                return locator
            raise StepFailure(
                f"{spec.text!r} is ambiguous: {count} visible elements match by {strategy}"
                f"{describe_matches(locator)} (page: {page.url})"
            )
        if time.monotonic() >= deadline:
            tried = ", ".join(spec.strategies)
            raise StepFailure(
                f"no visible element matches {spec.text!r} (tried: {tried}; page: {page.url})"
            )
        page.wait_for_timeout(_POLL_MS)  # processes browser events, unlike time.sleep


def describe_matches(locator: Locator, limit: int = 3) -> str:
    """Short description of the first matches, to help fix an ambiguous locator."""
    try:
        descriptions = locator.evaluate_all(
            """(els, limit) => els.slice(0, limit).map(e => {
                const id = e.getAttribute('data-testid');
                const text = (e.innerText || e.value || '').trim().slice(0, 30);
                return `<${e.tagName.toLowerCase()}${id ? ` data-testid="${id}"` : ''}>` +
                       (text ? ` "${text}"` : '');
            })""",
            limit,
        )
    except Exception:
        return ""
    return ": " + ", ".join(descriptions) if descriptions else ""
