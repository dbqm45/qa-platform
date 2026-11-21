# Getting started

This guide takes you from a clean machine to your own tested scenarios. It
follows the order a new user needs: install, try the Example Shop, then set up
a project of your own. Every command and output below was run on a fresh
clone; ids and timings will differ on your machine.

## 1. Requirements

- Python **3.12**. `uv` downloads it automatically if it is missing.
- [uv](https://docs.astral.sh/uv/) 0.5 or newer.
- Git.
- A Chromium for browser (FE) tests. API (BE) tests need no browser.

The platform is developed and tested on Linux. Hard timeouts use POSIX
signals; on Windows only the adapter timeouts apply (see
[execution.md](execution.md#timeouts)).

## 2. Install

```bash
git clone https://github.com/dbqm45/qa-platform.git
```

```bash
cd qa-platform
```

```bash
uv sync --locked
```

`uv sync --locked` creates `.venv/` with the exact versions from `uv.lock`.
Check that the CLI works:

```bash
uv run qa --help
```

It lists the commands `init`, `test`, `project`, `scenario` and `execution`.

### Browser

Install the Chromium build that matches the installed Playwright:

```bash
uv run playwright install chromium
```

If you cannot download it (offline machine, proxy), use a Chromium you already
have: set `adapters.playwright.executable_path` in the project's `qa.yaml`
(shown in [step 4.6](#46-run-browser-scenarios)).

## 3. Try the Example Shop

The repository contains a small application to test against
([examples/README.md](../examples/README.md)). Start it in its own terminal and
leave it running:

```bash
uv run python examples/app/shop_app.py --port 8000
```

In a second terminal, from the `qa-platform` directory:

```bash
cd examples
```

```bash
uv run qa init
```

```bash
uv run qa test --scenario api.feature
```

`qa init` is safe here: it only creates what is missing (`.qa/` for results)
and never overwrites the existing `qa.yaml`. Every scenario should pass. With
a browser installed, also run `login.feature`, `contact.feature` and
`orders.feature` (without `playwright install`, add the `adapters` section
from [step 4.6](#46-run-browser-scenarios) to `examples/qa.yaml` first).

## 4. Your own project

A project is a directory with a `qa.yaml`, a `scenarios/` folder and a `.qa/`
folder for results. It lives next to (not inside) the application you test;
the platform never changes the application's code.

To call `qa` from any directory, activate the platform's virtual environment
(once per terminal):

```bash
source qa-platform/.venv/bin/activate
```

Alternatively prefix every command with
`uv run --project <path-to-qa-platform>`.

`qa project show` prints what the platform reads from `qa.yaml` at any time.

The steps below test the Example Shop from section 3, so keep it running.

### 4.1 Create the project

```bash
qa init my-shop-tests --name "My Shop Tests"
```

```
  created  qa.yaml
  created  scenarios
  created  .qa
  created  .qa/.gitignore
  created  .qa/qa.db
Initialized project 'my-shop-tests' in /home/me/my-shop-tests
```

```bash
cd my-shop-tests
```

Commit `qa.yaml` and `scenarios/` to version control. `.qa/` holds generated
files and ignores itself.

### 4.2 Describe the environment

An environment says where the application runs. `base_url` is the start for
browser steps; the `api` service is the base URL for API steps.

```bash
qa project env add shop --base-url http://localhost:8000 --service api=http://localhost:8000/api --timeout 10 --default
```

```
Added environment 'shop' to qa.yaml as the default environment
```

`qa.yaml` now contains:

```yaml
  default_environment: shop
  ...
  environments:
    - name: local
      # base_url: http://localhost:3000
    - name: shop
      base_url: http://localhost:8000
      services:
        api: http://localhost:8000/api
      timeout_seconds: 10
```

`timeout_seconds` is how long assertions wait for the page before failing.
The generated `local` environment is a placeholder you can fill in or remove
by hand; `qa project env add local` refuses to overwrite it. All settings are
in [configuration.md](configuration.md).

### 4.3 Write scenarios

Scenarios are Gherkin files in `scenarios/`. Steps must match the built-in
step definitions listed in [steps.md](steps.md). Create
`scenarios/health.feature`:

```gherkin
Feature: API health
  Scenario: The API is up
    When the client sends GET "/health"
    Then the response status is 200
    And the response field "status" is "ok"
```

and `scenarios/sign-in.feature`:

```gherkin
Feature: Sign in
  Customers sign in with their username and password.

  Scenario: Alice signs in
    Given the user opens "/login"
    When the user fills "Username" with "alice"
    And the user fills "Password" with "${SHOP_PASSWORD}"
    And the user clicks "Log in"
    Then the URL is "/dashboard"
    And the page shows "Welcome, Alice"

  Scenario: Wrong password is rejected
    Given the user opens "/login"
    When the user fills "Username" with "alice"
    And the user fills "Password" with "not-the-password"
    And the user clicks "Log in"
    Then the page shows "Invalid username or password"
```

`${SHOP_PASSWORD}` is a secret reference: the value comes from an environment
variable at run time and never appears in files ([section 6](#6-secrets)).

### 4.4 Validate and compile

```bash
qa scenario validate
```

```
Validated 2 files, 3 scenarios: 0 errors, 0 warnings
```

```bash
qa scenario compile
```

```
READY        health.the-api-is-up  (scenarios/health.feature:2)
READY        sign-in.alice-signs-in  (scenarios/sign-in.feature:4)
READY        sign-in.wrong-password-is-rejected  (scenarios/sign-in.feature:12)

Compiled 3 specifications from 2 files: 3 ready, 0 needs review, 0 blocked, 0 unsupported
Specifications written to /home/me/my-shop-tests/.qa/specifications
```

Validation checks structure (empty scenarios, duplicate names, ...).
Compilation also matches every step against the step definitions; only
`READY` specifications run. Both commands exit with 1 on problems, so they fit
in CI. You can skip them: `qa test` compiles the file it runs. Details:
[scenarios.md](scenarios.md).

### 4.5 Run API scenarios

```bash
qa test --scenario health.feature
```

```
health.the-api-is-up  (scenarios/health.feature:2)
  PASSED    The API is up  (0.1s)
  execution 20261121-112822-97525e: PASSED  -> .qa/executions/20261121-112822-97525e/results.json
  report: .qa/executions/20261121-112822-97525e/report.html

Ran 1 specification from scenarios/health.feature on shop: 1 passed
```

`--scenario` accepts a path relative to the current directory, the project or
`scenarios/`. `-e NAME` selects another environment. The exit code is 0 only
when everything passed.

### 4.6 Run browser scenarios

If you installed the browser with `playwright install`, skip to the run.
Otherwise append to `qa.yaml`:

```yaml
adapters:
  playwright:
    executable_path: /path/to/chromium
```

Provide the secret and run:

```bash
export SHOP_PASSWORD=correct-password
```

```bash
qa test --scenario sign-in.feature
```

```
sign-in.alice-signs-in  (scenarios/sign-in.feature:4)
  PASSED    Alice signs in  (0.4s)
  execution 20261121-112839-6ba3f5: PASSED  -> .qa/executions/20261121-112839-6ba3f5/results.json
  report: .qa/executions/20261121-112839-6ba3f5/report.html
sign-in.wrong-password-is-rejected  (scenarios/sign-in.feature:12)
  PASSED    Wrong password is rejected  (0.3s)
  execution 20261121-112840-b15fdd: PASSED  -> .qa/executions/20261121-112840-b15fdd/results.json
  report: .qa/executions/20261121-112840-b15fdd/report.html

Ran 2 specifications from scenarios/sign-in.feature on shop: 2 passed
```

Each scenario is one specification and one execution. To see a failure,
change `"Welcome, Alice"` to `"Welcome, Bob"` and run again. The assertion
waits `timeout_seconds`, then fails:

```
  FAILED    Alice signs in  (10.4s)
            application_bug: the page does not show 'Welcome, Bob' (page: http://localhost:8000/dashboard)
            screenshot: .qa/executions/20261121-113407-2252b6/sign-in.alice-signs-in/screenshot.png
```

## 5. Results and history

Every execution has a folder `.qa/executions/<id>/`:

| File | Contents |
|------|----------|
| `report.html` | human-readable report; open it in a browser |
| `results.json` | machine-readable results (`ExecutionReport`) |
| `execution.log` | JSON Lines log of every step, adapter and timing event |
| `<test case id>/` | evidence: `page.json`, `http.json`, `screenshot.png` (on failure) |

List past executions, newest first:

```bash
qa execution list
```

```
20261121-112840-b15fdd  PASSED    2026-11-21 11:28     1.0s  shop       sign-in.wrong-password-is-rejected
20261121-112839-6ba3f5  PASSED    2026-11-21 11:28     0.9s  shop       sign-in.alice-signs-in
20261121-112822-97525e  PASSED    2026-11-21 11:28     0.1s  shop       health.the-api-is-up
```

Show one; a unique prefix of the id is enough:

```bash
qa execution show 20261121-112839
```

```
Execution     20261121-112839-6ba3f5
Status        PASSED
Specification sign-in.alice-signs-in
Plan          sign-in.alice-signs-in.fe.shop (fe, functional)
Environment   shop
...
Report:  .qa/executions/20261121-112839-6ba3f5/report.html
Results: .qa/executions/20261121-112839-6ba3f5/results.json
Log:     .qa/executions/20261121-112839-6ba3f5/execution.log
```

Statuses, failure classifications, modes and timeouts are explained in
[execution.md](execution.md).

## 6. Secrets

- Never write passwords, tokens or keys into `qa.yaml` or scenarios. `qa.yaml`
  rejects URLs with credentials, plaintext `Authorization`/`Cookie`/API-key
  headers and variables named like secrets.
- Refer to a secret as `${NAME}` in a step or in an environment header, and
  export `NAME` before `qa test`.
- Secret values are masked as `********` in the console, `results.json`,
  `execution.log`, evidence and the report.
- Plain values that differ per environment go to the environment's
  `variables` and are not masked.

Playwright traces (`trace: on-failure`) are not redacted; keep them off when
secrets are typed into the page. Full rules: [secrets.md](secrets.md).

## 7. Troubleshooting

Messages below are exactly what the platform prints.

```
Error: Invalid configuration in qa.yaml:
  - file not found; run `qa init` to create it
```

You are not in the project directory. `cd` into it or pass `-c path/to/qa.yaml`.

**`environment_error: playwright could not be prepared: cannot launch chromium: BrowserType.launch: Executable doesn't exist at ...`**
No browser for this Playwright version. Run `uv run playwright install
chromium` in the `qa-platform` directory, or set
`adapters.playwright.executable_path`. If the message says `Failed to launch
chromium because executable doesn't exist at <your path>`, the configured path
is wrong: it must be the browser binary itself, not its folder.

**`environment_error: cannot send GET /health: [Errno 111] Connection refused`**
(or `cannot open /login: ...` in the browser) — the application is not
running at the environment's URL. Start it or fix `base_url`/`services`.

**`environment_error: secret SHOP_PASSWORD is not set (export it as an environment variable)`**
Export the variable in the terminal that runs `qa test`.

**`NOT RUN  not executed (blocked): 1 step(s) cannot be resolved`**
followed by `line 4: action 'the user dances': no step definition matches this text` —
the step's wording matches no built-in step. Compare it with
[steps.md](steps.md); quotes around values are required.

**`scenarios/broken.feature:2: error [scenario.no-steps] scenario has no steps`**
followed by `... has errors; nothing was executed` — a validation error blocks
the whole file. Rule codes are listed in [scenarios.md](scenarios.md).

**`Error: scenario file x.feature not found (looked for: ...)`**
The message lists every place that was tried. Scenario files must be inside
the project.

**`Internal error: <ExceptionType>: ...`**
A bug in the platform, not in your project. Run the command again with
`QA_DEBUG=1` in front of it to see the full traceback, and report it.

**`Interrupted.`** (exit code 130)
You pressed Ctrl-C. The execution that was running is kept in the history as
`cancelled`; browser and HTTP clients are closed.

**`Error: unknown environment 'prod'; known: local, shop`**
Use one of the listed names with `-e`, or add the environment with
`qa project env add`.

**`Error: '2026' matches 9 executions (...); give more of the id`**
Give `qa execution show` a longer prefix.

**A result says `application_bug`, `environment_error`, `test_data_error`, ...**
That is the failure classification: see
[execution.md](execution.md#failure-classification) for what each means and
where to look first.
