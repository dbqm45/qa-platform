"""`qa scenario validate` end to end (TASK-022)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from qa_cli.main import app
from qa_core.scenarios.service import validate_project

runner = CliRunner()
ROOT = Path(__file__).parents[2]

GOOD = "Feature: Login\n  Scenario: Ok\n    Given the page is open\n    Then it works\n"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    return tmp_path


def _write(project: Path, name: str, content: str | bytes) -> None:
    path = project / "scenarios" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)


def _validate(project: Path) -> tuple[int, list[str]]:
    result = runner.invoke(app, ["scenario", "validate", "-c", str(project / "qa.yaml")])
    return result.exit_code, result.output.splitlines()


def test_example_project_is_valid() -> None:
    result = runner.invoke(app, ["scenario", "validate", "-c", str(ROOT / "examples/qa.yaml")])
    assert result.exit_code == 0, result.output
    assert result.output == "Validated 4 files, 10 scenarios: 0 errors, 0 warnings\n"


def test_valid_scenarios(project: Path) -> None:
    _write(project, "a.feature", GOOD)
    _write(project, "nested/b.feature", GOOD.replace("Ok", "Also ok"))

    code, lines = _validate(project)

    assert code == 0
    assert lines == ["Validated 2 files, 2 scenarios: 0 errors, 0 warnings"]


def test_errors_are_listed_with_locations_and_fail(project: Path) -> None:
    _write(project, "a.feature", GOOD)
    _write(project, "b.feature", "Feature: B\n  Scenario:\n    Given x\n")
    _write(project, "c.feature", "Feature: C\n  Scenario: S\n    Given x\n  oops\n")

    code, lines = _validate(project)

    assert code == 1
    assert lines[0] == "scenarios/b.feature:2: error [scenario.missing-name] scenario has no name"
    assert lines[1].startswith("scenarios/c.feature:4:3: error [syntax] unexpected 'oops'")
    assert lines[-1] == "Validated 3 files, 2 scenarios: 2 errors, 0 warnings"


def test_warnings_do_not_fail(project: Path) -> None:
    _write(project, "a.feature", "Feature: Empty\n")

    code, lines = _validate(project)

    assert code == 0
    assert (
        lines[0] == "scenarios/a.feature:1: warning [feature.no-scenarios] Feature has no scenarios"
    )
    assert lines[-1] == "Validated 1 file, 0 scenarios: 0 errors, 1 warning"


def test_no_scenario_files_is_a_warning(project: Path) -> None:
    code, lines = _validate(project)
    assert code == 0
    assert lines[0] == "scenarios: warning [discovery.no-files] no scenario files (*.feature) found"


def test_discovery_problems_are_errors(project: Path) -> None:
    _write(project, "good.feature", GOOD)
    _write(project, "latin1.feature", "Feature: Café\n".encode("latin-1"))

    code, lines = _validate(project)

    assert code == 1
    assert lines[0].startswith(
        "scenarios/latin1.feature: error [discovery] file is not valid UTF-8"
    )
    assert lines[-1] == "Validated 1 file, 1 scenario: 1 error, 0 warnings"


def test_missing_scenario_directory(project: Path) -> None:
    (project / "scenarios").rmdir()
    code, lines = _validate(project)
    assert code == 1
    assert lines[0] == "scenarios: error [discovery] directory does not exist"


def test_issues_are_sorted_by_file_and_line(project: Path) -> None:
    _write(project, "z.feature", "Feature:\n  Scenario:\n    Given x\n")
    _write(project, "a.feature", "Feature: A\n  Scenario: S\n  Scenario: S\n    Given x\n")

    report = validate_project(project / "qa.yaml")

    keys = [(str(i.path), i.line or 0) for i in report.issues]
    assert keys == sorted(keys)
    assert {str(i.path) for i in report.issues} == {"scenarios/a.feature", "scenarios/z.feature"}


def test_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scenario", "validate", "-c", str(tmp_path / "qa.yaml")])
    assert result.exit_code == 1
    assert "run `qa init`" in result.output


def test_uses_qa_yaml_in_current_directory(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(project, "a.feature", GOOD)
    monkeypatch.chdir(project)
    result = runner.invoke(app, ["scenario", "validate"])
    assert result.exit_code == 0, result.output


def test_scenario_dir_is_relative_to_config_not_cwd(
    project: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(project, "a.feature", GOOD)
    monkeypatch.chdir(tmp_path_factory.mktemp("elsewhere"))
    code, lines = _validate(project)
    assert code == 0
    assert lines == ["Validated 1 file, 1 scenario: 0 errors, 0 warnings"]
