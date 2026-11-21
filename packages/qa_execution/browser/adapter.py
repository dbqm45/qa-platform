"""Playwright adapter: provides the ``browser`` capability (TASK-039, TASK-044).

One browser per execution and a fresh browser context (cookies, storage,
page) per test case, so test cases cannot influence each other. Steps receive
a :class:`BrowserSession` with the current page and the browser settings.

Evidence per test case, in ``<evidence dir>/<test case id>/``:

- ``page.json`` -- final URL, title, console errors and uncaught page errors;
- ``screenshot.png`` -- by default only when the test case did not pass;
- ``trace.zip`` -- Playwright trace, only when enabled.
"""

import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    ConsoleMessage,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError
from pydantic import ValidationError

from qa_execution.adapters import (
    AdapterNotPreparedError,
    ExecutionContext,
    TestAdapter,
    evidence_folder,
)
from qa_execution.browser.config import BrowserConfig, EvidenceMode
from qa_execution.errors import TestEnvironmentError
from qa_schemas.evidence import EvidenceReference
from qa_schemas.specification import TestCase

INSTALL_HINT = (
    "install the browser with `uv run playwright install chromium`, "
    "or set adapters.playwright.executable_path in qa.yaml"
)


@dataclass
class BrowserSession:
    """The ``browser`` resource handed to step implementations."""

    page: Page
    config: BrowserConfig
    timeout_seconds: float
    console_errors: list[str] = field(default_factory=list)


class PlaywrightAdapter(TestAdapter):
    name = "playwright"
    capabilities = frozenset({"browser"})

    def __init__(self) -> None:
        self.config = BrowserConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._session: BrowserSession | None = None
        self._execution: ExecutionContext | None = None
        self._passed: bool | None = None
        self._tracing = False

    # --- Lifecycle -----------------------------------------------------------

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
        self._playwright.selectors.set_test_id_attribute(self.config.test_id_attribute)
        launcher = getattr(self._playwright, self.config.browser)
        try:
            self._browser = launcher.launch(
                headless=self.config.headless, executable_path=self.config.executable_path
            )
        except PlaywrightError as exc:
            raise TestEnvironmentError(
                f"cannot launch {self.config.browser}: {first_line(exc)}; {INSTALL_HINT}"
            ) from None

    def start_test_case(self, test_case: TestCase) -> None:
        self._close_context()  # left over if evidence collection did not run
        browser, execution = self._require_browser()
        base_url = execution.environment.base_url
        context = browser.new_context(
            base_url=str(base_url) if base_url else None,
            viewport={"width": self.config.viewport_width, "height": self.config.viewport_height},
        )
        timeout = execution.settings.step_timeout_seconds
        context.set_default_timeout(timeout * 1000)
        if self.config.trace != "off":
            context.tracing.start(screenshots=True, snapshots=True)
            self._tracing = True
        self._context = context
        page = context.new_page()
        session = BrowserSession(page=page, config=self.config, timeout_seconds=timeout)
        page.on("console", lambda message: _record_console(session, message))
        page.on("pageerror", lambda error: session.console_errors.append(f"uncaught: {error}"))
        self._session = session
        self._passed = None

    def finish_test_case(self, test_case: TestCase, passed: bool) -> None:
        self._passed = passed  # the context stays open until evidence is collected

    def collect_evidence(self, test_case: TestCase) -> list[EvidenceReference]:
        session, execution = self._session, self._execution
        if session is None or execution is None:
            return []
        folder = evidence_folder(test_case.id)
        directory = execution.evidence_dir / folder
        directory.mkdir(parents=True, exist_ok=True)
        failed = self._passed is not True
        evidence: list[EvidenceReference] = []
        try:
            page = session.page
            info = {
                "url": page.url,
                "title": _safe(page.title, ""),
                "console_errors": session.console_errors,
            }
            text = json.dumps(execution.redactor.redact_data(info), indent=2) + "\n"
            (directory / "page.json").write_text(text)
            evidence.append(
                _ref("page-info", folder, "page.json", "final URL, title and console errors")
            )

            if _wanted(self.config.screenshot, failed):
                page.screenshot(path=directory / "screenshot.png", full_page=True)
                evidence.append(
                    _ref("screenshot", folder, "screenshot.png", f"page at the end: {page.url}")
                )

            if self._tracing and self._context is not None:
                self._tracing = False
                if _wanted(self.config.trace, failed):
                    self._context.tracing.stop(path=directory / "trace.zip")
                    evidence.append(
                        _ref(
                            "trace", folder, "trace.zip", "open with `uv run playwright show-trace`"
                        )
                    )
                else:
                    self._context.tracing.stop()
        finally:
            self._close_context()
        return evidence

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
        if self._session is None:
            raise AdapterNotPreparedError("the browser page exists only while a test case runs")
        return self._session

    # --- Internals -----------------------------------------------------------

    def _require_browser(self) -> tuple[Browser, ExecutionContext]:
        if self._browser is None or self._execution is None:
            raise AdapterNotPreparedError("playwright is not prepared")
        return self._browser, self._execution

    def _close_context(self) -> None:
        context, self._context, self._session, self._tracing = self._context, None, None, False
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


def _record_console(session: BrowserSession, message: ConsoleMessage) -> None:
    if message.type == "error":
        session.console_errors.append(message.text)


def _wanted(mode: EvidenceMode, failed: bool) -> bool:
    return mode == "always" or (mode == "on-failure" and failed)


def _ref(kind: str, folder: str, name: str, description: str) -> EvidenceReference:
    return EvidenceReference(kind=kind, path=PurePosixPath(folder) / name, description=description)


def _safe(getter: Any, default: str) -> str:
    try:
        return str(getter())
    except PlaywrightError:
        return default


def first_line(error: BaseException) -> str:
    """First line of a Playwright error; its full text contains call logs."""
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__
