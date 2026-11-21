"""Browser settings: ``adapters.playwright`` in ``qa.yaml`` (TASK-039, TASK-043, TASK-044)."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from qa_execution.browser.locators import DEFAULT_STRATEGIES, Strategy
from qa_schemas.base import SchemaModel

EvidenceMode = Literal["off", "on-failure", "always"]


class BrowserConfig(SchemaModel):
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    executable_path: Path | None = None
    """Use a specific browser binary instead of the one Playwright installed."""
    viewport_width: Annotated[int, Field(ge=200, le=7680)] = 1280
    viewport_height: Annotated[int, Field(ge=200, le=4320)] = 720
    locator_strategies: Annotated[tuple[Strategy, ...], Field(min_length=1)] = DEFAULT_STRATEGIES
    """Order in which plain-text locators are tried. CSS is only used when written
    explicitly (``css:...``) and cannot be listed here."""
    test_id_attribute: Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$")] = "data-testid"
    screenshot: EvidenceMode = "on-failure"
    trace: EvidenceMode = "off"
    """Playwright traces are large; record them only when needed."""

    @model_validator(mode="after")
    def _unique_strategies(self) -> Self:
        if len(set(self.locator_strategies)) != len(self.locator_strategies):
            raise ValueError("locator_strategies must not repeat a strategy")
        return self
