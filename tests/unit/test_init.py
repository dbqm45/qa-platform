"""Unit tests for project initialization helpers (TASK-013)."""

import pytest

from qa_core.config import parse_config
from qa_core.init import derive_project_id, render_config


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("shop", "shop"),
        ("My Shop", "my-shop"),
        ("my_shop.v2", "my_shop-v2"),
        ("2024 Shop!", "shop"),
        ("--Shop--", "shop"),
        ("Żółw", "w"),
        ("", "project"),
        ("123", "project"),
        ("a" * 100, "a" * 64),
    ],
)
def test_derive_project_id(name: str, expected: str) -> None:
    assert derive_project_id(name) == expected


@pytest.mark.parametrize(
    "name",
    ["Shop", 'Shop "Beta"', "Shop: v2 # not a comment", "Żółta Łódź", "  padded  "],
)
def test_rendered_config_is_valid_and_keeps_the_name(name: str) -> None:
    config = parse_config(render_config("shop", name))
    assert config.project.id == "shop"
    assert config.project.name == name.strip()
    assert config.project.default_environment == "local"
