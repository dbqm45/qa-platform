# qa-platform

Local-first QA automation platform. It turns Gherkin scenarios into normalized
Test Specifications and executes them deterministically through adapters
(Playwright for UI, HTTPX for APIs), producing results, evidence and reports.

> **Status:** MVP complete and frozen ([review](docs/mvp-review.md)). Gherkin
> scenarios run end to end in a browser (FE), against JSON APIs (BE) or both
> (FULL), with evidence, history and an HTML report.

## Quick start

New here? Follow [`docs/getting-started.md`](docs/getting-started.md): installation,
the Example Shop, your own project from scratch, secrets and troubleshooting.

In short: install (see [Installation](#installation)), then in one terminal start the
example application:

```bash
uv run python examples/app/shop_app.py --port 8000
```

and in another run its scenarios:

```bash
cd examples
```

```bash
uv run qa init
```

```bash
uv run qa test --scenario login.feature
```

```
login.successful-login  (scenarios/login.feature:8)
  PASSED    Successful login  (0.8s)
  execution 20261121-080102-1a2b3c: PASSED  -> .qa/executions/20261121-080102-1a2b3c/results.json
  report: .qa/executions/20261121-080102-1a2b3c/report.html
...
Ran 3 specifications from scenarios/login.feature on local: 3 passed
```

Open the printed `report.html` in a browser. Try `contact.feature` and
`api.feature` (no browser needed) too, or
change an expected text in a scenario to see a failure with a screenshot.

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

Browser tests need a browser for Playwright:

```bash
uv run playwright install chromium
```

Alternatively point `adapters.playwright.executable_path` in `qa.yaml` to an
existing Chromium. Browser integration tests are skipped when no browser can
be launched (set `QA_TEST_BROWSER_EXECUTABLE` to use a specific binary, or
`QA_TEST_REQUIRE_BROWSER=1` to make them fail instead, as CI does).

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
| Tests with coverage | `uv run pytest --cov` |

Run everything before committing:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

### Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

- **checks**: the commands above, then all tests with an installed Chromium and
  `QA_TEST_REQUIRE_BROWSER=1`, so browser tests fail instead of being skipped.
- **example-project**: the `qa-test` action (for test projects, see
  [`docs/ci.md`](docs/ci.md)) against the Example Shop, also in contract mode.
- **audit**: `pip-audit` on the exact versions from `uv.lock`.

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

Add repositories and environments to an existing project:

```bash
uv run qa project repo add web --path ../shop-web
```

```bash
uv run qa project env add staging --base-url https://staging.example.com --service api=https://api.staging.example.com --timeout 60 --default
```

Both commands use `qa.yaml` in the current directory (`-c PATH` for another
file), validate the result before writing, and keep existing comments.

Tests only reach the environment's own hosts (plus its `allowed_hosts`), so a
copied URL or a redirect cannot send them, or their credentials, elsewhere.
`qa test --mode contract` also checks every API response against the
service's OpenAPI document.
`qa test --mock api` answers a service from a mock file instead of the real
one (see `docs/execution.md`).
`--protected` on `env add` makes an environment read-only (`qa test
--allow-writes` overrides it for one run).
`uv run qa project show` prints the whole configuration (without secret
values); `uv run qa --version` prints the platform version.

Exit codes: `0` success, `1` error (configuration, validation, storage),
`2` invalid command-line usage, `130` interrupted with Ctrl-C (a running
execution is recorded as `cancelled`). An unexpected error prints one line
(`Internal error: ...`); run with `QA_DEBUG=1` to see the traceback.

## Scenarios

Scenarios are Gherkin `.feature` files; supported constructs and validation
rules are described in [`docs/scenarios.md`](docs/scenarios.md).

```bash
uv run qa scenario validate
```

```
scenarios/login.feature:12: error [scenario.missing-name] scenario has no name
scenarios/login.feature:20: warning [examples.unused-column] column 'role' is not used by any step

Validated 3 files, 7 scenarios: 1 error, 1 warning
```

Exit code `1` if there is any error; warnings alone exit with `0`.

## Step definitions

How step text is linked to implementations: [`docs/steps.md`](docs/steps.md).

## Adapters

Adapters provide browsers, HTTP clients and other resources to steps:
[`docs/adapters.md`](docs/adapters.md).

## Execution

```bash
uv run qa test --scenario login.feature --environment local
```

Compiles the file, executes its ready specifications in a browser and stores
results, evidence, a log and an HTML report in `.qa/executions/<id>/`.
`uv run qa test --scenario login.feature --json build/qa-summary.json` also writes a versioned JSON summary for CI;
`qa summary` combines several, and a GitHub Action runs a whole project in CI
([`docs/ci.md`](docs/ci.md)).
`uv run qa execution list` and `uv run qa execution show <id>` browse the history;
`uv run qa rerun --failed-only <id>` runs the failed test cases of an execution again;
`uv run qa execution compare <id> <id>` names what differed between two executions
(scenario, environment, repository commits, versions, ...). Lifecycle, outcomes and failure classification: [`docs/execution.md`](docs/execution.md).

## Secrets

Reference credentials as `${NAME}` environment variables; secrets are masked in
results, reports and evidence. See [`docs/secrets.md`](docs/secrets.md).

## Configuration

Projects are configured in `qa.yaml`; see [`docs/configuration.md`](docs/configuration.md).

## Example application

`examples/` contains a small application with a login page, a form and a JSON
API to try the platform on; see [`examples/README.md`](examples/README.md).

## Roadmap

The full task backlog lives in [`docs/backlog.md`](docs/backlog.md); the MVP
review (scope, known limitations, next steps) in [`docs/mvp-review.md`](docs/mvp-review.md).

**First milestone:** execute one Gherkin login scenario against a local
application using Playwright, save a screenshot and generate a test report.
