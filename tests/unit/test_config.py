"""Tests for loading qa.yaml (TASK-012)."""

from pathlib import Path

import pytest

from qa_core.config import CONFIG_FILENAME, ConfigError, load_config, parse_config
from qa_schemas.base import IDENTIFIER_PATTERN, PATTERN_DESCRIPTIONS
from qa_schemas.config import CONFIG_SCHEMA_VERSION, ProjectConfig

ROOT = Path(__file__).parents[2]
EXAMPLE = ROOT / "examples" / CONFIG_FILENAME

MINIMAL = "project:\n  id: shop\n  name: Shop\n"


def _issues(text: str) -> list[str]:
    with pytest.raises(ConfigError) as info:
        parse_config(text)
    return info.value.issues


# --- Valid configuration -----------------------------------------------------


def test_example_config_loads_into_typed_models() -> None:
    config = load_config(EXAMPLE)

    assert isinstance(config, ProjectConfig)
    assert config.project.id == "shop"
    assert config.project.default_environment == "local"
    staging = config.project.environment("staging")
    assert staging is not None
    assert staging.timeout_seconds == 60
    assert [r.name for r in config.project.repositories] == ["web", "api"]


def test_example_scenario_dir_exists_next_to_config() -> None:
    config = load_config(EXAMPLE)
    assert (EXAMPLE.parent / config.project.scenario_dir).is_dir()


def test_minimal_config_uses_defaults() -> None:
    config = parse_config(MINIMAL)
    assert config.version == CONFIG_SCHEMA_VERSION
    assert config.project.scenario_dir == Path("scenarios")
    assert config.project.environments == ()


def test_load_config_from_file(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILENAME
    path.write_text(MINIMAL, encoding="utf-8")
    assert load_config(path).project.name == "Shop"


# --- File errors -------------------------------------------------------------


def test_missing_file(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILENAME
    with pytest.raises(ConfigError, match="file not found; run `qa init`") as info:
        load_config(path)
    assert info.value.path == path
    assert str(path) in str(info.value)


def test_directory_instead_of_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="is a directory"):
        load_config(tmp_path)


def test_non_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILENAME
    path.write_bytes(b"project: \xff\xfe")
    with pytest.raises(ConfigError, match="not valid UTF-8"):
        load_config(path)


# --- YAML errors -------------------------------------------------------------


def test_empty_file() -> None:
    assert _issues("") == ["file is empty; expected at least a 'project' section"]
    assert _issues("# only a comment\n") == _issues("")


@pytest.mark.parametrize(("text", "kind"), [("- a\n", "list"), ("hello\n", "str")])
def test_top_level_must_be_mapping(text: str, kind: str) -> None:
    assert _issues(text) == [f"top level must be a mapping, got {kind}"]


def test_syntax_error_reports_line_and_column() -> None:
    [issue] = _issues("project:\n  id: shop\n   name: Shop\n")
    assert issue.startswith("line 3, column ")
    assert "invalid YAML" in issue


def test_duplicate_keys_are_rejected() -> None:
    [issue] = _issues("project:\n  id: shop\n  name: A\n  name: B\n")
    assert issue == "line 4, column 3: invalid YAML: duplicate key 'name'"


def test_unsafe_yaml_tags_are_rejected() -> None:
    [issue] = _issues("project: !!python/object/apply:os.system ['echo hi']\n")
    assert "invalid YAML" in issue


# --- Validation errors -------------------------------------------------------


def test_all_validation_errors_are_reported_with_locations() -> None:
    issues = _issues(
        "version: 2\n"
        "project:\n"
        "  id: Shop\n"
        "  environments:\n"
        "    - name: local\n"
        "      timeout_seconds: abc\n"
    )
    assert "version: Input should be 1 (got 2)" in issues
    assert "project.name: Field required" in issues
    assert f"project.id: {PATTERN_DESCRIPTIONS[IDENTIFIER_PATTERN]} (got 'Shop')" in issues
    assert any(i.startswith("project.environments[0].timeout_seconds:") for i in issues)


def test_unknown_field_suggests_closest_name() -> None:
    issues = _issues(MINIMAL + "  enviroments: []\n")
    assert issues == ["project.enviroments: unknown field; did you mean 'environments'?"]


def test_unknown_field_without_close_match() -> None:
    assert _issues(MINIMAL + "  colour: red\n") == ["project.colour: unknown field"]


def test_cross_reference_error_is_readable() -> None:
    issues = _issues(MINIMAL + "  default_environment: prod\n")
    assert issues == ["project: default_environment 'prod' is not defined; known environments: []"]


# --- No credentials ----------------------------------------------------------


@pytest.mark.parametrize("key", ["password", "token", "api_key", "secret"])
def test_credential_fields_have_nowhere_to_go(key: str) -> None:
    assert _issues(MINIMAL + f"  {key}: hunter2\n") == [f"project.{key}: unknown field"]


def test_url_with_credentials_is_rejected_without_echoing_it() -> None:
    text = (
        MINIMAL + "  environments:\n    - name: qa\n      base_url: https://bob:hunter2@qa.local\n"
    )
    with pytest.raises(ConfigError) as info:
        parse_config(text)
    message = str(info.value)
    assert "must not contain credentials" in message
    assert "hunter2" not in message


def test_long_inputs_are_truncated() -> None:
    [issue] = _issues("project:\n  id: " + "X" * 500 + "\n  name: Shop\n")
    assert issue.endswith("...)")
    assert len(issue) < 300
