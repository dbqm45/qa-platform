"""Hard time limits for steps, hooks and cleanup (TASK-067, TASK-068).

Adapters enforce their own timeouts (Playwright operations, waiting
assertions, HTTP requests) and produce the best messages, so hard limits are
set slightly above the step timeout and act as a safety net for code that
waits forever: custom steps, ``page.evaluate`` loops, hung hooks.

A limit interrupts the running Python code with ``SIGALRM``. This works only
on POSIX systems and in the main thread; elsewhere :func:`deadline` does not
interrupt, and only adapter timeouts and the execution deadline checked
between steps apply.
"""

import signal
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType

from qa_execution.errors import ClassifiedError
from qa_schemas.enums import FailureClassification

GRACE_SECONDS = 2.0
"""Added to the step timeout so adapter timeouts, with better messages, fire first."""
PREPARE_SECONDS = 60.0
"""Minimum time an adapter gets to start (e.g. launching a browser)."""
HOOK_SECONDS = 10.0
"""Minimum time for per-test-case hooks and evidence collection."""
CLEANUP_SECONDS = 30.0
"""Each adapter's cleanup is limited independently of the execution deadline."""


class StepTimeoutError(ClassifiedError):
    """Something took longer than its time limit."""

    classification = FailureClassification.ENVIRONMENT_ERROR


def can_interrupt() -> bool:
    return hasattr(signal, "setitimer") and threading.current_thread() is threading.main_thread()


@contextmanager
def deadline(seconds: float, message: str) -> Iterator[None]:
    """Raise ``StepTimeoutError(message)`` if the block runs longer than ``seconds``."""
    if seconds <= 0:
        raise StepTimeoutError(message)
    if not can_interrupt():
        yield
        return

    def expire(signum: int, frame: FrameType | None) -> None:
        raise StepTimeoutError(message)

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class Budget:
    """Remaining time of the whole execution."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._end = time.monotonic() + seconds

    @property
    def remaining(self) -> float:
        return self._end - time.monotonic()

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    def limit(self, wanted: float, message: str) -> tuple[float, str]:
        """The time a phase may use and the message for when it is exceeded."""
        if self.remaining < wanted:
            return self.remaining, f"execution timeout of {self.seconds:g}s exceeded"
        return wanted, message
