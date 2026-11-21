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
| `qa_core` | Domain logic: projects, scenario parsing, compilation, step and adapter registries. | `qa_schemas` |
| `qa_execution` | Execution engine, execution targets, test adapters (Playwright, HTTPX). | `qa_schemas`, `qa_core` |
| `qa_reporting` | HTML/JSON reports built from results and evidence. | `qa_schemas` |
| `qa_cli` | Argument parsing and output only; delegates all work to the packages. | all of the above |

Dependencies point only in the directions listed. No package imports `qa_cli`,
and `qa_reporting` does not import `qa_execution` — it works from persisted
results, so reports can be regenerated without re-running tests.

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
| `qa_schemas.scenario` | `ScenarioDocument` (raw input); `ParseResult`, `ParsedFeature`, `Scenario`, `ScenarioStep`, `Examples`, `ParseIssue` |

`Project` validates cross-references: repository and environment names are
unique, and `default_environment` must name a defined environment.
Secrets and environment variables are added in TASK-055.

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
Any other value is rejected. The version is bumped on incompatible changes;
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
