"""Playwright adapter: provides the ``browser`` capability (TASK-039).

One browser per execution and a fresh browser context (cookies, storage,
page) per test case, so test cases cannot influence each other. The resource
handed to steps is the current Playwright ``Page``.
"""

from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from pydantic import ValidationError

from qa_execution.adapters import AdapterNotPreparedError, ExecutionContext, TestAdapter
from qa_execution.browser.config import BrowserConfig
from qa_execution.errors import TestEnvironmentError
from qa_schemas.specification import TestCase

INSTALL_HINT = (
    "install the browser with `uv run playwright install chromium`, "
    "or set adapters.playwright.executable_path in qa.yaml"
)


class PlaywrightAdapter(TestAdapter):
    name = "playwright"
    capabilities = frozenset({"browser"})

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._execution: ExecutionContext | None = None
        self.config = BrowserConfig()

    def prepare(self, context: ExecutionContext) -> None:
        try:
            self.config = BrowserConfig.model_validate(dict(context.config_for(self.name)))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_url=False)
            )
            raise TestEnvironmentError(
                f"invalid adapters.playwright configuration: {problems}"
            ) from None
        self._execution = context
        self._playwright = sync_playwright().start()
        launcher = getattr(self._playwright, self.config.browser)
        try:
            self._browser = launcher.launch(
                headless=self.config.headless,
                executable_path=self.config.executable_path,
            )
        except PlaywrightError as exc:
            first_line = (
                str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            )
            raise TestEnvironmentError(
                f"cannot launch {self.config.browser}: {first_line}; {INSTALL_HINT}"
            ) from None

    def start_test_case(self, test_case: TestCase) -> None:
        browser, execution = self._require_browser()
        base_url = execution.environment.base_url
        self._context = browser.new_context(
            base_url=str(base_url) if base_url else None,
            viewport={"width": self.config.viewport_width, "height": self.config.viewport_height},
        )
        self._context.set_default_timeout(execution.settings.step_timeout_seconds * 1000)
        self._page = self._context.new_page()

    def finish_test_case(self, test_case: TestCase, passed: bool) -> None:
        self._close_context()

    def cleanup(self) -> None:
        errors = []
        for close in (self._close_context, self._close_browser, self._stop_playwright):
            try:
                close()
            except Exception as exc:  # keep closing the rest
                errors.append(f"{close.__name__.strip('_')}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))

    @property
    def resource(self) -> Any:
        if self._page is None:
            raise AdapterNotPreparedError("the browser page exists only while a test case runs")
        return self._page

    @property
    def base_url(self) -> str | None:
        if self._execution is None or self._execution.environment.base_url is None:
            return None
        return str(self._execution.environment.base_url)

    # --- Internals -----------------------------------------------------------

    def _require_browser(self) -> tuple[Browser, ExecutionContext]:
        if self._browser is None or self._execution is None:
            raise AdapterNotPreparedError("playwright is not prepared")
        return self._browser, self._execution

    def _close_context(self) -> None:
        context, self._context, self._page = self._context, None, None
        if context is not None:
            context.close()

    def _close_browser(self) -> None:
        browser, self._browser = self._browser, None
        if browser is not None:
            browser.close()

    def _stop_playwright(self) -> None:
        playwright, self._playwright = self._playwright, None
        if playwright is not None:
            playwright.stop()
