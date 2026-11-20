"""`qa init` end to end through the CLI (TASK-013)."""

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from qa_cli.main import app
from qa_core.config import load_config
from qa_core.storage import ProjectRepository, open_database

runner = CliRunner()


def _snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
        for p in sorted(root.rglob("*"))
    }


def test_init_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "My Shop"

    result = runner.invoke(app, ["init", str(root)])

    assert result.exit_code == 0, result.output
    assert "Initialized project 'my-shop'" in result.output
    assert set(_snapshot(root)) == {"qa.yaml", "scenarios", ".qa", ".qa/.gitignore", ".qa/qa.db"}
    config = load_config(root / "qa.yaml")
    assert config.project.id == "my-shop"
    assert config.project.name == "My Shop"
    assert (root / ".qa/.gitignore").read_text().splitlines()[-1] == "*"


def test_init_uses_given_id_and_name(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--id", "shop", "--name", "Shop"])

    assert result.exit_code == 0, result.output
    project = load_config(tmp_path / "qa.yaml").project
    assert (project.id, project.name) == ("shop", "Shop")


def test_init_defaults_to_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init"]).exit_code == 0
    assert (tmp_path / "qa.yaml").is_file()


def test_second_run_changes_nothing(tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(tmp_path), "--id", "shop"])
    (tmp_path / "scenarios" / "login.feature").write_text("Feature: Login\n")
    config = tmp_path / "qa.yaml"
    config.write_text(config.read_text().replace("  name:", "  # edited\n  name:", 1))
    before = _snapshot(tmp_path)

    result = runner.invoke(app, ["init", str(tmp_path), "--id", "other"])

    assert result.exit_code == 0, result.output
    assert _snapshot(tmp_path) == before
    assert "Already initialized project 'shop'" in result.output
    assert "--id/--name were ignored" in result.output


def test_missing_directories_are_recreated_without_touching_config(tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(tmp_path)])
    shutil.rmtree(tmp_path / "scenarios")
    shutil.rmtree(tmp_path / ".qa")
    config_before = (tmp_path / "qa.yaml").read_bytes()

    result = runner.invoke(app, ["init", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "created  scenarios" in result.output
    assert "exists   qa.yaml" in result.output
    assert (tmp_path / "qa.yaml").read_bytes() == config_before


def test_existing_scenario_dir_from_config_is_used(tmp_path: Path) -> None:
    (tmp_path / "qa.yaml").write_text("project:\n  id: shop\n  name: Shop\n  scenario_dir: specs\n")

    result = runner.invoke(app, ["init", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "specs").is_dir()
    assert not (tmp_path / "scenarios").exists()


def test_invalid_existing_config_is_reported_and_left_alone(tmp_path: Path) -> None:
    config = tmp_path / "qa.yaml"
    config.write_text("project:\n  id: Shop\n")

    result = runner.invoke(app, ["init", str(tmp_path)])

    assert result.exit_code == 1
    assert "project.id:" in result.output
    assert "project.name: Field required" in result.output
    assert config.read_text() == "project:\n  id: Shop\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["qa.yaml"]


def test_invalid_id_creates_nothing(tmp_path: Path) -> None:
    root = tmp_path / "new"

    result = runner.invoke(app, ["init", str(root), "--id", "Bad Id"])

    assert result.exit_code == 1
    assert "invalid project id or name" in result.output
    assert not root.exists()


def test_scenario_dir_outside_project_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "qa.yaml").write_text("project:\n  id: p\n  name: P\n  scenario_dir: ../elsewhere\n")

    result = runner.invoke(app, ["init", str(root)])

    assert result.exit_code == 1
    assert "outside the project" in result.output
    assert not (tmp_path / "elsewhere").exists()


def test_file_instead_of_directory_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x")

    result = runner.invoke(app, ["init", str(target)])

    assert result.exit_code == 1
    assert "is not a directory" in result.output


def test_installed_qa_command(tmp_path: Path) -> None:
    executable = shutil.which("qa")
    assert executable, "the `qa` entry point should be installed in the environment"

    completed = subprocess.run(
        [executable, "init", str(tmp_path / "app")], capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "app" / "qa.yaml").is_file()


def test_init_registers_project_in_database(tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(tmp_path), "--id", "shop", "--name", "Shop"])
    config = tmp_path / "qa.yaml"
    config.write_text(config.read_text().replace('name: "Shop"', 'name: "Shop v2"'))

    result = runner.invoke(app, ["init", str(tmp_path)])

    assert result.exit_code == 0, result.output
    with open_database(tmp_path / ".qa" / "qa.db") as db:
        record = ProjectRepository(db).get("shop")
    assert record is not None
    assert record.name == "Shop v2"
    assert record.updated_at >= record.created_at


def test_corrupt_database_is_reported(tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(tmp_path)])
    (tmp_path / ".qa" / "qa.db").write_bytes(b"garbage" * 200)

    result = runner.invoke(app, ["init", str(tmp_path)])

    assert result.exit_code == 1
    assert "unusable" in result.output
