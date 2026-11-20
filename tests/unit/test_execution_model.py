"""Tests for the TestExecution model and migration constraints."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from qa_core.storage.migrations import MIGRATIONS
from qa_schemas.enums import ExecutionMode, ExecutionStatus, TestCategory
from qa_schemas.execution import TestExecution

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _execution(**overrides: Any) -> TestExecution:
    data: dict[str, Any] = {
        "id": "exec-1",
        "project_id": "shop",
        "specification_id": "login.successful-login",
        "plan_id": "login.successful-login.fe.local",
        "mode": "fe",
        "category": "functional",
        "environment": "local",
        "created_at": T0,
    }
    return TestExecution.model_validate(data | overrides)


def test_defaults_to_pending() -> None:
    execution = _execution()
    assert execution.status is ExecutionStatus.PENDING
    assert execution.started_at is None
    assert execution.finished_at is None


def test_finished_execution() -> None:
    execution = _execution(
        status="passed", started_at=T0 + timedelta(seconds=1), finished_at=T0 + timedelta(seconds=5)
    )
    assert execution.status is ExecutionStatus.PASSED


def test_json_round_trip() -> None:
    execution = _execution(status="running", started_at=T0)
    assert TestExecution.model_validate_json(execution.model_dump_json()) == execution


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        _execution(created_at=datetime(2026, 1, 1, 12, 0))


def test_started_before_created_is_rejected() -> None:
    with pytest.raises(ValidationError, match="started_at must not be before created_at"):
        _execution(started_at=T0 - timedelta(seconds=1))


@pytest.mark.parametrize("status", ["pending", "running"])
def test_finished_at_requires_terminal_status(status: str) -> None:
    with pytest.raises(ValidationError, match="only allowed for finished executions"):
        _execution(status=status, finished_at=T0)


def test_finished_before_started_is_rejected() -> None:
    with pytest.raises(ValidationError, match="finished_at must not be before"):
        _execution(status="failed", started_at=T0 + timedelta(seconds=5), finished_at=T0)


# --- Migration CHECK constraints match the enums -----------------------------


def _allowed_values(column: str) -> set[str]:
    sql = "\n".join(MIGRATIONS)
    match = re.search(rf"\b{column}\s+TEXT NOT NULL CHECK \({column} IN \((.*?)\)\)", sql, re.S)
    assert match, f"no CHECK constraint for {column}"
    return set(re.findall(r"'([a-z_]+)'", match.group(1)))


@pytest.mark.parametrize(
    ("column", "enum"),
    [("mode", ExecutionMode), ("category", TestCategory), ("status", ExecutionStatus)],
)
def test_check_constraints_match_enums(column: str, enum: type[ExecutionMode]) -> None:
    assert _allowed_values(column) == {member.value for member in enum}
