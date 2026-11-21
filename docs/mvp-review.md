# MVP review (TASK-075)

Review of the MVP scope (all P0 tasks of [backlog.md](backlog.md)) at commit
time of this document. The MVP is **frozen**: further work starts from the P1
list or the post-MVP backlog, one task at a time.

## Verdict

The deterministic local flow works end to end. Gherkin scenarios are
validated, compiled into Test Specifications, planned and executed. Browser
steps run through Playwright and API steps through HTTPX, in FE, BE and FULL
modes. Every run produces results, evidence, a log and an HTML report, and is
stored in a history the CLI can query. A new user can follow
[getting-started.md](getting-started.md) from a fresh clone; that was checked
by running every command in it.

At review time one P0 had a part deferred explicitly: mocked dependencies in
FE mode (TASK-051, see below); it has been done since. The first milestone
(TASK-072) has been reached.

## P0 status

| Area | Tasks | Status |
|------|-------|--------|
| Project setup | 001–005 | Done |
| Domain models and schemas | 006–011, 057 | Done (057: `qa_schemas.results`: test case id, status, duration, classification, message, evidence) |
| Configuration and persistence | 012–014, 016, 055 | Done (014 revised to `repo add` / `env add`) |
| Scenarios | 017–023 | Done; Markdown scenarios deferred (ADR-010) |
| Compilation | 024–028 | Done |
| Steps and adapters | 029–033 | Done |
| Execution engine | 034–038 | Done (034: local target only) |
| Browser (Playwright) | 039–042, 044 | Done (043 is P1 and also done) |
| API (HTTPX) | 045–049 | Done |
| Plans and modes | 050, 052, 053 | Done |
| FE mode | 051 | **Done for the MVP; mocked API dependencies deferred** at review time (the runner was made to refuse `mock` plans, which it used to ignore silently). *Update:* mocks were added after the review (`qa test --mock`). |
| Results, history, reports | 058, 059, 062, 063 | Done |
| Reliability and security | 066–068 | Done (067: hard limits need POSIX and the main thread, ADR-019) |
| Examples and validation | 070–074 | Done |
| Review | 075 | Done (this document) |

## Architecture

- **Package boundaries.** The dependency table in
  [architecture.md](architecture.md) did not list `qa_execution → qa_reporting`
  (the `qa test` use case writes the report). The table now does, and
  `tests/unit/test_architecture.py` enforces the rules on every import, so
  they cannot drift silently. `qa_reporting` still depends on `qa_schemas`
  only, so reports can be rebuilt from `results.json`.
- **Decisions** are recorded as ADR-001…019. None is contradicted by the code.
- **No speculative abstractions.** There is one execution target (local), two
  adapters and one scenario format. The interfaces (`TestAdapter`,
  `ExecutionStore`, scenario source) each exist because the code needs them.
- **No AI, MCP, cloud or web UI code**, as the backlog requires before the
  local flow is stable.
- **Silent mocks.** The plan schema accepts `mode: mock`, but nothing
  implements it, and the runner ignored it, so it would have tested the real
  service. The runner now refuses such plans (`NotExecutableError`).
- **Stale notes.** One docstring and one architecture paragraph still said
  "follows in TASK-0xx" for work that is finished. Both are fixed.

## Security

| Check | Result |
|-------|--------|
| Secrets in git history (key/token/password patterns, `.env`, keys, `.qa/`, databases) | none found; only the Example Shop's documented test passwords |
| Secrets in configuration | `qa.yaml` rejects credentials in URLs, plaintext credential headers and secret-named variables |
| Secret values in output | masked in console, `results.json`, `execution.log`, evidence and report. Checked again in a fresh project: the value appears in no file under `.qa/` |
| HTML report | every dynamic value is HTML-escaped, including attributes; a test covers `<script>` in messages |
| Paths | evidence paths must be relative without `..`; specification ids follow a strict pattern before becoming file names; scenario files outside the project are rejected |
| SQL | parameters only; the one f-string inserts a constant column list |
| Application under test | the platform only reads repository locations from `qa.yaml`, never writes there; the Example Shop listens on `127.0.0.1` by default |
| Dependency vulnerabilities | not checked in the review environment (the scan tool could not run there); the CI `audit` job now runs `pip-audit` on `uv.lock` for every push |

Known security limitations are listed below.

## Test coverage

- 753 tests (unit + integration), all passing; `ruff`, `ruff format --check`
  and `mypy --strict` clean.
- `uv run pytest --cov`: **98 % line coverage** (3,415 statements, 65 missed).
  What is missed is mostly defensive branches: database open/migration
  failures, log write errors, unreachable planning guards.
- Each main workflow has a home in the tests; the map is in
  `tests/integration/test_platform_workflows.py`. The full vertical slice (all
  example features, fe/be/full, run twice) is
  `tests/integration/test_vertical_slice.py`.
- Browser tests are skipped when no browser can be launched locally; CI sets
  `QA_TEST_REQUIRE_BROWSER=1`, which turns that skip into a failure.

## CLI usability

- Commands: `init`, `project repo add`, `project env add`, `scenario validate`,
  `scenario compile`, `test`, `execution list`, `execution show`. Every
  project command accepts `-c/--config`.
- Exit codes are consistent and documented: `0` success, `1` domain error,
  `2` usage error.
- Errors name the cause and the fix (getting-started lists the real
  messages). The guide replay found and fixed two rough edges: `qa test` now
  names unresolved steps, and "not found" no longer repeats paths.
- Gaps: `qa project env add`
  cannot edit an existing environment; that needs a manual edit of `qa.yaml`.
  (`qa project show`, `qa --version` and `qa rerun` were added after the
  review, with TASK-015, TASK-065 and TASK-064.)

## Documentation

- README, [getting-started.md](getting-started.md) and one reference page per
  area: configuration, scenarios, steps, adapters, execution, secrets and
  architecture.
- All internal links and anchors resolve (checked by script).
- [getting-started.md](getting-started.md) was replayed command by command in
  a fresh clone.

## Known limitations

Scenarios and compilation:

- Gherkin only; Markdown scenarios are deferred (ADR-010).
- Tags on an `Examples` section are not carried into the specification.
- `qa.yaml` validation reports the first problem of an environment, not all.

Execution:

- One execution target (local, in process); no parallelism.
- Mocks replace only requests the test or the browser sends, not calls the
  application makes from its own servers (TASK-051, `qa test --mock`).
- `contract` mode is not implemented (TASK-054, P1).
- Only the `functional` test category runs.
- Hard timeouts need POSIX signals and the main thread. On Windows, or when
  embedded in a thread, only adapter timeouts apply (ADR-019).
- Test data isolation (TASK-056) is opt-in: `${UNIQUE}`, setup/cleanup requests and
  protected environments; nothing is isolated automatically.

Security:

- Values written literally into scenario files stay in those files and in
  their specifications; only `${NAME}` references are protected.
- Playwright traces are not redacted (off by default). Screenshots show
  whatever the page shows.
- Dependency vulnerabilities are scanned in CI only (see above).

## Deferred and next

Deferred explicitly from the MVP:
- Mocked dependencies for FE mode (part of TASK-051); done after the review
  with `qa test --mock`.
- Markdown scenarios (ADR-010).

Recommended next, in order:
1. ~~Run a dependency vulnerability scan and add a CI workflow (lint, types,
   tests with a browser).~~ Done: `.github/workflows/ci.yml` (part of
   post-MVP TASK-128/129).
2. ~~TASK-065 (CLI error messages, `--version`) and TASK-015 (`qa project show`).~~ Done.
3. ~~TASK-060 (JSON report beyond `results.json`) and TASK-064 (rerun failed).~~ Done.
4. ~~TASK-056 (test data isolation), then mocked dependencies (completes
   TASK-051).~~ Done.
5. TASK-054 (contract mode), TASK-061 (fingerprinting), ~~TASK-069 (safety
   policies)~~ done (host allowlist).
