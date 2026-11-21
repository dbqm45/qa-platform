"""Locator syntax and browser configuration (TASK-043, TASK-044); no browser needed."""

import pytest
from pydantic import ValidationError

from qa_execution.adapters import evidence_folder
from qa_execution.browser.config import BrowserConfig
from qa_execution.browser.locators import DEFAULT_STRATEGIES, parse_locator


@pytest.mark.parametrize(
    ("text", "strategies", "value", "role"),
    [
        ("Log in", DEFAULT_STRATEGIES, "Log in", None),
        ("testid:login-button", ("testid",), "login-button", None),
        ("label:Email", ("label",), "Email", None),
        ("text:Welcome back", ("text",), "Welcome back", None),
        ("css:#login > button", ("css",), "#login > button", None),
        ("role:button=Log in", ("role",), "Log in", "button"),
        ("role:heading", ("role",), "", "heading"),
        ("Note: read me", DEFAULT_STRATEGIES, "Note: read me", None),  # unknown prefix
        ("https://example.com", DEFAULT_STRATEGIES, "https://example.com", None),
    ],
)
def test_parse_locator(
    text: str, strategies: tuple[str, ...], value: str, role: str | None
) -> None:
    spec = parse_locator(text)
    assert (spec.strategies, spec.value, spec.role) == (strategies, value, role)


def test_plain_text_uses_configured_order() -> None:
    assert parse_locator("Save", ("text", "role")).strategies == ("text", "role")


def test_css_is_never_implicit() -> None:
    assert "css" not in DEFAULT_STRATEGIES
    with pytest.raises(ValidationError, match="locator_strategies"):
        BrowserConfig(locator_strategies=("testid", "css"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "locator is empty"),
        ("   ", "locator is empty"),
        ("css:", "has no value after 'css:'"),
        ("testid: ", "has no value after 'testid:'"),
        ("role:=Save", "must look like 'role:button=Log in'"),
        ("role:button=", "must look like 'role:button=Log in'"),
    ],
)
def test_malformed_locators(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_locator(text)


def test_browser_config_defaults() -> None:
    config = BrowserConfig()
    assert config.locator_strategies == ("testid", "role", "label", "text")
    assert (config.screenshot, config.trace, config.test_id_attribute) == (
        "on-failure",
        "off",
        "data-testid",
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"locator_strategies": ()},
        {"locator_strategies": ("text", "text")},
        {"screenshot": "sometimes"},
        {"test_id_attribute": "data testid"},
        {"viewport_width": 10},
        {"unknown": 1},
    ],
)
def test_invalid_browser_config(settings: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BrowserConfig.model_validate(settings)


def test_evidence_folder_is_filesystem_safe() -> None:
    assert evidence_folder("login.apply-code:2") == "login.apply-code_2"
    assert evidence_folder("a/b\\c") == "a_b_c"
