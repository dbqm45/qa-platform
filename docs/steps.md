# Step definitions

A step definition connects step text in scenarios to an implementation.
Resolution is deterministic: no step is ever guessed.

```python
from qa_core.steps.registry import StepRegistry
from qa_schemas.enums import StepKind

registry = StepRegistry()

@registry.step(
    "auth.sign-in",                                          # id = normalized action
    "the user signs in as {string} with password {string}",  # pattern
    kind=StepKind.ACTION,
    capability="browser",                                    # adapter capability needed
)
def sign_in(context, username: str, password: str) -> None:
    ...
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
argument, or a handler whose parameter count differs from the pattern's.

## Resolution results

| Result | Reported reason |
|--------|-----------------|
| exactly one compatible definition matches | resolved: `action` and `parameters` are set |
| none matches | `no step definition matches this text` |
| only definitions of another kind match | `matches <id> (<kind>), which cannot be used as a <kind> step` |
| several compatible definitions match | `ambiguous: matches several steps (<ids>)` |

Unresolved steps keep `action: null` and are listed with test case, step
index, line, kind and reason.
