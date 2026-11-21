# Architecture

## Repository layout

```
qa-platform/
├── apps/
│   └── cli/qa_cli/        # `qa` command-line interface
├── packages/
│   ├── qa_core/           # domain logic
│   ├── qa_schemas/        # versioned data schemas
│   ├── qa_execution/      # runners and adapters
│   └── qa_reporting/      # reports and evidence presentation
├── tests/                 # platform tests
├── docs/
└── examples/              # example scenarios and test applications
```

## Package responsibilities

| Package | Responsibility | May depend on |
|---------|----------------|---------------|
| `qa_schemas` | Pydantic models for Test Specification, Execution Plan, results, configuration. No behaviour beyond validation. | — |
| `qa_core` | Domain logic: projects, scenario parsing, compilation, step registry, storage. | `qa_schemas` |
| `qa_execution` | Execution engine, adapter registry, test adapters (Playwright, HTTPX), the `qa test` use case and execution history. | `qa_schemas`, `qa_core`, `qa_reporting` |
| `qa_reporting` | HTML/JSON reports built from results and evidence. | `qa_schemas` |
| `qa_cli` | Argument parsing and output only; delegates all work to the packages. | all of the above |

Dependencies point only in the directions listed. No package imports `qa_cli`,
and `qa_reporting` does not import `qa_execution` — it works from persisted
results, so reports can be regenerated without re-running tests. `qa_execution`
writes the report at the end of a run (and points to it from the history), so
it may call `qa_reporting`. These rules are enforced by
`tests/unit/test_architecture.py`.

## Decisions

### ADR-001: Single distribution, multiple top-level packages (TASK-004)

All packages are shipped in one distribution (`qa-platform`) built with
hatchling, rather than as a uv workspace with one `pyproject.toml` per package.

- **Why:** a solo project with no need to version or publish packages
  independently; one lockfile and one install command keep the setup simple.
- **Trade-off:** package boundaries are enforced by convention and review,
  not by the packaging tool.
- **Revisit when:** a package needs to be released or deployed separately
  (e.g. remote runners in the post-MVP backlog).

## Shared vocabulary (`qa_schemas.enums`)

All status, mode and category values are defined once, in
`packages/qa_schemas/enums.py`. A unit test fails if any other platform
module defines an enum containing a status value.

| Enum | Values | Used for |
|------|--------|----------|
| `CompilationStatus` | `ready`, `needs_review`, `blocked`, `unsupported` | Result of compiling a scenario. Only `ready` is executable. |
| `ExecutionStatus` | `pending`, `running`, `passed`, `failed`, `error`, `cancelled` | Lifecycle of an execution or test result. All except `pending`/`running` are terminal. |
| `ExecutionMode` | `fe`, `be`, `full`, `contract` | Which parts of the system are exercised. |
| `TestCategory` | `functional`, `visual`, `accessibility`, `performance`, `security`, `contract` | What quality is verified. Independent of mode. |
| `StepKind` | `precondition`, `action`, `expectation` | Role of a step (Gherkin Given / When / Then). |
| `DependencyMode` | `real`, `mock` | How an external service is provided. |
| `ScenarioFormat` | `gherkin` | Format of a scenario document; selects the parser. |
| `StepKeywordType` | `context`, `action`, `outcome`, `conjunction`, `unknown` | Gherkin keyword type, language independent. |
| `IssueSeverity` | `error`, `warning` | Severity of a validation finding. |
| `FailureClassification` | `application_bug`, `test_implementation_error`, `environment_error`, `test_data_error`, `dependency_error`, `requirement_ambiguity` | Why a test did not pass. |

### ADR-002: Two status enums instead of one (TASK-007)

The ten statuses from TASK-007 are split into `CompilationStatus` and
`ExecutionStatus`. They describe different lifecycles, and separate types let
the type checker reject e.g. an execution marked `ready`.

### ADR-003: Lowercase string values (TASK-007/010/011)

Members are `StrEnum`s with uppercase names and lowercase values
(`ExecutionMode.FULL == "full"`). Values match YAML/JSON conventions and CLI
arguments. Parsing is case-sensitive; normalising user input is the caller's job.

Note: because they are `StrEnum`s, `ExecutionMode.CONTRACT == TestCategory.CONTRACT`
is `True` at runtime. mypy (strict) flags such cross-type comparisons; always
compare against members of the same enum.

## Schemas (`qa_schemas`)

All schemas are Pydantic v2 models deriving from `qa_schemas.base.SchemaModel`:

- **Unknown fields are rejected** (`extra="forbid"`), so configuration typos fail loudly.
- **Instances are immutable** (`frozen=True`); collections are tuples. Derive
  changed copies with `model_copy(update=...)`.
- Shared field types: `Identifier` (`^[a-z][a-z0-9_-]{0,63}$`), `NonEmptyStr`
  (stripped, 1–200 chars) and `SafeHttpUrl` (http/https, **no embedded credentials**).

| Module | Models |
|--------|--------|
| `qa_schemas.project` | `Project`, `Repository`, `Environment` |
| `qa_schemas.specification` | `TestSpecification`, `TestCase`, `Step`, `SourceReference`, `SpecificationMetadata` |
| `qa_schemas.plan` | `ExecutionPlan`, `ExecutionSettings`, `Dependency` |
| `qa_schemas.config` | `ProjectConfig` (root of `qa.yaml`) |
| `qa_schemas.execution` | `TestExecution` |
| `qa_schemas.compilation` | `CompiledSpecification`, `UnresolvedStep` (format of `.qa/specifications/*.json`) |
| `qa_schemas.evidence` | `EvidenceReference` |
| `qa_schemas.results` | `TestResult`, `StepResult`, `Failure`, `ExecutionReport` (`results.json`, versioned) |
| `qa_schemas.summary` | `RunSummary` and its parts: the `qa test --json` summary for CI |
| `qa_schemas.scenario` | `ScenarioDocument` (raw input); `ParseResult`, `ParsedFeature`, `Scenario`, `ScenarioStep`, `Examples`, `ParseIssue` |

`Project` validates cross-references: repository and environment names are
unique, and `default_environment` must name a defined environment.
Environment variables, headers and secret references: [`configuration.md`](configuration.md), [`secrets.md`](secrets.md).

## Test Specification vs Execution Plan (TASK-008, TASK-009)

```
TestSpecification (what to verify)          ExecutionPlan (how / where)
  schema_version: 1                            schema_version: 1
  id ◄──────────────────────────────────────── specification_id
  source: path, feature, scenario,             mode, category, environment
          line, content_hash                   adapters, dependencies
  test_cases[]: id, name, steps[], parameters  settings: timeouts, fail_fast
  required_capabilities, metadata
```

Samples: `examples/specifications/login.spec.json` and two plans for it in
`examples/plans/` (FULL on staging, FE locally with a mocked API). Unit tests
assert the samples are byte-identical to what the models serialize, so any
format change must update them.

### ADR-004: Steps as one ordered list with a kind

A test case keeps all steps (including Background) in source order, each with
a `kind`. `preconditions`, `actions` and `expected_results` are derived views.
Separate lists would lose ordering for scenarios that interleave When/Then.
A step stores only its keyword, text and line; normalized action and
parameters are added in TASK-024.

### ADR-005: Plans reference specifications by id

An Execution Plan stores `specification_id`, not a copy of the specification.
One specification can have many plans, and each validates on its own.
Whether mode, adapters, capabilities and environment fit together is checked
during plan generation (TASK-050), not by the schema.

### ADR-006: Integer schema versions

Both documents carry `schema_version` (currently `1`) as their first field.
Any other value is rejected. The same applies to the files other tools read:
`results.json` (`ExecutionReport`) and the `qa test --json` summary
(`RunSummary`). `results.json` written before its version existed defaults to
`1`. The version is bumped on incompatible changes;
migrations are added when a second version exists.

## Configuration loading (TASK-012)

`qa_schemas.config.ProjectConfig` defines the shape of `qa.yaml`;
`qa_core.config.load_config()` does the I/O. Every failure (missing file,
YAML syntax, duplicate keys, validation) becomes a single `ConfigError` with
one readable line per problem, so the CLI never shows a traceback for bad
configuration. Format reference: [`configuration.md`](configuration.md).

## CLI and project initialization (TASK-013)

The CLI is built with Typer (`apps/cli/qa_cli/main.py`, entry point `qa`).
Commands only parse arguments, call a function in a package and print the
result; `qa init` delegates to `qa_core.init.initialize_project()`.

`initialize_project()` validates everything first (existing or generated
`qa.yaml`, `scenario_dir` inside the project) and only then touches the
filesystem. Files are created with exclusive mode (`open(..., "x")`), so an
existing file is never overwritten, even by a concurrent run. It then
creates or migrates `.qa/qa.db` and registers the project in it.

## Local persistence (TASK-016)

`qa_core.storage` is the only package that contains SQL. Everything else works
with models.

| Module | Responsibility |
|--------|----------------|
| `storage.database` | `open_database(path)`: opens `.qa/qa.db`, enables foreign keys, applies migrations, always closes. |
| `storage.migrations` | Ordered SQL migrations; schema version in `PRAGMA user_version`. |
| `storage.repositories` | `ProjectRepository`, `ExecutionRepository`: models in, models out. |

```
projects   (id PK, name, created_at, updated_at)
executions (id PK, project_id → projects, specification_id, plan_id,
            mode, category, environment, status, created_at, started_at, finished_at)
```

- **What is stored where:** `qa.yaml` is the source of truth for configuration;
  the database holds runtime metadata (registered project, executions, later
  results). The project row is refreshed from `qa.yaml` on every `qa init`.
- All failures surface as `StorageError` with a readable message.

### ADR-007: stdlib `sqlite3`, no ORM

The schema is small and queries are simple, so the standard library is enough
and adds no dependency. Repositories keep SQL out of business logic, so an ORM
or PostgreSQL (TASK-112) can be introduced behind the same interface later.

### ADR-008: Migration rules

- Migrations are append-only; released ones are never edited or reordered.
- Each runs in one transaction together with the `user_version` bump; a failure
  rolls back completely.
- A database with a newer version than the code knows is refused, not modified.
- Tables are `STRICT` (SQLite ≥ 3.37), and enum columns have `CHECK` constraints
  written out literally; a unit test verifies they match the current enums.
- Timestamps are stored as fixed-width UTC ISO 8601 text, so text order is time order.

## Editing configuration (TASK-014)

`qa_core.config_edit` edits `qa.yaml` with `ruamel.yaml` in round-trip mode, so
comments and layout survive. Reading for validation still goes through
`qa_core.config.parse_config` (PyYAML + Pydantic) — there is one definition of
"valid configuration".

Each edit: validate current file → apply change to the round-trip document →
validate the resulting text → atomic replace. Any failure leaves the file untouched.

### ADR-009: `ruamel.yaml` for writing only

PyYAML cannot preserve comments, and the generated `qa.yaml` relies on them as
documentation. `ruamel.yaml` is used only to write; validation keeps a single
code path through `parse_config`.

## Scenario sources (TASK-017, TASK-018)

```
ScenarioSource.discover() ──► DiscoveryResult
                                 documents: ScenarioDocument[]  (path, format, content, content_hash)
                                 problems:  DiscoveryProblem[]  (path, message)
                                        │
                                        ▼
                          parser chosen by document.format  (TASK-019)
```

`ScenarioSource` (`qa_core.scenarios.sources`) is a `Protocol`: anything with
`discover()`. Sources find and read documents; they never parse. A new source
needs no parser change and a new format needs no source change.

`LocalFileSource(root, directories)` — the only implementation so far:

- recursive, results sorted by path (deterministic);
- file types by extension (`FORMAT_BY_SUFFIX`, case-insensitive); everything
  else, and hidden files/directories, is ignored;
- directory symlinks are not followed; file symlinks must resolve inside the project;
- directories outside the project are rejected;
- content is decoded as UTF-8 (a BOM is removed); `content_hash` is the sha256
  of the raw bytes;
- unreadable, non-UTF-8, oversized (> 1 MB) files and missing directories are
  reported as problems; discovery of other files continues.

### ADR-010: Markdown scenarios deferred

The backlog lists Markdown as an initial source type, but no Markdown scenario
format is defined and there is no parser for it. Discovering `.md` files would
pick up every README in a scenario directory. Supporting it later means adding
a `ScenarioFormat` value, a suffix in `FORMAT_BY_SUFFIX` and a parser.

## Gherkin parsing (TASK-019)

`qa_core.scenarios.parsing.parse_document()` picks a parser from `PARSERS` by
`document.format`. The Gherkin parser (`qa_core.scenarios.gherkin`) uses the
official Cucumber parser (`gherkin-official`) and converts its AST into
platform models, so nothing downstream depends on the library.

```
ParseResult
  feature: ParsedFeature | None        (None on syntax errors or an empty file)
    path, content_hash, language, name, tags, description, line
    scenarios: Scenario[]              (source order, including those inside Rules)
      name, keyword, line, tags, description, is_outline
      rule: RuleReference | None
      background: ScenarioStep[]       (Feature Background + Rule Background)
      steps: ScenarioStep[]            keyword, keyword_type, text, line, data_table, doc_string
      examples: Examples[]             name, tags, line, header, rows[line, values]
  issues: ParseIssue[]                 (line, column, readable message; sorted by position)
```

- Supported: Feature, Rule, Background, Scenario/Example, Scenario Outline/Template,
  Examples, Given/When/Then/And/But/`*`, tags, descriptions, data tables, doc strings,
  and every Gherkin language (`# language: pl`).
- Syntax errors are returned, never raised; all errors are reported, with token
  names translated (`unexpected 'oops'; expected step, table row, ...`).
- Parsing is syntactic only. Models are permissive (empty names, no steps,
  Examples without a table) so that validation (TASK-020) can report them.
  `And`/`But`/`*` keep their own keyword type; resolving them is part of
  compilation (TASK-023).

### ADR-011: Official Cucumber parser

Using `gherkin-official` gives the complete grammar, all languages and precise
error locations, which a hand-written parser would need a long time to match.
It is deterministic and needs no LLM. The conversion layer keeps it replaceable.

## Scenario validation (TASK-020)

`qa_core.scenarios.validation.validate(results)` turns parse results into a
`ValidationReport` (issues, document and scenario counts, `ok` = no errors).
Syntax errors from the parser become `syntax` issues, so the CLI reports
everything in one format. Rules are pure functions over the parsed models;
each `ValidationIssue` has a stable `code` for filtering and tests. The rule
list is documented for users in [`scenarios.md`](scenarios.md).

## Traceability and `qa scenario validate` (TASK-021, TASK-022)

Each `ParsedFeature` carries the file path and the hash of its raw bytes; each
`Scenario` carries its line and a `content_hash` computed by
`qa_core.scenarios.traceability` from its fields, ignoring `line`, `column`
and `description`. Specifications (TASK-023) can reference the scenario hash
to detect which scenarios changed.

`qa_core.scenarios.service.validate_project(config_path)` combines discovery,
parsing and validation; discovery problems are merged into the report as
`discovery` errors. Paths are resolved relative to `qa.yaml`, not the current
directory. The CLI command only formats the report and sets the exit code.

## Scenario → Test Specification (TASK-023)

`qa_core.scenarios.conversion.convert_feature(feature, base)` produces one
`TestSpecification` per scenario; the mapping is documented for users in
[`scenarios.md`](scenarios.md#from-scenario-to-test-specification). Input is
expected to be validated; anything that still cannot be represented raises
`ConversionError` with `path:line`.

Specification `Step` gained optional `data_table` and `doc_string` (additive,
`schema_version` stays `1`), because dropping step arguments would lose
information the test needs. The sample specification in `examples/` is now
produced by the converter, and a test keeps them identical.

### ADR-012: Specification ids and source hash

- **Ids** are derived from the file path (relative to `scenario_dir`) and the
  scenario name, so they are readable and stable across runs and machines.
  Renaming a scenario or moving its file changes its id; collisions within a
  file are resolved by source order (`-2`, `-3`).
- **`source.content_hash`** is the scenario content hash (TASK-021), not the
  file hash, so a specification becomes outdated only when *its* scenario changes.

## Step representation, registry and resolution (TASK-024, TASK-025)

Specification steps now carry `action` (the id of the registered step, or
`null` when unresolved) and typed `parameters`. Together with `kind`,
`keyword`, `text`, `line`, `data_table` and `doc_string` this is the complete
step representation; an expected result is a step of kind `expectation`.

- `qa_core.steps.registry.StepRegistry` holds `StepDefinition`s (id, pattern,
  kind, capability, handler, parameter names). Definitions are fully checked
  when registered.
- `qa_core.steps.resolution.resolve_specification(spec, registry)` returns
  the specification with actions, parameters and `required_capabilities`
  filled in, plus the list of `UnresolvedStep`s.

Author-facing rules: [`steps.md`](steps.md).

### ADR-013: Cucumber Expressions, kind-aware matching

- Patterns use Cucumber Expressions (official `cucumber-expressions` package),
  with anchored regexes as an escape hatch. They are typed and familiar to
  Gherkin authors; parameter types are limited to JSON-compatible ones.
- A step resolves only if **exactly one** definition of a compatible kind
  matches; multiple matches are reported as ambiguous instead of picking one.
- Expectation steps resolve only to expectation definitions, so an
  unrecognised assertion can never become an executable no-op.

## Compilation statuses and `qa scenario compile` (TASK-026, TASK-027)

`qa_core.scenarios.compilation.compile_documents()` runs validate → convert →
resolve → status for each parsed document and returns a `CompilationReport`.
`qa_core.scenarios.service.compile_project()` adds discovery, and
`write_specifications()` stores `CompiledSpecification` files atomically in
`.qa/specifications/` (a platform-owned directory, so stale files are removed).

Status rules (first match wins): unresolved step → `blocked`; missing
capability (only when `available_capabilities` is given) → `unsupported`;
test case without expectation → `needs_review`; otherwise `ready`. Only
`ready` is executable; the runner must check `status.is_executable`.

Built-in step definitions and adapters come from
`qa_execution.builtin.builtin_registry()` / `builtin_adapters()`; the CLI passes
the adapters' capabilities as `available_capabilities`.

### ADR-014: Validation errors block the whole file

Mapping a finding to a single scenario by line number is unreliable (e.g. a
Rule tag error sits before the Rule's scenarios), so a file with validation
errors produces no specifications at all. The fix is always reported by
`qa scenario validate`, and the rule is simple to explain.

## Adapters (TASK-029, TASK-030)

`qa_execution.adapters.TestAdapter` is the adapter contract and
`qa_execution.registry.AdapterRegistry` selects adapters by capability.
Author-facing description: [`adapters.md`](adapters.md).

### ADR-015: Adapters provide resources; the runner executes steps

The backlog sketched `TestAdapter.execute(test_case)`. That only works when a
test case uses a single adapter; in FULL mode one test case mixes browser and
HTTP steps. Instead:

- adapters manage a resource and its lifecycle (`prepare`, per-test-case hooks,
  `collect_evidence`, `cleanup`) and expose it via `resource`;
- the runner (TASK-035) executes steps in order, and each step implementation
  obtains the resource for its capability.

Results of all adapters are naturally part of the same test case, and the
engine depends on no testing framework.

### ADR-016: Synchronous API

Playwright and HTTPX both have complete synchronous APIs, and steps run
strictly in order. Async would add complexity to adapters, steps and tests
without a benefit for the local runner.

## Execution engine (TASK-034, TASK-035, TASK-036, TASK-038)

| Module | Responsibility |
|--------|----------------|
| `qa_execution.targets` | `ExecutionTarget` interface; `LocalTarget` (remote/Kubernetes are post-MVP) |
| `qa_execution.runner` | `LocalRunner`: checks, adapter lifecycle, step execution, status transitions |
| `qa_execution.errors` | `StepFailure`, classified errors, `classify()` |
| `qa_schemas.results` | normalized results, identical for every adapter |

The runner persists status through an `ExecutionStore` protocol, which
`qa_core.storage.ExecutionRepository` satisfies; it has no SQL of its own.
Clock and id factory are injectable, so tests are deterministic.
Behaviour for users and step authors: [`execution.md`](execution.md).

## Browser adapter (TASK-039, TASK-040)

`qa_execution.browser` contains the Playwright adapter (`PlaywrightAdapter`,
capability `browser`), its configuration (`BrowserConfig`, from `qa.yaml`
`adapters.playwright`) and the navigation steps. `qa_execution.builtin`
assembles the built-in step and adapter registries; it lives in
`qa_execution` because built-in steps depend on Playwright and on
`qa_execution.errors`, which `qa_core` must not import.

- One browser per execution; a new browser context and page per test case,
  so cookies and storage never leak between test cases.
- The environment's `base_url` is the context's base URL; the default timeout
  is the plan's `step_timeout_seconds`.
- A browser that cannot be launched or invalid adapter settings are
  `environment_error`s with a hint how to fix them.

## Browser interactions, assertions, locators and evidence (TASK-041..044)

- The `browser` resource is a `BrowserSession` (page, `BrowserConfig`, step
  timeout), not the bare Playwright page, so steps can honour the configured
  locator strategies and timeouts.
- `qa_execution.browser.locators` parses and resolves locators;
  `qa_execution.browser.ui` holds interaction and assertion steps;
  `qa_execution.browser.navigation` the navigation steps.
- Evidence is written in `collect_evidence` (which the runner guards so it can
  never change an outcome); the browser context is closed afterwards.

### ADR-017: Waiting without blocking Playwright

Assertions and locators poll until their condition holds or the step timeout
expires. Polling uses `page.wait_for_timeout`, never `time.sleep`: the sync
API processes browser events (navigations, `page.url` updates) only while a
Playwright call runs, so sleeping would make a waiting assertion miss the very
change it waits for.

## `qa test`, plan generation and result storage (TASK-062, TASK-050, TASK-058)

- `qa_execution.planning.create_plan()` derives a validated `ExecutionPlan`
  from a specification, an environment and an optional mode, rejecting modes
  that do not fit the required capabilities.
- `qa_execution.service.run_scenario()` is the whole `qa test` flow: locate the
  file, compile it, plan and run each ready specification with `LocalRunner`,
  write `results.json` atomically. The CLI only formats `TestRun`.
- `qa_execution.rerun.rerun_execution()` (`qa rerun`, TASK-064) reads the
  original `results.json`, which records the scenario `source` (path and
  content hash), and runs that file again through the same
  `service.run_file()` with a `select` function that keeps the specification
  and, with `--failed-only`, the test cases that did not pass, matched by id
  *and* name. `TestExecution.rerun_of` links the new execution to the original
  (database migration 2 adds the column).
- Execution metadata goes to SQLite (queryable history); the full report is a
  JSON file next to its evidence (easy to inspect, archive or hand to CI).

## HTML report (TASK-059)

`qa_reporting.html.render_html(report, specification=None)` turns an
`ExecutionReport` into a self-contained HTML page; `write_html_report()` stores
it as `report.html` next to the evidence. `qa_reporting` depends only on
`qa_schemas` (see the dependency table), so reports never require re-running
tests. All values are HTML-escaped.

## Secret references and redaction (TASK-066)

`qa_core.redaction` resolves `${NAME}` references and provides `Redactor`.
Each execution creates one redactor and passes it in `ExecutionContext`:
the runner resolves references just before binding step arguments, steps can
add values with `StepContext.mark_secret()`, the browser adapter redacts
`page.json`, and `runner.redact_report()` masks the free-text fields of the
final report. User-facing description: [`secrets.md`](secrets.md).

### ADR-018: Redact free text, never structure

Redaction runs over free-text fields only (step texts, names, messages,
notes, descriptions). Ids, statuses, actions and timestamps are structural:
masking them would corrupt results (`login.wrong-password` with the secret
`wrong` would stop being a valid id), and secrets never belong there.

## API adapter (TASK-045..049)

`qa_execution.http` mirrors the browser package: `HttpxAdapter` (capability
`http`, settings `adapters.httpx`), `HttpSession` as the resource (client,
extra headers, last response, recorded exchanges) and the request/assertion
steps. A new `httpx.Client` per test case keeps test cases independent.
Shared parameter types live in `qa_execution.values`, and `evidence_folder`
moved to `qa_execution.adapters`, so the API package does not import
Playwright. Specifications that need only `http` run in `be` mode.

Step arguments (`data_table`, `doc_string`) are now validated through their
annotations like text parameters; the JSON body check relies on it.

## Timeouts and safe cleanup (TASK-067, TASK-068)

`qa_execution.timeouts` provides `deadline()` (a hard limit via `SIGALRM`) and
`Budget` (remaining execution time). The runner wraps every phase: adapter
start, hooks, steps (step timeout + grace), evidence collection and cleanup
(own 30 s limit, independent of the budget). A `StepTimeoutError` is an
`environment_error`; when the budget runs out, remaining test cases are
cancelled and the execution fails with an execution-level `Failure`.

### ADR-019: Interrupting with signals, not threads

Running a step in a worker thread and abandoning it on timeout is not
possible: Playwright's sync API objects must stay on the thread that created
them. `SIGALRM` interrupts the main thread's Python code instead, after which
the normal error handling and cleanup run. The price: no hard limits on
Windows or outside the main thread; adapter timeouts still apply there. Hard
limits sit 2 s above the step timeout so adapter timeouts, which have better
messages, normally fire first.

## Execution log and history (TASK-037, TASK-063)

`qa_execution.log.ExecutionLog` appends redacted JSON lines to
`execution.log` while the runner works; it never raises, so logging cannot
change an outcome. `qa_execution.history` lists executions from SQLite and
assembles details from the files in the execution directory; the CLI
commands `qa execution list|show` only format them.

## Environment configuration (TASK-055)

`Environment` holds base URL, service endpoints, step timeout, plain
`variables` and default API `headers`. `ExecutionContext.resolve()` is the
single place that resolves `${NAME}`: environment variables from `qa.yaml`
first (plain), then the process environment (secret, registered with the
redactor). The runner uses it for step arguments, the HTTP adapter for
default headers. The schema refuses plain credentials in sensitive headers and
secret-like variable names; patterns are shared through `qa_schemas.base`.
