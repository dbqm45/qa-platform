# Step definitions

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

@registry.step("api.send", "the client sends {word} {string}", kind=StepKind.ACTION, capability="http")
def send(context, method: Method, path: str) -> None: ...   # receives Method.POST, not "POST"
```

Values are checked when scenarios are compiled: `Then the status is 999` is
unresolved (`api.status: invalid value 999 for parameter 'code': ...`), so its
specification is `blocked` and never executed. At execution time
`StepDefinition.bind()` validates again and returns the converted values.
Specifications store the raw JSON values.

### Data tables and doc strings

A step that needs the table or doc string written below it declares a
keyword-only parameter with that exact name:

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
