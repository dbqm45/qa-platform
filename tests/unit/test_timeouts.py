"""Hard time limits (TASK-067)."""

import threading
import time

import pytest

from qa_execution.timeouts import Budget, StepTimeoutError, can_interrupt, deadline
from qa_schemas.enums import FailureClassification


def test_deadline_interrupts_a_blocking_call() -> None:
    started = time.monotonic()
    with pytest.raises(StepTimeoutError, match="too slow"), deadline(0.2, "too slow"):
        time.sleep(10)
    assert time.monotonic() - started < 2


def test_deadline_does_nothing_when_the_block_is_fast() -> None:
    with deadline(5, "never"):
        value = 1 + 1
    assert value == 2


def test_timer_is_cancelled_after_the_block() -> None:
    with deadline(0.2, "first"):
        pass
    time.sleep(0.4)  # would raise here if the timer were still armed


def test_no_time_left_fails_immediately() -> None:
    with pytest.raises(StepTimeoutError, match="nothing left"), deadline(0, "nothing left"):
        pytest.fail("the block must not run")


def test_timeouts_are_environment_errors() -> None:
    assert StepTimeoutError.classification is FailureClassification.ENVIRONMENT_ERROR


def test_outside_the_main_thread_deadline_cannot_interrupt() -> None:
    outcome: list[str] = []

    def work() -> None:
        assert not can_interrupt()
        with deadline(0.05, "ignored"):
            time.sleep(0.2)
        outcome.append("finished")

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert outcome == ["finished"]


def test_budget_limits_phases_to_the_remaining_time() -> None:
    budget = Budget(1.0)
    seconds, message = budget.limit(0.5, "step exceeded")
    assert (seconds, message) == (0.5, "step exceeded")
    seconds, message = budget.limit(10, "step exceeded")
    assert seconds <= 1.0
    assert message == "execution timeout of 1s exceeded"
    assert not budget.exhausted
