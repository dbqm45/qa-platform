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

`Project` validates cross-references: repository and environment names are
unique, and `default_environment` must name a defined environment.
Secrets and environment variables are added in TASK-055.
