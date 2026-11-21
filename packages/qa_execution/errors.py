"""Execution errors and their classification (TASK-038).

Step implementations signal outcomes with these exceptions:

- ``StepFailure`` -- the application did not behave as expected -> FAILED;
- a ``ClassifiedError`` subclass -- the test could not be evaluated -> ERROR
  with an explicit classification;
- anything else -> ERROR / TEST_IMPLEMENTATION_ERROR, so an unexpected
  exception (a bug in a step or the platform) is never reported as an
  ordinary test failure.
"""

from qa_schemas.enums import ExecutionStatus, FailureClassification

C = FailureClassification


class StepFailure(Exception):
    """An expectation was not met. The only exception that yields FAILED."""

    def __init__(self, message: str, classification: C = C.APPLICATION_BUG) -> None:
        super().__init__(message)
        self.classification = classification


class ClassifiedError(Exception):
    """The test could not be evaluated; ``classification`` says why."""

    classification: C = C.TEST_IMPLEMENTATION_ERROR


class TestEnvironmentError(ClassifiedError):
    """The environment is unreachable or misconfigured."""

    __test__ = False
    classification = C.ENVIRONMENT_ERROR


class TestDataError(ClassifiedError):
    __test__ = False
    classification = C.TEST_DATA_ERROR


class DependencyError(ClassifiedError):
    classification = C.DEPENDENCY_ERROR


class RootCause:
    """Marker for problems an adapter reports at the end of a test case that explain
    why a step failed (a blocked request, an unmocked call). The runner reports them
    instead of that step failure, which is kept as a note."""


class RequirementAmbiguityError(ClassifiedError):
    classification = C.REQUIREMENT_AMBIGUITY


_ENVIRONMENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
)


def classify(error: BaseException) -> tuple[ExecutionStatus, C]:
    """Map an exception raised while running a step or hook to status and classification."""
    if isinstance(error, StepFailure):
        return ExecutionStatus.FAILED, error.classification
    if isinstance(error, ClassifiedError):
        return ExecutionStatus.ERROR, error.classification
    if isinstance(error, _ENVIRONMENT_EXCEPTIONS):
        return ExecutionStatus.ERROR, C.ENVIRONMENT_ERROR
    return ExecutionStatus.ERROR, C.TEST_IMPLEMENTATION_ERROR


def describe(error: BaseException) -> str:
    """Readable one-line message, falling back to the exception type."""
    text = str(error).strip()
    return text if text else type(error).__name__
