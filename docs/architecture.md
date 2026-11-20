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
