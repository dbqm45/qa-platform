"""Execution targets: where an execution runs (TASK-034).

Execution logic (``LocalRunner``) is separate from execution infrastructure.
Only the local target exists; remote and Kubernetes targets are post-MVP
(TASK-113, TASK-121) and will implement the same interface.
"""

from typing import Protocol

from qa_execution.runner import ExecutionRequest, LocalRunner
from qa_schemas.results import ExecutionReport


class ExecutionTarget(Protocol):
    name: str

    def execute(self, request: ExecutionRequest) -> ExecutionReport: ...


class LocalTarget:
    """Runs the execution in the current process; needs no remote services."""

    name = "local"

    def __init__(self, runner: LocalRunner) -> None:
        self._runner = runner

    def execute(self, request: ExecutionRequest) -> ExecutionReport:
        return self._runner.run(request)
