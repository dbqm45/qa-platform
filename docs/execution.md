# Execution

## Running tests

```bash
qa test --scenario login.feature [--environment local] [--mode fe|be|full] [--category functional]
```

1. The file is found as given, relative to the project root, or relative to
   `scenario_dir`; it must be inside the project.
2. It is compiled. A file with validation errors is not executed at all.
3. Every `ready` specification gets an Execution Plan and is executed; others
   are listed as `NOT RUN` with the reason.
4. Results are stored in `.qa/executions/<execution id>/`:
   `results.json` (complete report) and one folder of evidence per test case.
   Status and timestamps are also kept in `.qa/qa.db`.

```
login.successful-login  (scenarios/login.feature:5)
  PASSED    Successful login  (0.6s)
  execution 20261121-073604-bc3f2e: PASSED  -> .qa/executions/20261121-073604-bc3f2e/results.json
login.wrong-password  (scenarios/login.feature:12)
  FAILED    Wrong password  (3.1s)
            application_bug: the page does not show 'Welcome' (page: http://127.0.0.1:8000/login)
            screenshot: .qa/executions/20261121-073610-8bf27a/login.wrong-password/screenshot.png
  execution 20261121-073610-8bf27a: FAILED  -> .qa/executions/20261121-073610-8bf27a/results.json

Ran 2 specifications from scenarios/login.feature on local: 1 failed, 1 passed
```

| Exit code | Meaning |
|-----------|---------|
| `0` | every specification was executed and passed |
| `1` | something failed, errored or could not be executed, or the request was invalid |
| `2` | invalid command-line usage (e.g. unknown `--mode`) |

`--environment` defaults to `default_environment`. The environment's
`timeout_seconds` is the step timeout, so a failing assertion waits that long
before it fails.

### Report

Every execution also gets `.qa/executions/<execution id>/report.html`: a single
self-contained file (no scripts or external resources, light and dark theme)
with the summary, every test case with its steps, durations and statuses,
failure classification and message, a screenshot thumbnail and links to all
evidence. Links are relative, so the execution folder can be archived or shared
as a whole. The report is built only from `results.json` and can be regenerated
with `qa_reporting.html.write_html_report()`.

Secrets are masked in `results.json`, `report.html` and evidence; reference
real credentials as `${NAME}` (see [`secrets.md`](secrets.md)).

### Execution Plans and modes

The plan is generated (TASK-050, minimal). Without `--mode` the mode follows
from the capabilities the steps need:

| Mode | Requires | Chosen when the steps need |
|------|----------|----------------------------|
| `fe` | `browser` only | `browser` only |
| `be` | no `browser` | anything without `browser` |
| `full` | `browser` and something else | `browser` and something else |
| `contract` | not implemented yet | never |

An explicit mode that does not fit (e.g. `--mode be` for browser steps) is
rejected and the specification is not executed. Only the `functional`
category is supported so far.

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

## Browser evidence

For every test case the Playwright adapter writes to
`<evidence root>/<execution id>/<test case id>/`:

| File | When |
|------|------|
| `page.json` | always: final URL, title, browser console errors and uncaught page errors |
| `screenshot.png` | full page; by default only when the test case did not pass (`screenshot`) |
| `trace.zip` | only if enabled (`trace`); open with `uv run playwright show-trace trace.zip` |

The files are listed in the test result's `evidence`. Collecting evidence
never changes the outcome; problems are recorded as notes.

## API evidence

For every test case that sent requests, the HTTPX adapter writes
`<test case id>/http.json`: each exchange with method, URL, request headers and
body, response status, headers and body (truncated to `max_body_bytes`) and
duration. `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`,
`X-Api-Key` and `X-Auth-Token` are masked, and the file passes through the
secret redactor.

## Timeouts

No execution can run indefinitely.

| Limit | Default | Set by | When exceeded |
|-------|---------|--------|---------------|
| step | environment `timeout_seconds` (30 s) | `qa.yaml` environment | step `error` / `environment_error`: `step exceeded its timeout of Ns` |
| whole execution | 600 s (or the step timeout if longer) | `qa test --timeout SECONDS` (1–86400) | current step stopped, remaining test cases `cancelled`, execution `error`: `execution timeout of Ns exceeded` |
| adapter start | max(60 s, step timeout) | — | execution `error` |
| per-test-case hooks and evidence | max(10 s, step timeout) + 2 s | — | hook: test case `error`; evidence: a note only |
| cleanup, per adapter | 30 s, even after the execution deadline | — | recorded in `cleanup_errors`; other adapters are still cleaned up |

Two layers enforce these limits:

1. **Adapter timeouts** — every Playwright operation, every waiting assertion
   and every HTTP request uses the step timeout and produces a specific message.
2. **Hard limits** — slightly above the step timeout (+2 s), they interrupt
   code that would otherwise wait forever (custom steps, `page.evaluate`
   loops, hung hooks). They use `SIGALRM`, so they work on Linux and macOS
   when `qa` runs in the main thread. On Windows only the adapter timeouts and
   the execution deadline checked between test cases apply.
