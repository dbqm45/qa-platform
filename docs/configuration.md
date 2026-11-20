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
```

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
| `project.environments[].timeout_seconds` | number | `30` | `0 < value ≤ 3600`. |

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

Referencing secrets (e.g. from environment variables) is added in TASK-055.

## Programmatic use

```python
from pathlib import Path
from qa_core.config import ConfigError, load_config

try:
    config = load_config(Path("qa.yaml"))
except ConfigError as error:
    print(error)            # readable, multi-line message
    error.issues            # list[str], one entry per problem
```
