"""qa summary: one overview of several qa test --json runs (TASK-128)."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qa_cli.main import app
from qa_reporting.summary import render_markdown, render_text
from qa_schemas.summary import RunSummary

runner = CliRunner()


def _summary(scenario: str, **fields: Any) -> RunSummary:
    data: dict[str, Any] = {
        "project": "shop", "scenario": scenario, "environment": "local", "ok": True,
        "counts": {"passed": 2}, "specifications": [],
    } | fields  # fmt: skip
    return RunSummary.model_validate(data)


PASSED = _summary("scenarios/api.feature")
FAILED = _summary(
    "scenarios/login.feature",
    ok=False,
    counts={"passed": 1, "failed": 1, "not_executed": 1},
    mocked=["api"],
    specifications=[
        {"id": "login.ok", "source": "scenarios/login.feature:3", "compilation": "ready",
         "status": "failed", "execution_id": "e1", "report": ".qa/executions/e1/report.html",
         "failures": [{"test_case_id": "login.ok", "status": "failed",
                       "classification": "application_bug", "step": 4,
                       "message": "the page does not show 'Welcome | Alice'"}]},
        {"id": "login.dance", "source": "scenarios/login.feature:9", "compilation": "blocked",
         "status": None, "problem": "not executed (blocked): 1 step(s) cannot be resolved"},
    ],
)  # fmt: skip
INVALID = _summary(
    "scenarios/broken.feature", ok=False, counts={},
    errors=[{"location": "scenarios/broken.feature:2", "code": "scenario.no-steps",
             "message": "scenario has no steps"}],
)  # fmt: skip


def test_text() -> None:
    assert render_text([PASSED, FAILED, INVALID]) == (
        "OK    scenarios/api.feature on local: 2 passed\n"
        "FAIL  scenarios/login.feature on local (mocked: api): 1 passed, 1 failed, "
        "1 not executed\n"
        "      login.ok, step 4: application_bug: the page does not show 'Welcome | Alice'\n"
        "      scenarios/login.feature:9: not_executed: not executed (blocked): "
        "1 step(s) cannot be resolved\n"
        "FAIL  scenarios/broken.feature on local: validation errors\n"
        "      scenarios/broken.feature:2: scenario.no-steps: scenario has no steps\n"
        "\n3 scenario files: 3 passed, 1 failed, 1 not executed -- NOT all passed\n"
    )


def test_markdown() -> None:
    page = render_markdown([PASSED, FAILED])
    assert page.startswith("## QA results: NOT all passed\n\n2 scenario files: 3 passed")
    assert "| ✅ | `scenarios/api.feature` | local | 2 passed |" in page
    assert "| ❌ | `scenarios/login.feature` | local (mocked: api) |" in page
    # a | in a message must not break the table
    assert (
        "| `login.ok, step 4` | application_bug | the page does not show 'Welcome \\| Alice' |"
        in page
    )
    assert "- `login.ok`: `.qa/executions/e1/report.html`" in page
    assert render_markdown([PASSED]).startswith("## QA results: all passed")


def test_long_messages_are_shortened() -> None:
    long = _summary("s.feature", ok=False, errors=[
        {"location": "s.feature:1", "code": "c", "message": "x " * 400}])  # fmt: skip
    line = next(x for x in render_text([long]).splitlines() if "s.feature:1" in x)
    assert len(line) < 360 and line.endswith("…")


@pytest.fixture
def files(tmp_path: Path) -> list[Path]:
    paths = []
    for summary in (PASSED, FAILED):
        path = tmp_path / f"{Path(summary.scenario).stem}.json"
        path.write_text(summary.model_dump_json())
        paths.append(path)
    return paths


def test_cli_exit_codes(files: list[Path]) -> None:
    both = runner.invoke(app, ["summary", *map(str, files)])
    only_passed = runner.invoke(app, ["summary", "--markdown", str(files[0])])
    assert both.exit_code == 1 and "NOT all passed" in both.output
    assert only_passed.exit_code == 0 and only_passed.output.startswith("## QA results: all")


@pytest.mark.parametrize(
    ("content", "message"),
    [(None, "cannot read"), ("{}", "is not a qa test --json summary"),
     ("not json", "is not a qa test --json summary")],
)  # fmt: skip
def test_cli_bad_files(tmp_path: Path, content: str | None, message: str) -> None:
    path = tmp_path / "s.json"
    if content is not None:
        path.write_text(content)
    result = runner.invoke(app, ["summary", str(path)])
    assert result.exit_code == 1
    assert message in result.output


def test_cli_reads_real_qa_test_output(tmp_path: Path) -> None:
    """The format qa test --json writes is what qa summary reads (schema round trip)."""
    path = tmp_path / "s.json"
    path.write_text(json.dumps(json.loads(FAILED.model_dump_json())))
    assert "login.ok, step 4" in runner.invoke(app, ["summary", str(path)]).output
