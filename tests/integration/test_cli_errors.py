"""CLI behaviour outside the happy path: version, interrupts, internal errors (TASK-065)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from qa_cli import main
from qa_cli.main import app
from qa_core import __version__

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output == f"qa-platform {__version__}\n"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _raise(error: BaseException) -> object:
    def fail(*args: object, **kwargs: object) -> object:
        raise error

    return fail


def test_interrupt_exits_130_without_traceback(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "list_executions", _raise(KeyboardInterrupt()))

    result = runner.invoke(app, ["execution", "list"])

    assert result.exit_code == 130
    assert result.output == "\nInterrupted.\n"


def test_unexpected_error_is_one_line_with_a_hint(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("QA_DEBUG", raising=False)
    monkeypatch.setattr(main, "list_executions", _raise(ValueError("boom")))

    result = runner.invoke(app, ["execution", "list"])

    assert result.exit_code == 1
    assert result.output == (
        "Internal error: ValueError: boom\n"
        "This is a bug in qa-platform. Run again with QA_DEBUG=1 for the traceback.\n"
    )
    assert "Traceback" not in result.output


def test_debug_shows_the_original_exception(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QA_DEBUG", "1")
    monkeypatch.setattr(main, "list_executions", _raise(ValueError("boom")))

    result = runner.invoke(app, ["execution", "list"])

    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)


def test_usage_errors_are_still_reported_by_typer(project: Path) -> None:
    result = runner.invoke(app, ["project", "env", "add", "qa", "--service", "broken"])
    assert result.exit_code == 2
    assert "expected NAME=URL" in result.output
    assert "Internal error" not in result.output
