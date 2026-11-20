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

## Roadmap

The full task backlog lives in [`docs/backlog.md`](docs/backlog.md).

**First milestone:** execute one Gherkin login scenario against a local
application using Playwright, save a screenshot and generate a test report.
