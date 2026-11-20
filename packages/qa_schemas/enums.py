"""Central definitions of all platform status, mode and category values.

This is the only module allowed to define these values. Other modules import
them from here instead of declaring their own (enforced by a unit test).

Enum values are lowercase strings so they serialize naturally to JSON/YAML and
match CLI arguments (e.g. ``--mode full``). Parsing is case-sensitive.
"""

from enum import StrEnum, unique


@unique
class CompilationStatus(StrEnum):
    """Outcome of compiling a scenario into a Test Specification (TASK-026)."""

    READY = "ready"
    """All steps resolved; the specification can be executed."""
    NEEDS_REVIEW = "needs_review"
    """Compiled, but something requires human confirmation before execution."""
    BLOCKED = "blocked"
    """Cannot be executed until a problem is fixed (e.g. unresolved step)."""
    UNSUPPORTED = "unsupported"
    """Uses constructs or capabilities the platform does not support."""

    @property
    def is_executable(self) -> bool:
        """Only READY specifications may be executed."""
        return self is CompilationStatus.READY


@unique
class ExecutionStatus(StrEnum):
    """Lifecycle state of an execution or a single test result (TASK-036)."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    """The application under test did not meet an expected result."""
    ERROR = "error"
    """The test could not be evaluated (environment, test code, internal error)."""
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Whether the execution has finished and its status can no longer change."""
        return self not in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING)


@unique
class ExecutionMode(StrEnum):
    """Which parts of the system under test are exercised (TASK-010)."""

    FE = "fe"
    """Frontend only, through the browser."""
    BE = "be"
    """Backend/API only, no browser."""
    FULL = "full"
    """Frontend and backend together."""
    CONTRACT = "contract"
    """API contracts, without the full application stack."""


@unique
class TestCategory(StrEnum):
    """What kind of quality is verified; independent of ExecutionMode (TASK-011)."""

    __test__ = False  # not a pytest test class despite the name

    FUNCTIONAL = "functional"
    VISUAL = "visual"
    ACCESSIBILITY = "accessibility"
    PERFORMANCE = "performance"
    SECURITY = "security"
    CONTRACT = "contract"


@unique
class StepKind(StrEnum):
    """Role of a step in a test case, independent of the source format (TASK-008).

    Gherkin mapping: Given -> PRECONDITION, When -> ACTION, Then -> EXPECTATION.
    """

    PRECONDITION = "precondition"
    ACTION = "action"
    EXPECTATION = "expectation"


@unique
class DependencyMode(StrEnum):
    """How an external dependency is provided during execution (TASK-009)."""

    REAL = "real"
    MOCK = "mock"
