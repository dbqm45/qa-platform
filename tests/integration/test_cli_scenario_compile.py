"""`qa scenario compile` end to end (TASK-027)."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qa_cli import main
from qa_cli.main import app
from qa_core.steps.registry import StepRegistry
from qa_execution.adapters import ExecutionContext, TestAdapter
from qa_execution.registry import AdapterRegistry
from qa_schemas.compilation import CompiledSpecification
from qa_schemas.enums import StepKind

runner = CliRunner()
ROOT = Path(__file__).parents[2]

LOGIN = (ROOT / "examples/scenarios/login.feature").read_text()


def _login_registry() -> StepRegistry:
    def handler(context: Any, *values: Any) -> None: ...

    def one(context: Any, value: Any) -> None: ...

    def two(context: Any, username: Any, password: Any) -> None: ...

    registry = StepRegistry()
    a, e = StepKind.ACTION, StepKind.EXPECTATION
    registry.register("nav.login", "the login page is open", handler, kind=a, capability="browser")
    registry.register(
        "auth.sign-in", "the user signs in as {string} with password {string}", two,
        kind=a, capability="browser",
    )  # fmt: skip
    registry.register(
        "ui.dashboard", "the dashboard is shown", handler, kind=e, capability="browser"
    )
    registry.register(
        "ui.greeting", "the greeting contains {string}", one, kind=e, capability="browser"
    )
    return registry


@pytest.fixture
def project(tmp_path: Path) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path), "--id", "shop"]).exit_code == 0
    return tmp_path


def _write(project: Path, name: str, content: str) -> None:
    path = project / "scenarios" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _compile(project: Path) -> tuple[int, str]:
    result = runner.invoke(app, ["scenario", "compile", "-c", str(project / "qa.yaml")])
    return result.exit_code, result.output


def _saved(project: Path) -> dict[str, CompiledSpecification]:
    directory = project / ".qa" / "specifications"
    return {
        p.stem: CompiledSpecification.model_validate_json(p.read_text())
        for p in sorted(directory.glob("*.json"))
    }


class _FakeBrowser(TestAdapter):
    name = "fake-browser"
    capabilities = frozenset({"browser"})

    def prepare(self, context: ExecutionContext) -> None: ...

    def cleanup(self) -> None: ...

    @property
    def resource(self) -> Any:
        return None


@pytest.fixture
def with_login_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Login step definitions plus an adapter that provides their capability."""
    monkeypatch.setattr(main, "builtin_registry", _login_registry)
    monkeypatch.setattr(main, "builtin_adapters", lambda: AdapterRegistry([_FakeBrowser]))


def test_steps_without_adapter_are_unsupported(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "builtin_registry", _login_registry)
    monkeypatch.setattr(main, "builtin_adapters", AdapterRegistry)  # no adapters at all
    _write(project, "login.feature", LOGIN)

    code, output = _compile(project)

    assert code == 0  # not blocked: the scenario is fine, the platform lacks an adapter
    assert "UNSUPPORTED  login.successful-login" in output
    assert "no adapter provides the required capabilities: browser" in output
    assert not _saved(project)["login.successful-login"].status.is_executable


# --- Without step definitions (current built-in registry is empty) -----------


def test_without_step_definitions_everything_is_blocked(project: Path) -> None:
    _write(project, "login.feature", LOGIN)

    code, output = _compile(project)

    assert code == 1
    assert "BLOCKED      login.successful-login  (scenarios/login.feature:7)" in output
    assert "  4 step(s) cannot be resolved" in output
    assert 'line 8: action \'the user signs in as "alice"' in output
    assert "Compiled 1 specification from 1 file: 0 ready, 0 needs review, 1 blocked" in output
    saved = _saved(project)
    assert saved["login.successful-login"].status.value == "blocked"


# --- With step definitions ---------------------------------------------------


@pytest.mark.usefixtures("with_login_steps")
def test_ready_specification_is_saved(project: Path) -> None:
    _write(project, "auth/login.feature", LOGIN)

    code, output = _compile(project)

    assert code == 0, output
    assert "READY        auth.login.successful-login  (scenarios/auth/login.feature:7)" in output
    assert "1 ready, 0 needs review, 0 blocked, 0 unsupported" in output
    compiled = _saved(project)["auth.login.successful-login"]
    assert compiled.status.is_executable
    steps = compiled.specification.test_cases[0].steps
    assert steps[1].action == "auth.sign-in"
    assert steps[1].parameters == {"username": "alice", "password": "correct-password"}
    assert compiled.specification.required_capabilities == ("browser",)


@pytest.mark.usefixtures("with_login_steps")
def test_unresolved_steps_are_shown_once_per_outline(project: Path) -> None:
    _write(
        project,
        "outline.feature",
        "Feature: O\n  Scenario Outline: Fly <n>\n    When the user flies <n> times\n"
        "    Then the dashboard is shown\n    Examples:\n      | n |\n      | 1 |\n      | 2 |\n",
    )

    code, output = _compile(project)

    assert code == 1
    assert output.count("line 3: action 'the user flies") == 1
    assert "(in 2 test cases)" in output
    assert "1 step(s) cannot be resolved" in output


@pytest.mark.usefixtures("with_login_steps")
def test_needs_review_is_shown_but_does_not_fail(project: Path) -> None:
    _write(project, "a.feature", "Feature: A\n  Scenario: Open\n    Given the login page is open\n")

    code, output = _compile(project)

    assert code == 0
    assert "NEEDS_REVIEW a.open" in output
    assert "test case(s) without any expectation step: a.open" in output


@pytest.mark.usefixtures("with_login_steps")
def test_invalid_file_is_reported_and_others_still_compile(project: Path) -> None:
    _write(project, "login.feature", LOGIN)
    _write(project, "bad.feature", "Feature: Bad\n  Scenario:\n    Given x\n")

    code, output = _compile(project)

    assert code == 1
    assert "BLOCKED      scenarios/bad.feature  (1 error)" in output
    assert "scenarios/bad.feature:2: [scenario.missing-name] scenario has no name" in output
    assert "; 1 file with errors" in output
    assert list(_saved(project)) == ["login.successful-login"]


# --- Persistence -------------------------------------------------------------


@pytest.mark.usefixtures("with_login_steps")
def test_recompiling_unchanged_input_gives_identical_files(project: Path) -> None:
    _write(project, "login.feature", LOGIN)
    _compile(project)
    first = {p.name: p.read_bytes() for p in (project / ".qa/specifications").iterdir()}

    _compile(project)

    second = {p.name: p.read_bytes() for p in (project / ".qa/specifications").iterdir()}
    assert first == second


@pytest.mark.usefixtures("with_login_steps")
def test_stale_specifications_are_removed(project: Path) -> None:
    _write(project, "login.feature", LOGIN)
    _write(
        project, "old.feature", "Feature: Old\n  Scenario: Gone\n    Given the login page is open\n"
    )
    _compile(project)
    assert set(_saved(project)) == {"login.successful-login", "old.gone"}

    (project / "scenarios/old.feature").unlink()
    _compile(project)

    assert set(_saved(project)) == {"login.successful-login"}
    assert not list((project / ".qa/specifications").glob(".*.tmp"))


def test_saved_files_are_valid_json_documents(project: Path) -> None:
    _write(project, "login.feature", LOGIN)
    _compile(project)
    data = json.loads((project / ".qa/specifications/login.successful-login.json").read_text())
    assert data["schema_version"] == 1
    assert data["specification"]["schema_version"] == 1


def test_missing_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scenario", "compile", "-c", str(tmp_path / "qa.yaml")])
    assert result.exit_code == 1
    assert "run `qa init`" in result.output
