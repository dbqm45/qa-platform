# qa-platform

Local-first QA automation platform. It turns Gherkin scenarios into normalized
Test Specifications and executes them deterministically through adapters
(Playwright for UI, HTTPX for APIs), producing results, evidence and reports.

> **Status:** early development — Phase 0 (project setup).

## Principles

- Deterministic execution first; no LLM is required for the core flow.
- The platform never modifies the source code of the applications under test.
- Runs locally end to end; no remote services are required.
- No secrets in the repository or in configuration files.

## Requirements

- Python **3.12** (pinned in `.python-version`)
- [uv](https://docs.astral.sh/uv/) 0.5+ — dependency and environment manager
- Git

`uv` downloads Python 3.12 automatically if it is not installed.

## Installation

```bash
git clone https://github.com/dbqm45/qa-platform.git
cd qa-platform
uv sync --locked
```

`uv sync --locked` creates `.venv/` and installs the exact versions from
`uv.lock`; it fails if the lockfile is out of date with `pyproject.toml`.

## Managing dependencies

| Action | Command |
|--------|---------|
| Add a runtime dependency | `uv add <package>` |
| Add a development dependency | `uv add --dev <package>` |
| Remove a dependency | `uv remove <package>` |
| Upgrade locked versions | `uv lock --upgrade` |
| Run a command in the environment | `uv run <command>` |

Always commit `pyproject.toml` and `uv.lock` together.

## Code quality

All tools are configured in `pyproject.toml`.

| Check | Command |
|-------|---------|
| Lint | `uv run ruff check .` |
| Lint and auto-fix | `uv run ruff check --fix .` |
| Format | `uv run ruff format .` |
| Verify formatting | `uv run ruff format --check .` |
| Type check (strict) | `uv run mypy` |
| Tests | `uv run pytest` |

Run everything before committing:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

## Tests

```
tests/
├── unit/          # fast, isolated — no network, browser or filesystem side effects
└── integration/   # real dependencies (browser, HTTP, SQLite)
```

Tests under `tests/integration/` are marked `integration` automatically.

| Run | Command |
|-----|---------|
| All tests | `uv run pytest` |
| Unit tests only | `uv run pytest -m "not integration"` |
| Integration tests only | `uv run pytest -m integration` |
| One file / one test | `uv run pytest tests/unit/test_version.py::test_version_is_semantic` |

Test files are named `test_*.py`, test functions `test_*`.

## Project structure

| Path | Contents |
|------|----------|
| `apps/cli/qa_cli/` | `qa` command-line interface |
| `packages/qa_core/` | Domain logic |
| `packages/qa_schemas/` | Versioned data schemas |
| `packages/qa_execution/` | Execution engine and adapters |
| `packages/qa_reporting/` | Reporting |
| `tests/` | Platform tests |
| `examples/` | Example scenarios and applications |

Package responsibilities and allowed dependencies are described in
[`docs/architecture.md`](docs/architecture.md).

## Usage

After installation the `qa` command is available inside the environment
(`uv run qa ...`, or directly after `source .venv/bin/activate`).

```bash
uv run qa init path/to/my-project
```

`qa init` creates only what is missing and never overwrites existing files:

| Path | Purpose |
|------|---------|
| `qa.yaml` | Project configuration (see below). `--id` / `--name` set its initial values. |
| `scenarios/` | Scenario files (the configured `scenario_dir`). |
| `.qa/` | Local platform data (evidence, reports). Has its own `.gitignore`. |
| `.qa/qa.db` | SQLite database with project and execution metadata; migrated automatically. |

Re-running it is safe; an existing `qa.yaml` is validated and left untouched.
Exit code is `0` on success and `1` on an error.

## Configuration

Projects are configured in `qa.yaml`; see [`docs/configuration.md`](docs/configuration.md).

## Roadmap

The full task backlog lives in [`docs/backlog.md`](docs/backlog.md).

**First milestone:** execute one Gherkin login scenario against a local
application using Playwright, save a screenshot and generate a test report.
