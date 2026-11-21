"""`qa execution list` / `qa execution show` (TASK-063)."""

from pathlib import Path

from typer.testing import CliRunner

from qa_cli.main import app
from tests.integration import test_cli_test as cli

project = cli.project  # reuse the initialized-project fixture
runner = CliRunner()


def _qa(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def _two_executions(project: Path) -> tuple[str, str]:
    cli._write(project, cli.LOGIN + "\n" + cli.WRONG)
    _, output = _qa("test", "-s", "login.feature")
    paths = [line.rsplit("-> ", 1)[1] for line in output.splitlines() if "-> " in line]
    passed, failed = (Path(p).parent.name for p in paths)
    return passed, failed


def test_list_without_executions(project: Path) -> None:
    assert _qa("execution", "list") == (0, "No executions yet; run `qa test`.\n")


def test_list_most_recent_first(project: Path) -> None:
    passed, failed = _two_executions(project)

    code, output = _qa("execution", "list")

    lines = output.splitlines()
    assert code == 0
    assert [line.split()[0] for line in lines] == [failed, passed]
    assert "FAILED" in lines[0] and "login.wrong-password-shows-the-dashboard" in lines[0]
    assert "PASSED" in lines[1] and " app " in lines[1]
    assert _qa("execution", "list", "--limit", "1")[1].count("\n") == 1


def test_show_failed_execution(project: Path) -> None:
    _, failed = _two_executions(project)

    code, output = _qa("execution", "show", failed)

    assert code == 0
    assert f"Execution     {failed}" in output
    assert "Status        FAILED" in output
    assert (
        "Plan          login.wrong-password-shows-the-dashboard.fe.app (fe, functional)" in output
    )
    assert "  FAILED    Wrong password shows the dashboard" in output
    assert "application_bug: the page does not show 'Welcome'" in output
    assert f"Report:  .qa/executions/{failed}/report.html" in output
    assert f"Log:     .qa/executions/{failed}/execution.log" in output


def test_show_accepts_a_unique_prefix(project: Path) -> None:
    passed, failed = _two_executions(project)
    differs_at = next(i for i, (a, b) in enumerate(zip(passed, failed, strict=True)) if a != b)

    code, output = _qa("execution", "show", passed[: differs_at + 1])

    assert code == 0, output
    assert f"Execution     {passed}" in output


def test_ambiguous_and_unknown_ids(project: Path) -> None:
    _two_executions(project)
    code, output = _qa("execution", "show", "20")
    assert code == 1
    assert "'20' matches 2 executions" in output
    code, output = _qa("execution", "show", "nope")
    assert code == 1
    assert "no execution matches 'nope'" in output


def test_show_interrupted_execution_without_results(project: Path) -> None:
    passed, _ = _two_executions(project)
    (project / ".qa" / "executions" / passed / "results.json").unlink()

    code, output = _qa("execution", "show", passed)

    assert code == 0
    assert "No results recorded (the execution may have been interrupted)." in output
    assert "Results: not available" in output


def test_log_file_never_contains_the_password(project: Path) -> None:
    passed, _ = _two_executions(project)
    log = (project / ".qa" / "executions" / passed / "execution.log").read_text()
    assert "correct-password" not in log
    assert '"event": "step-finished"' in log


def test_results_written_before_schema_version_still_load(project: Path) -> None:
    """results.json from before TASK-060 has no schema_version; it reads as version 1."""
    import json

    _, failed = _two_executions(project)
    path = project / ".qa" / "executions" / failed / "results.json"
    data = json.loads(path.read_text())
    assert data.pop("schema_version") == 1
    path.write_text(json.dumps(data))

    code, output = _qa("execution", "show", failed)

    assert code == 0
    assert "application_bug: the page does not show 'Welcome'" in output
