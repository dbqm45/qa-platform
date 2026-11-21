# Secrets

## Referencing secrets in scenarios

Never write real credentials into scenarios. Reference an environment
variable instead:

```gherkin
When the user fills "Password" with "${SHOP_PASSWORD}"
```

```bash
export SHOP_PASSWORD='...'
```

```bash
uv run qa test --scenario login.feature
```

- `${NAME}` (uppercase letters, digits, `_`) is resolved **only when the step
  runs**, in step parameters, data tables and doc strings.
- Scenario files, compiled specifications, `results.json` and `report.html`
  contain only the reference text `${SHOP_PASSWORD}`.
- A missing variable makes the test case `error` / `environment_error`:
  `secret SHOP_PASSWORD is not set` (the message never contains a value).

## Plain variables and default headers per environment

```yaml
environments:
  - name: staging
    variables:
      SHOP_USER: qa-bot             # plain: shown in results as is
    headers:
      X-Api-Key: ${SHOP_API_KEY}    # secret: from the environment variable
```

`${NAME}` is resolved from the platform's built-in values first (`RUN_ID`,
`UNIQUE`, see [steps.md](steps.md#unique-test-data)), then the target
environment's `variables` (plain, not masked), otherwise from environment
variables (secret, masked). So the
same scenario can run against environments with different users or keys.
Headers listed under `headers` are sent with every API request; a missing
secret makes each test case `error` / `environment_error`. `qa.yaml` rejects
plain values for sensitive headers and variables with secret-like names.

## What is masked

Every execution has a redactor. Known secret values and sensitive patterns are
replaced with `********` in all free text of the results (step texts, test case
names, failure messages, notes, evidence descriptions, cleanup errors) and in
`page.json` evidence.

| Masked | Source |
|--------|--------|
| values of resolved `${NAME}` references | always |
| values typed into a password field (`<input type="password">`) by `the user fills` | detected at run time, so literal test passwords are masked too |
| values a step implementation marks with `context.mark_secret(value)` | custom steps |
| `password=…`, `token=…`, `secret=…`, `api_key=…`, `auth=…`, `session=…`, `pin=…`, `otp=…` in URLs and form data | pattern, always |
| the same names as JSON string fields: `"password": "…"`, `"token": "…"` | pattern, always (request and response bodies) |
| tokens taken with `the client uses the token from` / `uses bearer token`, values of sensitive headers set with `sets header` | API steps |
| `Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, … headers in `http.json` | always |
| `Bearer …`, `Basic …`, `Token …` credentials | pattern, always |

Identifiers (specification, test case and plan ids), statuses and actions are
never altered, so a secret that happens to be a common word cannot corrupt
results.

## Limitations

- What an author writes literally into a scenario file stays in that file and
  in its compiled specification. Use `${NAME}` for anything real.
- Values shorter than 4 characters are not masked as substrings (they would
  hide unrelated text); the patterns above still mask them in parameters and
  headers.
- Matching is exact and case-sensitive.
- Playwright traces (`trace: on-failure|always`) record everything that
  happens on the page, including typed values. They are off by default; treat
  them as sensitive.
- Screenshots show what the page shows. Browsers render password fields as
  dots, but other fields are visible.
