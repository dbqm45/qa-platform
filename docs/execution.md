# Execution

The Local Runner executes a compiled specification in the current process.
Only `ready` specifications are executed; anything else is rejected before
anything starts.

## Lifecycle

```
PENDING   checks: specification ready, plan matches specification and environment,
          one adapter per required capability
RUNNING   adapters validated, then prepared
          each test case: start hooks -> steps in order -> finish hooks -> evidence
cleanup   always (also after failures and Ctrl+C), in reverse order of preparation
PASSED | FAILED | ERROR | CANCELLED
```

Each transition is persisted (`.qa/qa.db`). Execution ids are UTC timestamps
with a random suffix, e.g. `20261121-143005-a1b2c3`, so they sort by start time.
Evidence goes to `<evidence root>/<execution id>/`.

## Outcomes

| Test case status | Meaning |
|------------------|---------|
| `passed` | every step ran without raising |
| `failed` | a step raised `StepFailure`: the application did not behave as expected |
| `error` | the test could not be evaluated (environment, test data, broken step or platform) |
| `cancelled` | not run: interrupted, or skipped by `fail_fast` |

Steps after the first failing step are not run; results list the executed
steps and `steps_total`. The execution status is the most severe case status:
`error` > `failed` > `cancelled` > `passed`, so a non-passing result is never
reported as successful.

## Failure classification

| Raised by a step | Status | Classification |
|------------------|--------|----------------|
| `StepFailure(message)` | failed | `application_bug` (or the classification given) |
| `TestEnvironmentError`, `TimeoutError`, `ConnectionError` | error | `environment_error` |
| `TestDataError` | error | `test_data_error` |
| `DependencyError` | error | `dependency_error` |
| `RequirementAmbiguityError` | error | `requirement_ambiguity` |
| any other exception | error | `test_implementation_error` |

An unexpected exception is therefore never reported as an ordinary test
failure. Step implementations import these from `qa_execution.errors`:

```python
from qa_execution.errors import StepFailure

def greeting_contains(context, text: str) -> None:
    page = context.resource("browser")
    actual = page.inner_text("#greeting")
    if text not in actual:
        raise StepFailure(f"greeting {actual!r} does not contain {text!r}")
```

## Adapter problems

| Problem | Effect |
|---------|--------|
| `validate()` reports problems | execution `error` (`environment_error`); nothing is prepared |
| `prepare()` raises | execution `error`; adapters prepared so far (and the failing one) are cleaned up |
| `start_test_case()` raises | that test case is `error` |
| `finish_test_case()` raises | `error` if the case had passed; otherwise only a note, the original failure is kept |
| `collect_evidence()` raises | a note only; the outcome never changes |
| `cleanup()` raises | recorded in `cleanup_errors`; the outcome never changes |

Not yet implemented: step and execution timeouts (TASK-067).
