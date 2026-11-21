"""The adapter contract (TASK-029).

An adapter owns one testing resource (a browser, an HTTP client, ...) and its
lifecycle. It does not run steps: the runner executes steps one by one, and a
step implementation obtains the resource for the capability it needs from the
adapter that provides it. This lets one test case combine several adapters
(FULL mode) and keeps the engine independent of any testing framework.

Lifecycle per execution::

    adapter = AdapterClass()
    problems = adapter.validate(specification)       # before anything starts
    adapter.prepare(context)                          # e.g. launch the browser
    for each test case:
        adapter.start_test_case(test_case)
        ... steps use adapter.resource ...
        adapter.finish_test_case(test_case, passed)
        evidence = adapter.collect_evidence(test_case)
    adapter.cleanup()                                 # always, also after failures
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from qa_core.redaction import Redactor, resolve_references
from qa_execution.mocks import MockService
from qa_schemas.evidence import EvidenceReference
from qa_schemas.plan import ExecutionSettings
from qa_schemas.project import Environment
from qa_schemas.specification import TestCase, TestSpecification


@dataclass(frozen=True)
class ExecutionContext:
    """What an adapter needs to know about the execution it takes part in."""

    execution_id: str
    environment: Environment
    settings: ExecutionSettings
    evidence_dir: Path
    """Directory for this execution's evidence; adapters write only below it."""
    adapter_config: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    """Settings from ``qa.yaml`` ``adapters:``, by adapter name."""
    redactor: Redactor = field(default_factory=Redactor)
    """Masks this execution's secrets; adapters apply it to evidence they write."""
    secret_source: Mapping[str, str] = field(default_factory=dict)
    """Where ``${NAME}`` secrets come from (normally the process environment)."""
    builtins: dict[str, str] = field(default_factory=dict)
    """``${RUN_ID}`` always; ``${UNIQUE}`` while a test case runs (set by the runner)."""
    allow_writes: bool = False
    mocks: Mapping[str, MockService] = field(default_factory=dict)
    """Services answered from mock files in this execution, by service name."""

    @property
    def read_only(self) -> bool:
        """Adapters must not change data: the environment is protected (TASK-056)."""
        return self.environment.protected and not self.allow_writes

    def config_for(self, adapter: str) -> Mapping[str, Any]:
        return self.adapter_config.get(adapter, {})

    def resolve(self, text: str) -> str:
        """Resolve ``${NAME}``: platform values (``RUN_ID``, ``UNIQUE``), then
        environment ``variables``, then secrets.

        Raises ``MissingSecretError`` for an unknown name.
        """
        return resolve_references(
            text, self.secret_source, self.redactor, self.environment.variables, self.builtins
        )


def evidence_folder(test_case_id: str) -> str:
    """Filesystem-safe folder for a test case's evidence (``:`` is not allowed everywhere)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", test_case_id)


class AdapterNotPreparedError(RuntimeError):
    """The adapter's resource was requested before ``prepare`` or after ``cleanup``."""


class TestAdapter(ABC):
    """Base class for all adapters.

    Subclasses must set ``name`` and ``capabilities`` and implement
    ``prepare``, ``cleanup`` and ``resource``. The other hooks are optional.
    """

    __test__ = False  # not a pytest test class despite the name

    name: ClassVar[str]
    """Unique adapter name, e.g. ``playwright`` (used in Execution Plans)."""
    capabilities: ClassVar[frozenset[str]]
    """What step implementations can obtain from this adapter, e.g. ``{"browser"}``."""

    def get_capabilities(self) -> frozenset[str]:
        return self.capabilities

    def validate(self, specification: TestSpecification) -> list[str]:
        """Problems that prevent running ``specification`` with this adapter; empty if none.

        Called before ``prepare``; must not start anything.
        """
        return []

    @abstractmethod
    def prepare(self, context: ExecutionContext) -> None:
        """Acquire the resource (launch a browser, open a client)."""

    def start_test_case(self, test_case: TestCase) -> None:  # noqa: B027 - optional hook
        """Called before the first step of each test case."""

    def finish_test_case(self, test_case: TestCase, passed: bool) -> None:  # noqa: B027
        """Called after the last step of each test case, whatever its outcome."""

    def collect_evidence(self, test_case: TestCase) -> list[EvidenceReference]:
        """Evidence written for ``test_case``. Must never change the test outcome."""
        return []

    @abstractmethod
    def cleanup(self) -> None:
        """Release everything acquired in ``prepare``. Must be safe to call more than once."""

    @property
    @abstractmethod
    def resource(self) -> Any:
        """The object step implementations use; raises ``AdapterNotPreparedError`` when
        the adapter is not prepared."""
