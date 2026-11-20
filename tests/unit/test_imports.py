"""Every platform package must be importable from the installed environment."""

import importlib

import pytest

PACKAGES = ["qa_cli", "qa_core", "qa_schemas", "qa_execution", "qa_reporting"]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_is_importable(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__doc__, f"{name} should document its responsibility"
