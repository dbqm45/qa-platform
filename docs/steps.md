# Step definitions

## Built-in steps

### Navigation (`browser`, Playwright)

| Step | Action | Notes |
|------|--------|-------|
| `the user opens "<url>"` | `browser.open` | |
| `the user navigates to "<url>"` | `browser.navigate` | same behaviour as `opens`, reads better mid-scenario |
| `the user reloads the page` | `browser.reload` | |
| `the user goes back` | `browser.back` | fails if there is no previous page |

`<url>` is an absolute `http(s)://` URL or a path starting with `/`, resolved
against the environment's `base_url`. Other values (`file:`, `javascript:`,
`login.html`, URLs with credentials) are rejected when compiling.
All can be used with Given or When.

| Problem | Status | Classification |
|---------|--------|----------------|
| the page responds with HTTP 4xx/5xx | failed | `application_bug` |
| connection refused, DNS error, timeout | error | `environment_error` |
| relative URL but no `base_url` | error | `environment_error` |
| no previous page for `goes back` | failed | `application_bug` |

Every message includes the current page URL.

### Elements and locators

UI steps refer to elements with a locator, written as plain text or with an
explicit strategy:

| Written as | Finds |
|------------|-------|
| `"Log in"` | tries the strategies below in order |
| `"testid:login-button"` | `data-testid="login-button"` (attribute configurable) |
| `"role:button=Log in"` | ARIA role `button` with accessible name `Log in` (`role:heading` without a name) |
| `"label:Email"` | form control labelled `Email` |
| `"text:Welcome"` | element whose text is exactly `Welcome` |
| `"css:#login > button"` | CSS selector |

Plain text tries `testid`, then `role` (button, link, textbox, checkbox,
heading, …), then `label`, then `text`; the order is configurable with
`adapters.playwright.locator_strategies`. **CSS is only used when written
explicitly**, so it never wins over semantic locators silently.

- Only **visible** elements match.
- The first strategy that finds anything decides: one element is used,
  several are an error (`'Save' is ambiguous: 2 visible elements match by role: <button> "Save", …`).
- Locators wait up to the step timeout for the element to appear; a missing
  element fails with the strategies tried and the page URL.
- Malformed locators (`css:`, `role:=Save`) are rejected when compiling.

### Interactions (`browser`)

| Step | Action |
|------|--------|
| `the user clicks "<element>"` | `ui.click` |
| `the user fills "<element>" with "<value>"` | `ui.fill` |
| `the user selects "<option>" in "<element>"` | `ui.select` (option value or label) |
| `the user checks "<element>"` / `the user unchecks "<element>"` | `ui.check` / `ui.uncheck` |
| `the user submits the form` | `ui.submit`: the form of the focused field, or the only form on the page |

An element that cannot be used (disabled, not editable, covered) makes the
step **failed** with Playwright's reason; a closed browser is an
`environment_error`.

### UI assertions (`browser`, expectations)

| Step | Action |
|------|--------|
| `"<element>" is visible` / `"<element>" is hidden` | `ui.visible` / `ui.hidden` |
| `the page shows "<text>"` | `ui.text-present` (visible text, substring, case-insensitive) |
| `the URL is "<url or /path>"` | `ui.url-is` (a `/path` compares path, or path and query) |
| `the URL contains "<text>"` | `ui.url-contains` |
| `"<element>" is enabled` / `"<element>" is disabled` | `ui.enabled` / `ui.disabled` |
| `"<element>" has value "<value>"` | `ui.value` |

Values typed into password fields are treated as secrets and masked in
results and evidence. Reference real credentials as `${NAME}` (see
[`secrets.md`](secrets.md)).

Assertions wait up to the step timeout for the condition, then fail with what
was actually found (`'Email' has value '', expected 'x'`). Values of password
fields are masked in messages.

### API requests (`http`, HTTPX)

| Step | Action |
|------|--------|
| `the client sends <METHOD> "<url>"` | `api.send` |
| `the client sends <METHOD> "<url>" with:` + JSON doc string | `api.send-json` |
| `the client sets header "<name>" to "<value>"` | `api.header` (for the following requests) |
| `the client uses the token from "<field>"` | `api.token-from`: a field of the last JSON response becomes the `Bearer` token |
| `the client uses bearer token "<token>"` | `api.bearer` (use `${NAME}`) |

`<METHOD>` is `GET`, `POST`, `PUT`, `PATCH` or `DELETE`. `<url>` is an absolute
`http(s)://` URL or a path starting with `/`, resolved against the
environment's `api` service (configurable), else its `base_url`. The JSON body
is checked when compiling. Every test case gets a fresh client: no cookies,
headers or tokens are shared between test cases.

Example:

```gherkin
Given the client sends POST "/login" with:
  """
  {"username": "bob", "password": "${SHOP_PASSWORD}"}
  """
And the client uses the token from "token"
When the client sends GET "/orders"
Then the response status is 200
And the response field "orders" has 0 items
```

### API assertions (`http`, expectations on the last response)

| Step | Action |
|------|--------|
| `the response status is <code>` | `api.status` (100–599) |
| `the response header "<name>" is "<value>"` / `contains "<text>"` | `api.header-is` / `api.header-contains` |
| `the response field "<path>" is "<value>"` | `api.field-is` |
| `the response field "<path>" exists` | `api.field-exists` |
| `the response field "<path>" has <n> items` | `api.field-count` |
| `the response body contains "<text>"` | `api.body-contains` |

Paths: `status`, `order.total`, `orders[0].product`, `[1].id`. The expected
value is read as JSON when it is valid JSON (`4`, `6.0`, `true`, `null`,
`"\"4\""` for the string `"4"`), otherwise as text (`pear`); comparison is
type-exact, so `4` does not match `4.0`.

| Problem | Status | Classification |
|---------|--------|----------------|
| status, header, field or body differs; response is not JSON | failed | `application_bug` (message includes status, request and the start of the body) |
| connection refused, DNS error, timeout | error | `environment_error` |
| an assertion before any request | error | `test_implementation_error` |
| invalid method, URL, path, header name or JSON body | blocked at compile time | — |

## Unique test data

Two values are provided by the platform during an execution and can be used
in any step text, data table or doc string:

| Reference | Value | Example |
|-----------|-------|---------|
| `${RUN_ID}` | the execution id | `20261121-125129-0d376b` |
| `${UNIQUE}` | one value per test case, the same in all its steps | `202611211251290d376b2` |

```gherkin
Scenario: A new customer registers
  When the user fills "Email" with "qa-${UNIQUE}@example.com"
  And the user clicks "Register"
  Then the page shows "qa-${UNIQUE}@example.com"
```

- `${UNIQUE}` contains only lowercase letters and digits, so it fits usernames,
  e-mail addresses and URLs. It differs for every test case (including each
  row of a `Scenario Outline`) and every execution, so tests can run
  repeatedly, or in several environments, without colliding on data they
  create.
- The value of each test case is stored in `results.json` (`unique`) and in
  the log (`test-case-started`), so you can find the data a test created.
- Neither is a secret: they are not masked. Their names are reserved, so
  `variables` in `qa.yaml` cannot define them, and they take precedence over
  an environment variable of the same name.
- `${RUN_ID}` also works in environment `headers`; `${UNIQUE}` only in test
  case steps (elsewhere: `${UNIQUE} is only available in test case steps`).

## Writing step definitions

A step definition connects step text in scenarios to an implementation.
Resolution is deterministic: no step is ever guessed.

```python
from qa_core.steps.registry import StepRegistry
from qa_schemas.enums import StepKind

registry = StepRegistry()


@registry.step(
    "auth.sign-in",  # id = normalized action
    "the user signs in as {string} with password {string}",  # pattern
    kind=StepKind.ACTION,
    capability="browser",  # adapter capability needed
)
def sign_in(context, username: str, password: str) -> None: ...
```

| Part | Rules |
|------|-------|
| id | Stable identifier (`a-z 0-9 . : - _`), unique in the registry. Stored in specifications as the step's `action`. |
| pattern | A [Cucumber Expression](https://github.com/cucumber/cucumber-expressions#readme) or a compiled regex anchored with `^…$`. Must match the **whole** step text. |
| kind | `PRECONDITION` or `ACTION` for steps that do something, `EXPECTATION` for steps that check something. |
| capability | What the step needs from an adapter, e.g. `browser` or `http`. Collected into the specification's `required_capabilities`. |
| handler | First argument is the execution context; the remaining positional arguments receive the pattern's parameters, in order, and give them their names. |

## Parameters

| Expression | Matches | Value |
|------------|---------|-------|
| `{int}` | `42`, `-1` | `int` |
| `{float}` | `1.5` | `float` |
| `{word}` | one word without spaces | `str` |
| `{string}` | `"double"` or `'single'` quoted text | `str` (without quotes) |
| `{}` | anything | `str` |

Other Cucumber types (`{biginteger}`, `{bigdecimal}`, …) are rejected so that
values stay plain JSON. In regular expressions, a group whose regex is the
same as a built-in type is converted like it (`(\d+)` → `int`).

## Secrets in custom steps

Call `context.mark_secret(value)` for any value that must not appear in
results, reports or evidence. Values from `${NAME}` references are marked
automatically.

## Parameter validation

The handler's type annotations are the parameter schema. Every parameter
after `context` must be annotated (`Any` disables checking). Anything Pydantic
understands works, including constraints:

```python
from enum import StrEnum
from typing import Annotated, Literal
from pydantic import Field


class Method(StrEnum):
    GET = "GET"
    POST = "POST"


@registry.step("api.status", "the status is {int}", kind=StepKind.EXPECTATION, capability="http")
def status_is(context, code: Annotated[int, Field(ge=100, le=599)]) -> None: ...


@registry.step(
    "api.send", "the client sends {word} {string}", kind=StepKind.ACTION, capability="http"
)
def send(context, method: Method, path: str) -> None: ...  # receives Method.POST, not "POST"
```

Values are checked when scenarios are compiled: `Then the status is 999` is
unresolved (`api.status: invalid value 999 for parameter 'code': ...`), so its
specification is `blocked` and never executed. At execution time
`StepDefinition.bind()` validates again and returns the converted values.
Specifications store the raw JSON values.

### Data tables and doc strings

A step that needs the table or doc string written below it declares a
keyword-only parameter with that exact name; its annotation validates the
argument like any other parameter:

```python
@registry.step("ui.fill", "the user fills the form:", kind=StepKind.ACTION, capability="browser")
def fill(context, *, data_table: tuple[tuple[str, ...], ...]) -> None: ...


@registry.step("api.post", "the client posts to {string}:", kind=StepKind.ACTION, capability="http")
def post(context, path: str, *, doc_string: str) -> None: ...
```

A step without the required argument, or with an argument the definition
does not accept, is unresolved. Other keyword-only parameters are rejected
at registration.

## Kinds

- A step written with **Then** (or an `And`/`But` after it) resolves only to an
  `EXPECTATION` definition. An action can therefore never silently stand in
  for an assertion.
- **Given** and **When** steps resolve to `PRECONDITION` or `ACTION`
  definitions interchangeably (`Given the user is signed in` usually reuses
  the sign-in action).
- The same pattern may be registered once as an action and once as an
  expectation.

## Registration errors

Detected immediately when a definition is registered (`StepRegistrationError`):
duplicate id, duplicate pattern of a compatible kind, invalid expression,
unsupported parameter type, unanchored regex, handler without a context
argument, a handler whose parameter count differs from the pattern's, a
parameter without type annotation or with an annotation Pydantic cannot
validate, or an unknown keyword-only parameter.

## Resolution results

| Result | Reported reason |
|--------|-----------------|
| exactly one compatible definition matches | resolved: `action` and `parameters` are set |
| none matches | `no step definition matches this text` |
| only definitions of another kind match | `matches <id> (<kind>), which cannot be used as a <kind> step` |
| several compatible definitions match | `ambiguous: matches several steps (<ids>)` |
| one definition matches, but a value or argument is invalid | `<id>: invalid value ... for parameter ...`, `<id>: step ... requires a data table`, ... |

Unresolved steps keep `action: null` and are listed with test case, step
index, line, kind and reason.
