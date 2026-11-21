# Configuration (`qa.yaml`)

Each project has one `qa.yaml` at its root. Relative paths in it are relative
to the directory containing the file. A complete example is in
[`examples/qa.yaml`](../examples/qa.yaml).

```yaml
version: 1                      # configuration format version (optional, default 1)

project:
  id: shop                      # required, identifier
  name: Example Shop            # required, 1–200 characters
  scenario_dir: scenarios       # default: scenarios
  default_environment: local    # must name one of `environments`

  repositories:                 # read-only for the platform
    - name: web
      path: ../shop-web         # local checkout, and/or
      url: https://example.com/org/shop-web

  environments:
    - name: local
      base_url: http://localhost:3000     # entry point for browser tests
      services:                           # named service endpoints
        api: http://localhost:8000
      timeout_seconds: 30                 # default 30, max 3600
      variables:                          # plain values for ${NAME} in scenarios
        SHOP_USER: alice
      headers:                            # sent with every API request
        Accept-Language: en
        X-Api-Key: ${SHOP_API_KEY}        # secrets only as references
```

## Adapter settings

Optional, per adapter:

```yaml
adapters:
  playwright:
    browser: chromium          # chromium | firefox | webkit
    headless: true
    executable_path: null      # path to a browser binary; default: the one Playwright installed
    viewport_width: 1280       # 200..7680
    viewport_height: 720       # 200..4320
    locator_strategies: [testid, role, label, text]   # order for plain-text locators; css not allowed
    test_id_attribute: data-testid
    screenshot: on-failure     # off | on-failure | always
    trace: off                 # off | on-failure | always (traces are large)
  httpx:
    service: api               # environment service used as base URL (else base_url)
    verify_tls: true
    follow_redirects: false    # assert redirects explicitly by default
    max_body_bytes: 10000      # body size kept as evidence per request/response
```

Each section is validated by its adapter when an execution starts (unknown
fields are rejected then), not when `qa.yaml` is loaded.

## Field reference

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `version` | `1` | `1` | Any other value is rejected. |
| `project.id` | identifier | — | Lowercase letter first; then lowercase letters, digits, `-`, `_`; max 64. |
| `project.name` | text | — | Surrounding whitespace is stripped. |
| `project.scenario_dir` | path | `scenarios` | |
| `project.default_environment` | identifier | none | Must match an environment `name`. |
| `project.repositories[].name` | identifier | — | Unique within the project. |
| `project.repositories[].path` | path | none | At least one of `path` / `url` is required. |
| `project.repositories[].url` | http(s) URL | none | |
| `project.environments[].name` | identifier | — | Unique within the project. |
| `project.environments[].base_url` | http(s) URL | none | |
| `project.environments[].services` | map identifier → URL | `{}` | |
| `project.environments[].timeout_seconds` | number | `30` | `0 < value ≤ 3600`. Step timeout. |
| `project.environments[].variables` | map `NAME` → text | `{}` | Plain values for `${NAME}`; names like `*_PASSWORD`, `*_TOKEN`, `*_SECRET`, `*_KEY` are rejected, and so are the built-in `RUN_ID` and `UNIQUE` ([steps.md](steps.md#unique-test-data)). |
| `project.environments[].headers` | map header → text | `{}` | Default API headers; `Authorization`, `X-Api-Key`, `Cookie`, … must contain a `${NAME}` reference. |
| `project.environments[].setup` | list of `METHOD path` | `[]` | Requests sent before every execution, e.g. `POST /reset` ([execution.md](execution.md#setup-and-cleanup-requests)). |
| `project.environments[].cleanup` | list of `METHOD path` | `[]` | Requests sent after every execution, also when it failed. |
| `project.environments[].mocks` | map service → file | `{}` | Mock files that can replace a service with `qa test --mock NAME` ([execution.md](execution.md#mocked-services)). Each key must be a `services` entry. |
| `project.environments[].protected` | bool | `false` | Read-only: tests may not change data here unless `--allow-writes` is given ([execution.md](execution.md#protected-environments)). |

## Validation rules

- **Unknown fields are errors.** A typo such as `enviroments` is reported with
  a suggestion (`did you mean 'environments'?`).
- **Duplicate keys are errors** (plain YAML would silently keep the last one).
- **Only plain YAML is accepted.** Tags that construct Python objects are rejected.
- **All problems are reported at once**, each with its location:

```
Invalid configuration in qa.yaml:
  - project.id: must start with a lowercase letter and contain only lowercase letters, digits, '-' or '_' (max 64 characters) (got 'Shop')
  - project.enviroments: unknown field; did you mean 'environments'?
```

## Credentials

`qa.yaml` must never contain credentials, and the schema enforces it:

- there is no field that can hold a password, token or API key — such keys
  are rejected as unknown fields;
- URLs with embedded credentials (`https://user:token@host`) are rejected,
  and the rejected value is not echoed in the error message.

- sensitive headers (`Authorization`, `X-Api-Key`, `Cookie`, …) must contain a
  `${NAME}` reference, and variables with secret-like names are rejected.

Secrets are referenced as `${NAME}` and come from environment variables; see
[`secrets.md`](secrets.md).

## Inspecting the configuration

`qa project show [-c PATH]` prints the project, its repositories,
environments (base URL, services, timeout, variable names, headers as
written), the scenario directory with the number of scenario files, and the
available adapters with their capabilities. It shows no secret values:
`${NAME}` references stay unresolved and variable values are left out.

## Editing from the command line

| Command | Effect |
|---------|--------|
| `qa project repo add NAME [--path PATH] [--url URL]` | Appends to `project.repositories`. |
| `qa project env add NAME [--base-url URL] [--service NAME=URL ...] [--timeout S] [--default] [--protected]` | Appends to `project.environments`; `--default` also sets `default_environment`, `--protected` makes it read-only. |

Both accept `-c/--config PATH` (default: `qa.yaml` in the current directory).

- The current file must be valid; otherwise nothing is changed.
- The new entry and the resulting file are validated before anything is written;
  duplicate names are rejected.
- The file is replaced atomically (temporary file + rename), keeping its permissions.
- Comments, key order and quoting are preserved. Values are written exactly as
  typed (no URL normalization). Indentation is normalized to 2 spaces for
  mappings and 4/2 for list items.

## Programmatic use

```python
from pathlib import Path
from qa_core.config import ConfigError, load_config

try:
    config = load_config(Path("qa.yaml"))
except ConfigError as error:
    print(error)  # readable, multi-line message
    error.issues  # list[str], one entry per problem
```
