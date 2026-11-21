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
