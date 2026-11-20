"""Sanity checks for the development environment."""

import sys


def test_python_version_matches_project_requirement() -> None:
    assert sys.version_info[:2] == (3, 12)
