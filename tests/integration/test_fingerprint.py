"""Execution fingerprints and qa execution compare (TASK-061)."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from qa_cli.main import app

runner = CliRunner()

HEALTH = """\
Feature: Health
  Scenario Outline: Health <n>
    When the client sends GET "/health"
    Then the response status is <status>

    Examples:
      | n | status |
      | 1 | 200    |
      | 2 | 200    |
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=qa@example.com", "-c", "user.name=QA", *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip


@pytest.fixture
def app_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "shop-web"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "app.py").write_text("print('v1')\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "v1")
    return repo


@pytest.fixture
def project(
    tmp_path: Path, app_repo: Path, shop_server: Any, monkeypatch: pytest.MonkeyPatch
) -> Path:
    root = tmp_path / "tests"
    assert runner.invoke(app, ["init", str(root), "--id", "shop"]).exit_code == 0
    config = root / "qa.yaml"
    data = yaml.safe_load(config.read_text())
    data["project"]["repositories"] = [
        {"name": "web", "path": "../shop-web"},
        {"name": "api", "url": "https://example.com/org/shop-api"},
    ]
    data["project"]["environments"] = [{
        "name": "app", "services": {"api": f"{shop_server.url}/api"},
        "headers": {"X-Api-Key": "${SHOP_API_KEY}"},
    }]  # fmt: skip
    data["project"]["default_environment"] = "app"
    config.write_text(yaml.safe_dump(data))
    (root / "scenarios" / "health.feature").write_text(HEALTH)
    monkeypatch.setenv("SHOP_API_KEY", "first-key-value")
    monkeypatch.chdir(root)
    return root


def _run() -> str:
    output = runner.invoke(app, ["test", "-s", "health.feature"]).output
    return output.split("execution ", 1)[1].split(":", 1)[0]


def _compare(a: str, b: str) -> tuple[int, str]:
    result = runner.invoke(app, ["execution", "compare", a, b])
    return result.exit_code, result.output


def test_same_inputs_give_the_same_fingerprint(project: Path, monkeypatch: Any) -> None:
    first = _run()
    monkeypatch.setenv("SHOP_API_KEY", "rotated-key-value")  # secret values do not count
    second = _run()

    code, output = _compare(first, second)

    assert code == 0
    assert output.startswith("Same inputs (sha256:")
    results = (project / ".qa" / "executions" / second / "results.json").read_text()
    assert "rotated-key-value" not in results and "first-key-value" not in results


def test_repository_commit_and_uncommitted_changes(project: Path, app_repo: Path) -> None:
    v1 = _git(app_repo, "rev-parse", "HEAD")
    first = _run()
    (app_repo / "app.py").write_text("print('v2')\n")
    dirty = _run()
    _git(app_repo, "commit", "-q", "-am", "v2")
    v2 = _git(app_repo, "rev-parse", "HEAD")
    committed = _run()

    shown = runner.invoke(app, ["execution", "show", first]).output
    assert f"Repository    web @ {v1}" in shown
    assert "Repository    api @ unknown" in shown  # url only: no local checkout
    assert "Fingerprint   sha256:" in shown
    assert _compare(first, dirty) == (
        1, f"{first} and {dirty} differ in:\n  repository web: {v1[:12]} -> {v1[:12]}+dirty\n",
    )  # fmt: skip
    assert f"repository web: {v1[:12]} -> {v2[:12]}" in _compare(first, committed)[1]


def test_environment_and_test_case_changes_are_named(project: Path) -> None:
    first = _run()
    config = project / "qa.yaml"
    config.write_text(config.read_text().replace("name: app", "name: app\n    timeout_seconds: 7"))
    scenario = project / "scenarios" / "health.feature"
    scenario.write_text(HEALTH.replace("| 2 | 200    |", "| 2 | 201    |"))
    second = _run()

    code, output = _compare(first, second)

    assert code == 1
    lines = output.splitlines()[1:]
    assert "  environment" in lines
    assert "  plan" in lines  # the step timeout comes from the environment
    assert "  specification" in lines  # the scenario's content hash
    assert "  test case health.health-n:2" in lines
    assert "  test case health.health-n:1" not in lines  # unchanged


def test_rerun_names_what_changed_since_the_original(project: Path) -> None:
    scenario = project / "scenarios" / "health.feature"
    scenario.write_text(HEALTH.replace("| 2 | 200    |", "| 2 | 201    |"))
    original = _run()  # case 2 fails
    scenario.write_text(HEALTH)
    config = project / "qa.yaml"
    config.write_text(config.read_text().replace("name: app", "name: app\n    timeout_seconds: 7"))

    output = runner.invoke(app, ["rerun", "--failed-only", original]).output

    assert f"Warning: since execution {original} changed: environment; plan" in output
    rerun = next(
        line.split()[1].rstrip(":")
        for line in output.splitlines()
        if line.startswith("  execution ")
    )
    # only case 2 ran again; it is compared, the missing case 1 is listed
    _, compared = _compare(original, rerun)
    assert "test case health.health-n:2" in compared
    assert f"test case health.health-n:1 only in {original}" in compared


def test_compare_needs_fingerprints(project: Path) -> None:
    first, second = _run(), _run()
    path = project / ".qa" / "executions" / first / "results.json"
    data = json.loads(path.read_text())
    del data["fingerprint"]
    path.write_text(json.dumps(data))

    code, output = _compare(first, second)

    assert code == 1
    assert f"execution {first} has no fingerprint" in output


def test_repositories_are_only_read(project: Path, app_repo: Path) -> None:
    (app_repo / "app.py").write_text("print('changed, not committed')\n")

    def snapshot() -> dict[str, tuple[int, bytes]]:
        return {
            str(p.relative_to(app_repo)): (p.stat().st_mtime_ns, p.read_bytes())
            for p in sorted(app_repo.rglob("*")) if p.is_file()
        }  # fmt: skip

    before = snapshot()
    _run()
    assert snapshot() == before  # not even .git/index was refreshed
