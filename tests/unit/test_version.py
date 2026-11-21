"""Example unit test: the runtime version must match the installed distribution."""

import re
from importlib.metadata import version

import qa_core

SEMVER = re.compile(r"^\d+\.\d+\.\d+")


def test_version_matches_distribution_metadata() -> None:
    assert qa_core.__version__ == version("qa-platform")


def test_version_is_semantic() -> None:
    assert SEMVER.match(qa_core.__version__), qa_core.__version__
