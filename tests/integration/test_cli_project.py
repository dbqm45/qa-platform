"""`qa project repo add` / `qa project env add` (TASK-014)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from qa_cli.main import app
from qa_core.config import load_config
from qa_core.config_edit import ConfigEditError, add_repository

runner = CliRunner()


@pytest.fixture
def config(tmp_path: Path) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path), "--id", "shop", "--name", "Shop"])
    assert result.exit_code == 0, result.output
    return tmp_path / "qa.yaml"


def _comments(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip().startswith("#")]


def _run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


# --- repo add ----------------------------------------------------------------


def test_repo_add_persists_and_keeps_comments(config: Path) -> None:
    comments = _comments(config)

    code, output = _run("project", "repo", "add", "web", "--path", "../shop-web", "-c", str(config))

    assert code == 0, output
    assert "Added repository 'web'" in output
    assert _comments(config) == comments
    [repo] = load_config(config).project.repositories
    assert (repo.name, str(repo.path), repo.url) == ("web", "../shop-web", None)


def test_repo_add_several(config: Path) -> None:
    _run("project", "repo", "add", "web", "--path", "../web", "-c", str(config))
    _run("project", "repo", "add", "api", "--url", "https://example.com/org/api", "-c", str(config))

    repos = load_config(config).project.repositories
    assert [r.name for r in repos] == ["web", "api"]


def test_repo_add_uses_qa_yaml_in_current_directory(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(config.parent)
    code, output = _run("project", "repo", "add", "web", "--path", "../web")
    assert code == 0, output
    assert load_config(config).project.repositories[0].name == "web"


def test_values_are_written_as_typed(config: Path) -> None:
    _run("project", "repo", "add", "api", "--url", "https://example.com/org/api", "-c", str(config))
    assert "url: https://example.com/org/api\n" in config.read_text()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["web", "--path", "x"], "repository 'web' already exists"),
        (["api"], "needs at least one of 'path' or 'url'"),
        (["Bad", "--path", "x"], "name: must start with a lowercase letter"),
        (["api", "--url", "ftp://example.com"], "url:"),
    ],
)
def test_repo_add_rejects_invalid_input_without_changes(
    config: Path, args: list[str], message: str
) -> None:
    _run("project", "repo", "add", "web", "--path", "../web", "-c", str(config))
    before = config.read_bytes()

    code, output = _run("project", "repo", "add", *args, "-c", str(config))

    assert code == 1
    assert message in output
    assert config.read_bytes() == before


def test_credentials_in_url_are_rejected_and_not_echoed(config: Path) -> None:
    before = config.read_bytes()
    code, output = _run(
        "project",
        "repo",
        "add",
        "api",
        "--url",
        "https://bob:hunter2@example.com",
        "-c",
        str(config),
    )
    assert code == 1
    assert "must not contain credentials" in output
    assert "hunter2" not in output
    assert config.read_bytes() == before


# --- env add -----------------------------------------------------------------


def test_env_add_with_services_and_default(config: Path) -> None:
    comments = _comments(config)

    code, output = _run(
        "project", "env", "add", "staging",
        "--base-url", "https://staging.example.com",
        "--service", "api=https://api.staging.example.com",
        "--service", "auth=https://auth.example.com",
        "--timeout", "60",
        "--default",
        "-c", str(config),
    )  # fmt: skip

    assert code == 0, output
    assert "as the default environment" in output
    assert _comments(config) == comments
    assert "timeout_seconds: 60\n" in config.read_text()
    project = load_config(config).project
    assert project.default_environment == "staging"
    staging = project.environment("staging")
    assert staging is not None
    assert set(staging.services) == {"api", "auth"}
    assert staging.timeout_seconds == 60


def test_env_add_keeps_default_unless_requested(config: Path) -> None:
    _run("project", "env", "add", "qa", "--base-url", "https://qa.example.com", "-c", str(config))
    assert load_config(config).project.default_environment == "local"


@pytest.mark.parametrize(
    ("args", "code", "message"),
    [
        (["local"], 1, "environment 'local' already exists"),
        (["qa", "--base-url", "not-a-url"], 1, "base_url:"),
        (["qa", "--service", "broken"], 2, "expected NAME=URL"),
        (["qa", "--service", "api=http://a", "--service", "api=http://b"], 2, "given twice"),
        (["qa", "--service", "My Api=http://a"], 1, "services"),
        (["qa", "--timeout", "0"], 1, "timeout_seconds"),
        (["qa", "--timeout", "-5"], 2, "--timeout"),
    ],
)
def test_env_add_rejects_invalid_input_without_changes(
    config: Path, args: list[str], code: int, message: str
) -> None:
    before = config.read_bytes()

    exit_code, output = _run("project", "env", "add", *args, "-c", str(config))

    assert exit_code == code, output
    assert message in output
    assert config.read_bytes() == before


# --- File handling -----------------------------------------------------------


def test_missing_config_points_to_init(tmp_path: Path) -> None:
    code, output = _run(
        "project", "repo", "add", "web", "--path", "x", "-c", str(tmp_path / "qa.yaml")
    )
    assert code == 1
    assert "run `qa init`" in output


def test_invalid_existing_config_is_not_edited(tmp_path: Path) -> None:
    config = tmp_path / "qa.yaml"
    config.write_text("project:\n  id: Shop\n  name: Shop\n")

    code, output = _run("project", "repo", "add", "web", "--path", "x", "-c", str(config))

    assert code == 1
    assert "project.id:" in output
    assert config.read_text() == "project:\n  id: Shop\n  name: Shop\n"


@pytest.mark.parametrize("repositories", ["", "  repositories: []\n"])
def test_missing_or_empty_list_is_created(tmp_path: Path, repositories: str) -> None:
    config = tmp_path / "qa.yaml"
    config.write_text("project:\n  id: shop\n  name: Shop\n" + repositories)

    add_repository(config, "web", path="../web")

    assert [r.name for r in load_config(config).project.repositories] == ["web"]


def test_hand_written_flow_style_is_kept(tmp_path: Path) -> None:
    config = tmp_path / "qa.yaml"
    config.write_text(
        "project:\n  id: shop   # main id\n  name: Shop\n  repositories: [{name: a, path: x}]\n"
    )

    add_repository(config, "b", path="y")

    text = config.read_text()
    assert "# main id" in text
    assert [r.name for r in load_config(config).project.repositories] == ["a", "b"]


def test_file_permissions_are_kept(config: Path) -> None:
    config.chmod(0o640)
    add_repository(config, "web", path="../web")
    assert config.stat().st_mode & 0o777 == 0o640


def test_failed_write_leaves_original_and_no_temp_files(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = config.read_bytes()

    def fail(self: Path, target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        add_repository(config, "web", path="../web")

    assert config.read_bytes() == before
    assert sorted(p.name for p in config.parent.iterdir()) == [".qa", "qa.yaml", "scenarios"]


def test_duplicate_is_a_config_edit_error(config: Path) -> None:
    add_repository(config, "web", path="../web")
    with pytest.raises(ConfigEditError, match="already exists"):
        add_repository(config, "web", url="https://example.com")
