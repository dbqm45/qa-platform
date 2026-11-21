"""The runner persists execution status in the real SQLite database (TASK-036)."""

from pathlib import Path

from qa_core.storage import ExecutionRepository, ProjectRepository, open_database
from qa_execution.registry import AdapterRegistry
from qa_execution.runner import ExecutionRequest, LocalRunner
from qa_schemas.enums import ExecutionStatus
from qa_schemas.project import Environment, Project
from tests.unit.test_runner import PASSING, Browser, Http, _compiled, _plan, _steps


def _run(tmp_path: Path, *steps: str) -> str:
    db_path = tmp_path / "qa.db"
    compiled = _compiled(*steps)
    with open_database(db_path) as db:
        ProjectRepository(db).upsert(Project(id="shop", name="Shop"))
        runner = LocalRunner(
            _steps(),
            AdapterRegistry([Browser, Http]),
            evidence_root=tmp_path / "evidence",
            store=ExecutionRepository(db),
        )
        request = ExecutionRequest("shop", compiled, _plan(compiled), Environment(name="local"))
        return runner.run(request).execution.id


def test_status_survives_reopening_the_database(tmp_path: Path) -> None:
    passed = _run(tmp_path, *PASSING)
    failed = _run(tmp_path, 'When the user does "pass"', 'Then outcome "fail"')

    with open_database(tmp_path / "qa.db") as db:
        repo = ExecutionRepository(db)
        stored_passed, stored_failed = repo.get(passed), repo.get(failed)
        history = repo.list_for_project("shop")

    assert stored_passed is not None and stored_failed is not None
    assert stored_passed.status is ExecutionStatus.PASSED
    assert stored_failed.status is ExecutionStatus.FAILED  # never reported as successful
    assert stored_failed.started_at is not None and stored_failed.finished_at is not None
    assert {e.id for e in history} == {passed, failed}
