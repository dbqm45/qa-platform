"""`qa project show` (TASK-015)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from qa_cli.main import app

runner = CliRunner()

CONFIG = """\
version: 1
project:
  id: shop
  name: Example Shop
  default_environment: local
  repositories:
    - name: web
      path: ../shop-web
  environments:
    - name: local
      base_url: http://localhost:8000
      services:
        api: http://localhost:8000/api
      timeout_seconds: 10
      variables:
        SHOP_USER: alice
      headers:
        Authorization: Bearer ${API_TOKEN}
    - name: bare
adapters:
  playwright:
    headless: true
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "qa.yaml").write_text(CONFIG)
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "a.feature").write_text("Feature: A\n")
    (tmp_path / "scenarios" / "b.feature").write_text("Feature: B\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_TOKEN", "s3cr3t-token-value")
    return tmp_path


def test_shows_the_whole_configuration(project: Path) -> None:
    result = runner.invoke(app, ["project", "show"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    for expected in [
        "Project      Example Shop (shop)",
        "Config       qa.yaml",
        "Scenarios    scenarios  (2 files)",
        "  web          ../shop-web",
        "  local  (default)",
        "    base_url   http://localhost:8000/",
        "    service    api = http://localhost:8000/api",
        "    timeout    10 s",
        "    variables  SHOP_USER",
        "    header     Authorization: Bearer ${API_TOKEN}",
        "  bare",
        "    base_url   -",
        "  playwright   browser  (configured)",
        "  httpx        http  (defaults)",
    ]:
        assert expected in lines, expected


def test_never_shows_secret_or_variable_values(project: Path) -> None:
    output = runner.invoke(app, ["project", "show"]).output
    assert "s3cr3t-token-value" not in output
    assert "alice" not in output  # variables by name only


def test_empty_project_and_missing_scenario_dir(tmp_path: Path) -> None:
    (tmp_path / "qa.yaml").write_text("project:\n  id: p\n  name: P\n")

    result = runner.invoke(app, ["project", "show", "-c", str(tmp_path / "qa.yaml")])

    assert result.exit_code == 0, result.output
    assert "(0 files)" in result.output
    assert result.output.count("  (none)") == 2  # repositories and environments


def test_missing_config_is_an_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["project", "show", "-c", str(tmp_path / "qa.yaml")])
    assert result.exit_code == 1
    assert "file not found; run `qa init`" in result.output
