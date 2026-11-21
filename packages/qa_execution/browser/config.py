"""Browser configuration: the ``adapters.playwright`` section of ``qa.yaml`` (TASK-039)."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from qa_schemas.base import SchemaModel


class BrowserConfig(SchemaModel):
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    executable_path: Path | None = None
    """Use a specific browser binary instead of the one Playwright installed."""
    viewport_width: Annotated[int, Field(ge=200, le=7680)] = 1280
    viewport_height: Annotated[int, Field(ge=200, le=4320)] = 720
