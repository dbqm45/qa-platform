"""Browser navigation steps (TASK-040).

| Step                               | Action                 |
|------------------------------------|------------------------|
| the user opens {string}            | ``browser.open``       |
| the user navigates to {string}     | ``browser.navigate``   |
| the user reloads the page          | ``browser.reload``     |
| the user goes back                 | ``browser.back``       |

URLs are absolute ``http(s)://`` URLs or paths starting with ``/`` (resolved
against the environment's ``base_url``). Other schemes are rejected when the
scenario is compiled.
"""

from collections.abc import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Response

from qa_core.steps.registry import StepRegistry
from qa_execution.browser.adapter import BrowserSession, first_line
from qa_execution.errors import StepFailure, TestEnvironmentError
from qa_execution.runner import StepContext
from qa_execution.values import Url
from qa_schemas.enums import StepKind

CAPABILITY = "browser"
_BLANK = "about:blank"


def open_url(context: StepContext, url: Url) -> None:
    _go(context, url)


def navigate_to(context: StepContext, url: Url) -> None:
    _go(context, url)


def reload_page(context: StepContext) -> None:
    page = _page(context)
    _check_response(page, _call(page, "reload", page.reload), page.url)


def go_back(context: StepContext) -> None:
    page = _page(context)
    before = page.url
    response = _call(page, "go back", page.go_back)
    if page.url == _BLANK:  # a new tab starts at about:blank, which is not a page of the app
        _call(page, "go forward", page.go_forward)
    if page.url in (before, _BLANK):
        raise StepFailure(f"there is no previous page to go back to (current page: {before})")
    _check_response(page, response, page.url)


def register_navigation_steps(registry: StepRegistry) -> None:
    action = StepKind.ACTION
    registry.register(
        "browser.open", "the user opens {string}", open_url, kind=action, capability=CAPABILITY
    )
    registry.register(
        "browser.navigate", "the user navigates to {string}", navigate_to,
        kind=action, capability=CAPABILITY,
    )  # fmt: skip
    registry.register(
        "browser.reload",
        "the user reloads the page",
        reload_page,
        kind=action,
        capability=CAPABILITY,
    )
    registry.register(
        "browser.back", "the user goes back", go_back, kind=action, capability=CAPABILITY
    )


# --- Internals ---------------------------------------------------------------


def _page(context: StepContext) -> Page:
    return session(context).page


def session(context: StepContext) -> "BrowserSession":
    """The browser session of the current test case."""
    value: BrowserSession = context.resource(CAPABILITY)
    return value


def _go(context: StepContext, url: str) -> None:
    if url.startswith("/") and context.execution.environment.base_url is None:
        raise TestEnvironmentError(
            f"cannot open relative URL {url!r}: environment "
            f"{context.execution.environment.name!r} has no base_url"
        )
    page = _page(context)
    response = _call(page, f"open {url}", lambda: page.goto(url))
    _check_response(page, response, url)


def _call(page: Page, what: str, action: Callable[[], Response | None]) -> Response | None:
    """Run a navigation; connection problems and timeouts are environment errors."""
    try:
        return action()
    except PlaywrightError as exc:
        raise TestEnvironmentError(
            f"cannot {what}: {first_line(exc)} (current page: {page.url})"
        ) from None


def _check_response(page: Page, response: Response | None, url: str) -> None:
    if response is not None and response.status >= 400:
        raise StepFailure(
            f"{url} responded with HTTP {response.status} {response.status_text}".rstrip()
            + f" (current page: {page.url})"
        )
