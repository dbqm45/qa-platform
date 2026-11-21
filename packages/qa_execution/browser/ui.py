"""UI interaction and assertion steps (TASK-041, TASK-042).

``<element>`` is a locator as described in ``qa_execution.browser.locators``:
plain text (``Log in``) or ``strategy:value`` (``testid:login``, ``label:Email``,
``role:button=Save``, ``text:Welcome``, ``css:#id``).

Interactions (precondition / action):

| Step                                         | Action                |
|----------------------------------------------|-----------------------|
| the user clicks {string}                     | ``ui.click``          |
| the user fills {string} with {string}        | ``ui.fill``           |
| the user selects {string} in {string}        | ``ui.select``         |
| the user checks {string}                     | ``ui.check``          |
| the user unchecks {string}                   | ``ui.uncheck``        |
| the user submits the form                    | ``ui.submit``         |

Assertions (expectation) wait up to the step timeout for the condition:

| Step                                         | Action                |
|----------------------------------------------|-----------------------|
| {string} is visible                          | ``ui.visible``        |
| {string} is hidden                           | ``ui.hidden``         |
| the page shows {string}                      | ``ui.text-present``   |
| the URL is {string}                          | ``ui.url-is``         |
| the URL contains {string}                    | ``ui.url-contains``   |
| {string} is enabled                          | ``ui.enabled``        |
| {string} is disabled                         | ``ui.disabled``       |
| {string} has value {string}                  | ``ui.value``          |
"""

import time
from collections.abc import Callable
from typing import Annotated
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator
from pydantic import AfterValidator

from qa_core.steps.registry import StepHandler, StepRegistry
from qa_execution.browser.adapter import BrowserSession, first_line
from qa_execution.browser.locators import find_matches, parse_locator, resolve
from qa_execution.browser.navigation import CAPABILITY, session
from qa_execution.errors import StepFailure, TestEnvironmentError
from qa_execution.runner import StepContext
from qa_schemas.enums import StepKind

_POLL_MS = 50
_MASK = "********"


def _check_locator(value: str) -> str:
    parse_locator(value)
    return value


Element = Annotated[str, AfterValidator(_check_locator)]
"""A locator; malformed ones (``role:``, ``css:``) are rejected at compile time."""


# --- Interactions ------------------------------------------------------------


def click(context: StepContext, element: Element) -> None:
    browser, target = _element(context, element)
    _act(browser, f"click {element!r}", target.click)


def fill(context: StepContext, element: Element, value: str) -> None:
    browser, target = _element(context, element)
    _act(browser, f"fill {element!r}", lambda: target.fill(value))


def select(context: StepContext, option: str, element: Element) -> None:
    browser, target = _element(context, element)
    _act(browser, f"select {option!r} in {element!r}", lambda: target.select_option(option))


def check(context: StepContext, element: Element) -> None:
    browser, target = _element(context, element)
    _act(browser, f"check {element!r}", target.check)


def uncheck(context: StepContext, element: Element) -> None:
    browser, target = _element(context, element)
    _act(browser, f"uncheck {element!r}", target.uncheck)


_SUBMIT = """() => {
    const active = document.activeElement;
    let form = active && (active.form || (active.closest && active.closest('form')));
    if (!form) {
        const forms = document.querySelectorAll('form');
        if (forms.length !== 1) return forms.length ? `ambiguous:${forms.length}` : 'none';
        form = forms[0];
    }
    form.requestSubmit();
    return 'ok';
}"""


def submit_form(context: StepContext) -> None:
    browser = session(context)
    result = _act(browser, "submit the form", lambda: str(browser.page.evaluate(_SUBMIT)))
    if result == "none":
        raise StepFailure(f"there is no form on the page (page: {browser.page.url})")
    if result.startswith("ambiguous:"):
        raise StepFailure(
            f"the page has {result.split(':')[1]} forms and none contains the focused element; "
            f"click or fill a field of the form first (page: {browser.page.url})"
        )
    _act(browser, "wait for the page after submitting", browser.page.wait_for_load_state)


# --- Assertions --------------------------------------------------------------


def is_visible(context: StepContext, element: Element) -> None:
    _element(context, element)  # waits for exactly one visible element


def is_hidden(context: StepContext, element: Element) -> None:
    browser = session(context)
    spec = parse_locator(element, browser.config.locator_strategies)
    _eventually(
        browser,
        lambda: find_matches(browser.page, spec) is None,
        lambda: f"{element!r} is still visible (page: {browser.page.url})",
    )


def text_present(context: StepContext, text: str) -> None:
    browser = session(context)
    matches = browser.page.get_by_text(text).filter(visible=True)
    _eventually(
        browser,
        lambda: matches.count() > 0,
        lambda: f"the page does not show {text!r} (page: {browser.page.url})",
    )


def url_is(context: StepContext, url: str) -> None:
    browser = session(context)
    _eventually(
        browser,
        lambda: _url_matches(browser.page.url, url),
        lambda: f"the URL is {browser.page.url!r}, expected {url!r}",
    )


def url_contains(context: StepContext, part: str) -> None:
    browser = session(context)
    _eventually(
        browser,
        lambda: part in browser.page.url,
        lambda: f"the URL {browser.page.url!r} does not contain {part!r}",
    )


def is_enabled(context: StepContext, element: Element) -> None:
    _state(context, element, enabled=True)


def is_disabled(context: StepContext, element: Element) -> None:
    _state(context, element, enabled=False)


def has_value(context: StepContext, element: Element, value: str) -> None:
    browser, target = _element(context, element)
    secret = (
        _act(browser, "read the field type", lambda: target.get_attribute("type")) == "password"
    )

    def actual() -> str:
        return _act(browser, f"read the value of {element!r}", target.input_value)

    _eventually(
        browser,
        lambda: actual() == value,
        lambda: (
            f"{element!r} has value {_MASK if secret else repr(actual())}, "
            f"expected {_MASK if secret else repr(value)} (page: {browser.page.url})"
        ),
    )


# --- Registration ------------------------------------------------------------


def register_ui_steps(registry: StepRegistry) -> None:
    a, e = StepKind.ACTION, StepKind.EXPECTATION
    definitions: list[tuple[str, str, StepHandler, StepKind]] = [
        ("ui.click", "the user clicks {string}", click, a),
        ("ui.fill", "the user fills {string} with {string}", fill, a),
        ("ui.select", "the user selects {string} in {string}", select, a),
        ("ui.check", "the user checks {string}", check, a),
        ("ui.uncheck", "the user unchecks {string}", uncheck, a),
        ("ui.submit", "the user submits the form", submit_form, a),
        ("ui.visible", "{string} is visible", is_visible, e),
        ("ui.hidden", "{string} is hidden", is_hidden, e),
        ("ui.text-present", "the page shows {string}", text_present, e),
        ("ui.url-is", "the URL is {string}", url_is, e),
        ("ui.url-contains", "the URL contains {string}", url_contains, e),
        ("ui.enabled", "{string} is enabled", is_enabled, e),
        ("ui.disabled", "{string} is disabled", is_disabled, e),
        ("ui.value", "{string} has value {string}", has_value, e),
    ]
    for step_id, pattern, handler, kind in definitions:
        registry.register(step_id, pattern, handler, kind=kind, capability=CAPABILITY)


# --- Internals ---------------------------------------------------------------


def _element(context: StepContext, text: str) -> tuple[BrowserSession, Locator]:
    browser = session(context)
    spec = parse_locator(text, browser.config.locator_strategies)
    return browser, resolve(browser.page, spec, browser.timeout_seconds)


def _act[T](browser: BrowserSession, what: str, action: Callable[[], T]) -> T:
    """Run a Playwright call; a closed browser is an environment problem, anything
    else (not editable, detached, timeout) means the page did not behave as expected."""
    try:
        return action()
    except PlaywrightError as exc:
        message = first_line(exc)
        if "has been closed" in message:
            raise TestEnvironmentError(f"cannot {what}: {message}") from None
        raise StepFailure(f"cannot {what}: {message} (page: {_url(browser)})") from None


def _eventually(
    browser: BrowserSession, condition: Callable[[], bool], message: Callable[[], str]
) -> None:
    deadline = time.monotonic() + browser.timeout_seconds
    while True:
        if _act(browser, "check the page", condition):
            return
        if time.monotonic() >= deadline:
            raise StepFailure(message())
        # Not time.sleep: the sync API only processes browser events (navigation,
        # page.url updates) while a Playwright call is running.
        browser.page.wait_for_timeout(_POLL_MS)


def _state(context: StepContext, element: str, *, enabled: bool) -> None:
    browser, target = _element(context, element)
    expected = "enabled" if enabled else "disabled"
    _eventually(
        browser,
        lambda: target.is_enabled() is enabled,
        lambda: f"{element!r} is not {expected} (page: {browser.page.url})",
    )


def _url_matches(actual: str, expected: str) -> bool:
    if not expected.startswith("/"):
        return actual == expected
    parts = urlsplit(actual)
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    return expected in (parts.path, path)


def _url(browser: BrowserSession) -> str:
    try:
        return browser.page.url
    except PlaywrightError:
        return "unknown"
