# Scenarios

Scenarios are written in [Gherkin](https://cucumber.io/docs/gherkin/reference/)
in `.feature` files under the project's `scenario_dir`. Any Gherkin language
can be used (`# language: pl`).

## Supported constructs

Feature, Rule, Background, Scenario / Example, Scenario Outline / Template,
Examples, Given / When / Then / And / But / `*`, tags, descriptions,
data tables and doc strings.

## Validating

```bash
qa scenario validate [-c qa.yaml]
```

Finds all `.feature` files under `scenario_dir` (relative to `qa.yaml`),
parses and validates them, and prints one line per finding followed by a summary:

```
<path>:<line>[:<column>]: <error|warning> [<code>] <message>
```

Exits with `1` if there is at least one error, otherwise `0`.

## Validation rules

Every scenario file is validated before compilation. Errors block compilation;
warnings do not. Each finding reports `path:line[:column]`, a severity and a
stable code.

| Code | Severity | Meaning |
|------|----------|---------|
| `discovery` | error | The scenario directory is missing, or a file cannot be read, is not UTF-8 or is larger than 1 MB. |
| `discovery.no-files` | warning | No `.feature` files were found. |
| `syntax` | error | Invalid Gherkin syntax. |
| `document.no-feature` | error | The file contains no `Feature`. |
| `feature.missing-name` | error | `Feature:` has no name. |
| `feature.no-scenarios` | warning | The feature has no scenarios. |
| `scenario.missing-name` | error | A scenario has no name. |
| `scenario.duplicate-name` | error | Two scenarios in one file have the same name (also across Rules). |
| `scenario.no-steps` | error | A scenario has no steps of its own (Background alone is not enough). |
| `step.empty` | error | A step has no text. This includes a bare keyword such as `Given` on its own line, which Gherkin would otherwise silently treat as description text. |
| `step.ambiguous-kind` | error | The first step (including Background) starts with `And`, `But` or `*`, so it is unclear whether it is a precondition, an action or an expectation. |
| `outline.no-examples` | error | A Scenario Outline has no `Examples`. |
| `examples.no-table` | error | `Examples:` has no table. |
| `examples.no-rows` | error | The Examples table has a header but no data rows. |
| `examples.empty-column` | error | A column header is empty. |
| `examples.duplicate-column` | error | A column header appears twice. |
| `examples.missing-column` | error | A `<placeholder>` used in the scenario name, steps, data tables or doc strings has no column in an Examples table. Checked for every Examples table separately. |
| `examples.unused-column` | warning | A column is not used by any placeholder. |

Notes:

- Placeholders in Background steps are not substituted by Gherkin, so they do
  not count as using a column.
- A `Scenario` with `Examples` is validated like a Scenario Outline.

## Change detection

Every parsed scenario has a `content_hash` (sha256) of its meaningful content:
name, keyword, tags, Rule, Background and own steps (keyword, text, data
table, doc string) and Examples. Line numbers, indentation and descriptions are
not included, so moving a scenario or editing another scenario in the same
file does not change its hash. The file itself has a separate hash of its raw
bytes.
