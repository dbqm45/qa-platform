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

### JSON summary for CI

```bash
qa test --scenario api.feature --json build/qa-summary.json
```

writes one versioned summary of the whole run (`qa_schemas.summary.RunSummary`),
in addition to the console output and the per-execution files. Paths in it are
relative to the project root, so a pipeline can upload them as artifacts.
Missing parent directories are created. The file is written for every run,
including one whose scenario file has validation errors; it is not written
when the request itself is invalid (unknown environment, missing file), which
exits with `1` and a message as usual.

```json
{
  "schema_version": 1,
  "project": "shop",
  "scenario": "scenarios/api.feature",
  "environment": "local",
  "ok": false,
  "counts": {"failed": 1, "passed": 3},
  "errors": [],
  "specifications": [
    {
      "id": "api.placing-an-order",
      "source": "scenarios/api.feature:17",
      "compilation": "ready",
      "status": "failed",
      "problem": null,
      "execution_id": "20261121-125129-3ae7d2",
      "duration_ms": 66,
      "results": ".qa/executions/20261121-125129-3ae7d2/results.json",
      "report": ".qa/executions/20261121-125129-3ae7d2/report.html",
      "failures": [
        {
          "test_case_id": "api.placing-an-order",
          "status": "failed",
          "classification": "application_bug",
          "message": "response field 'total' is 6.0, expected 7.0",
          "step": 8
        }
      ]
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `ok` | `true` only if the file was valid and every specification ran and passed (same as exit code `0`) |
| `counts` | specifications per execution status, plus `not_executed` |
| `errors` | validation errors (`location`, `code`, `message`) that blocked the whole file |
| `specifications[].status` | execution status, or `null` with `problem` when it was not executed |
| `failures[].test_case_id` | `null` for a failure of the whole execution not already reported by its cases |
| `failures[].step` | 1-based step number, `null` when the failure is outside a step |

Messages are taken from the redacted results, so secrets are masked here as
everywhere else. `results.json` itself carries `schema_version: 1` too; files
written before it existed are read as version 1.

### History

```bash
qa execution list [--limit 20]
```

```
20261121-094743-ca8af5  PASSED    2026-11-21 10:47     0.8s  local      orders.an-order-placed-...
20261121-094520-1b2c3d  FAILED    2026-11-21 10:45     3.4s  local      login.invalid-login
```

```bash
qa execution show 20261121-0945
```

shows status, plan, mode, environment, start, duration, every test case with
its failure, and where the report, `results.json` and log are. A unique prefix
of the id is enough; an unknown or ambiguous id exits with `1`. An execution
interrupted before it finished has no `results.json`; `show` says so.

### Mocked services

A service of an environment can be replaced by a mock file for one run:

```yaml
environments:
  - name: local
    base_url: http://localhost:3000
    services:
      api: https://api.example.com/v1
    mocks:
      api: mocks/api.yaml        # relative to the project root
```

```yaml
# mocks/api.yaml
version: 1
responses:
  - request: GET /orders         # METHOD /path below the service URL; query ignored
    json: [{"product": "apple", "quantity": 3}]
  - request: POST /orders
    status: 201
    json: {"id": 99}
  - request: GET /health
    body: ok                     # text instead of json
    headers: {Content-Type: text/plain}
```

```bash
qa test --scenario orders.feature --mock api
```

- Requests to the mocked service's URL are answered from the file, in
  process: by the HTTP adapter for API steps, and by the browser for the
  page's own requests (`fetch`, XHR, scripts). Nothing reaches the real
  service; other URLs are not affected.
- A request the file does not describe is a `dependency_error` naming it
  (`mock 'api' has no response for GET /unknown (it knows: GET /orders, ...)`),
  never an invented response. In the browser this is reported even if a later
  step failed because of it (that failure is kept as a note).
- Mocked responses carry the header `x-qa-mock: <service>`, so `http.json`
  shows which answers were mocked. For pages on another origin they allow CORS
  (`access-control-allow-origin: *` unless the file sets it), and a browser's
  CORS preflight (`OPTIONS`) is answered automatically.
- The plan records the service as `dependencies: [{name: api, mode: mock}]`;
  `results.json` (`mocked`), `qa execution show` (`Mocked`), the summary line
  (`on local (mocked: api)`) and the [JSON summary](#json-summary-for-ci) say
  which services were mocked. `qa rerun` mocks the same services again.
- Requests to a mock change no data, so they are allowed in a
  [protected environment](#protected-environments); setup and cleanup
  requests to a mocked service are skipped (logged as `hook-skipped`).
- Only requests the test or the browser sends can be mocked. Calls the
  application makes from its own servers (e.g. a server-rendered page that
  loads orders from the API) still go to the real service: changing how the
  application under test is wired is outside the platform.
- Errors: an unknown `--mock` name (`environment 'local' has no mock for
  'payments' (mocks: api)`), a missing or invalid file (with the field, as for
  `qa.yaml`), or a file outside the project stop the run with exit code `1`.

### Setup and cleanup requests

```yaml
environments:
  - name: local
    services:
      api: http://localhost:8000/api
    setup: ["POST /reset"]      # before every execution
    cleanup: ["POST /reset"]    # after every execution
```

Each entry is `METHOD path` (or `METHOD https://...`), sent in order to the
environment's API service (`adapters.httpx.service`, default `api`) or else
its `base_url`, with the environment's `headers`. `${NAME}` references work
in the path. They run for every execution (each specification), whether its
steps use the browser, the API or both, so every test starts from known data.

- A failing setup request (no connection, or a status of 400 or more) stops
  the execution before its first test case: every test case is `error` /
  `environment_error` with `environment setup failed: setup POST /reset
  answered 500`. Cleanup requests are still sent.
- A failing cleanup request is recorded in `cleanup_errors` (shown as
  `cleanup: environment: ...`) and never changes a test result.
- Cleanup is skipped only when the execution never reached setup (e.g. the
  browser could not start), because nothing could have changed.
- Each request is logged (`hook-finished` with status and duration).
- In a [protected environment](#protected-environments) requests other than
  `GET`, `HEAD` and `OPTIONS` are not sent without `--allow-writes`.

For data a single test creates, prefer [`${UNIQUE}`](steps.md#unique-test-data)
over cleanup: unique data cannot collide even when cleanup fails.

### Protected environments

```yaml
environments:
  - name: prod
    base_url: https://shop.example.com
    protected: true
```

A protected environment is **read-only**: tests must not change its data.
`--allow-writes` on `qa test` or `qa rerun` lifts this for one run.

1. **Before execution.** A specification with built-in steps that would
   change data is not executed at all, and the steps are named:

   ```
   NOT RUN  not executed: environment 'prod' is protected (read-only) and these steps would change data: line 3: When the client sends POST "/orders" with:; use --allow-writes to run it anyway
   ```

   Such steps are API requests with any method other than `GET`, `HEAD` and
   `OPTIONS`, and data entry in the browser (`fills`, `selects`, `checks`,
   `unchecks`, `submits the form`). A `POST /login` counts too: the rule is
   about the method, not the intent.
2. **During execution**, as a safety net for custom steps and clicks:
   - the HTTP adapter does not send a write method (`environment_error`:
     `POST /orders was not sent: environment 'prod' is protected ...`);
   - the browser blocks every request of the page that is not `GET`, `HEAD`
     or `OPTIONS`, for example a form a click submits. The test case then ends
     as `error` / `environment_error` with the blocked requests, even if a
     later step failed because of the block (that failure is kept as a note),
     so the application is not blamed.

This guards against accidents; it is not a security boundary. A `GET` that
changes data in a badly designed application is not detected.

### Rerun

```bash
qa rerun --failed-only 20261121-0945
```

runs an earlier execution again: the same specification, environment, mode
and category. `--failed-only` takes only the test cases that did not pass
(failed, error or cancelled); without it every test case runs again.
`--timeout` and `--json` work as for `qa test`.

- The scenario file is compiled again, so the rerun uses the scenario **as it
  is now**. If it changed since the original execution, a warning says so:

  ```
  Warning: scenario 'Placing an order' changed since execution 20261121-125743-89884e; running the current version
  ```

- A test case is rerun only if both its id and its name still match. Outline
  test cases are numbered by position (`orders.order-product:2`), so after a
  row of `Examples` is removed or moved, the same number can name a different
  example; that case is skipped with a warning instead of running the wrong
  example in its place. If none is left, the rerun stops with an error.
- The rerun is a normal execution with its own results, evidence and report.
  `qa execution show` names the execution it repeats (`Rerun of`).
- If every test case passed, `--failed-only` prints `Nothing to rerun` and
  exits with `0`.
- An execution cannot be rerun when its `results.json` is missing (interrupted)
  or was written before reruns existed, when its environment was removed from
  `qa.yaml`, or when its scenario no longer exists. Each exits with `1` and
  says which.

### Log

Every execution writes `.qa/executions/<id>/execution.log`: one JSON object
per line, written as it happens (`tail -f` works during a run):

| Event | Fields |
|-------|--------|
| `execution-started` | execution, project, specification, scenario location, plan, mode, category, environment, adapters, timeouts |
| `adapter-prepared` / `adapter-failed` / `adapters-rejected-specification` | adapter, error / problems |
| `test-case-started` / `test-case-finished` / `test-case-cancelled` | test case, status, duration, classification, error, evidence, notes / reason |
| `step-finished` | test case, index, line, action, text, status, duration, error |
| `execution-interrupted`, `cleanup-finished`, `execution-finished` | errors / final status, failure, counts per status |

Every line passes through the secret redactor when it is written.

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
rejected and the specification is not executed.

In `full` mode one test case uses both adapters: steps run in order against
the browser and the API, the result lists all of them, and the test case's
evidence folder holds both `page.json` (and screenshots) and `http.json`.
Example: `examples/scenarios/orders.feature` places an order through the API
and checks it on the dashboard. Services are real unless mocked with
`--mock` (see [Mocked services](#mocked-services)). Only the `functional`
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
