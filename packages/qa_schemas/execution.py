"""Execution metadata: one run of an Execution Plan (TASK-006, TASK-016).

Lifecycle transitions and id generation are added in TASK-036; test results
in TASK-057.
"""

from typing import Self

from pydantic import AwareDatetime, model_validator

from qa_schemas.base import Identifier, SchemaModel, StableId
from qa_schemas.enums import ExecutionMode, ExecutionStatus, TestCategory


class TestExecution(SchemaModel):
    """A single execution of a plan. All timestamps are timezone-aware."""

    __test__ = False  # not a pytest test class despite the name

    id: StableId
    project_id: Identifier
    specification_id: StableId
    plan_id: StableId
    mode: ExecutionMode
    category: TestCategory
    environment: Identifier
    status: ExecutionStatus = ExecutionStatus.PENDING
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    rerun_of: StableId | None = None
    """The execution this one repeats (``qa rerun``), if any."""

    @model_validator(mode="after")
    def _consistent_timestamps(self) -> Self:
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at must not be before created_at")
        if self.finished_at is not None:
            if not self.status.is_terminal:
                raise ValueError(
                    f"finished_at is only allowed for finished executions, "
                    f"not {self.status.value!r}"
                )
            if self.finished_at < (self.started_at or self.created_at):
                raise ValueError("finished_at must not be before started_at/created_at")
        return self
