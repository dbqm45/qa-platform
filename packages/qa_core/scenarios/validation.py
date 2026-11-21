"""Scenario validation: find problems before compilation (TASK-020).

Every rule is deterministic and reports the file and line of the problem.
Errors block compilation; warnings do not.
"""

import re
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import PurePosixPath

from gherkin.dialect import Dialect

from qa_schemas.base import PATTERN_DESCRIPTIONS, TAG_PATTERN, SchemaModel
from qa_schemas.enums import IssueSeverity, StepKeywordType
from qa_schemas.scenario import (
    Examples,
    ParsedFeature,
    ParseResult,
    Scenario,
    ScenarioStep,
    ValidationIssue,
)

PLACEHOLDER = re.compile(r"<([^<>\n]+)>")
_TAG = re.compile(TAG_PATTERN)
"""Scenario Outline placeholder, e.g. ``<user name>``."""

_ERROR = IssueSeverity.ERROR
_WARNING = IssueSeverity.WARNING
_UNRESOLVABLE_FIRST = {StepKeywordType.CONJUNCTION, StepKeywordType.UNKNOWN}


class ValidationReport(SchemaModel):
    issues: tuple[ValidationIssue, ...] = ()
    documents: int = 0
    scenarios: int = 0

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is _ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is _WARNING)

    @property
    def ok(self) -> bool:
        """True when there are no errors (warnings are allowed)."""
        return not self.errors


def validate(results: Iterable[ParseResult]) -> ValidationReport:
    issues: list[ValidationIssue] = []
    documents = scenarios = 0
    for result in results:
        documents += 1
        scenarios += len(result.feature.scenarios) if result.feature else 0
        issues.extend(validate_result(result))
    return ValidationReport(issues=tuple(issues), documents=documents, scenarios=scenarios)


def validate_result(result: ParseResult) -> list[ValidationIssue]:
    """All issues of one parsed document, in source order, without duplicates."""
    if result.issues:
        return [
            ValidationIssue(
                path=i.path,
                line=i.line,
                column=i.column,
                severity=_ERROR,
                code="syntax",
                message=i.message,
            )
            for i in result.issues
        ]
    if result.feature is None:
        return [
            ValidationIssue(
                path=result.document,
                severity=_ERROR,
                code="document.no-feature",
                message="file contains no Feature",
            )
        ]

    feature = result.feature
    found = list(_feature_issues(feature))
    unique = list(dict.fromkeys(found))  # Background issues repeat per scenario
    return sorted(unique, key=lambda i: (i.line or 0, i.column or 0))


# --- Rules -------------------------------------------------------------------


def _issue(
    path: PurePosixPath, line: int, code: str, message: str, severity: IssueSeverity = _ERROR
) -> ValidationIssue:
    return ValidationIssue(path=path, line=line, severity=severity, code=code, message=message)


def _feature_issues(feature: ParsedFeature) -> Iterator[ValidationIssue]:
    path = feature.path

    if not feature.name.strip():
        yield _issue(path, feature.line, "feature.missing-name", "Feature has no name")
    if not feature.scenarios:
        yield _issue(
            path, feature.line, "feature.no-scenarios", "Feature has no scenarios", _WARNING
        )

    yield from _tag_issues(feature.tags, feature.line, path)
    keywords = _bare_step_keywords(feature.language)
    names = Counter(s.name.strip() for s in feature.scenarios if s.name.strip())
    for scenario in feature.scenarios:
        yield from _keywords_in_description(scenario, keywords, path)
        name = scenario.name.strip()
        if not name:
            yield _issue(path, scenario.line, "scenario.missing-name", "scenario has no name")
        elif names[name] > 1:
            yield _issue(
                path,
                scenario.line,
                "scenario.duplicate-name",
                f"scenario name {name!r} is used {names[name]} times in this file",
            )
        yield from _scenario_issues(scenario, path)


def _tag_issues(tags: Iterable[str], line: int, path: PurePosixPath) -> Iterator[ValidationIssue]:
    for tag in tags:
        if not _TAG.match(tag):
            yield _issue(
                path, line, "tag.invalid", f"tag @{tag} {PATTERN_DESCRIPTIONS[TAG_PATTERN]}"
            )


def _bare_step_keywords(language: str) -> set[str]:
    dialect = Dialect.for_name(language)
    if dialect is None:
        return set()
    keywords = (
        dialect.given_keywords + dialect.when_keywords + dialect.then_keywords
        + dialect.and_keywords + dialect.but_keywords
    )  # fmt: skip
    return {k.strip() for k in keywords if k.strip() != "*"}


def _keywords_in_description(
    scenario: Scenario, keywords: set[str], path: PurePosixPath
) -> Iterator[ValidationIssue]:
    """A bare keyword line (``Given`` with no text) is parsed as description text."""
    for line in scenario.description.splitlines():
        if line.strip() in keywords:
            yield _issue(
                path,
                scenario.line,
                "step.empty",
                f"step {line.strip()!r} has no text (Gherkin treats it as description, "
                "so the step is silently ignored)",
            )


def _scenario_issues(scenario: Scenario, path: PurePosixPath) -> Iterator[ValidationIssue]:
    yield from _tag_issues(scenario.tags, scenario.line, path)
    if scenario.rule:
        yield from _tag_issues(scenario.rule.tags, scenario.rule.line, path)
    if not scenario.steps:
        yield _issue(path, scenario.line, "scenario.no-steps", "scenario has no steps")

    for step in (*scenario.background, *scenario.steps):
        if not step.text.strip():
            yield _issue(path, step.line, "step.empty", f"step {step.keyword!r} has no text")

    sequence = (*scenario.background, *scenario.steps)
    if sequence and sequence[0].keyword_type in _UNRESOLVABLE_FIRST:
        first = sequence[0]
        yield _issue(
            path,
            first.line,
            "step.ambiguous-kind",
            f"first step starts with {first.keyword!r}; use Given, When or Then so its "
            "meaning (precondition, action or expectation) is clear",
        )

    if scenario.is_outline or scenario.examples:
        yield from _outline_issues(scenario, path)


def _outline_issues(scenario: Scenario, path: PurePosixPath) -> Iterator[ValidationIssue]:
    if not scenario.examples:
        yield _issue(path, scenario.line, "outline.no-examples", "Scenario Outline has no Examples")
        return

    used = _placeholders(scenario)
    for examples in scenario.examples:
        yield from _examples_issues(examples, used, path)


def _examples_issues(
    examples: Examples, used: dict[str, int], path: PurePosixPath
) -> Iterator[ValidationIssue]:
    if examples.header is None:
        yield _issue(path, examples.line, "examples.no-table", "Examples has no table")
        return
    if not examples.rows:
        yield _issue(path, examples.line, "examples.no-rows", "Examples table has no data rows")

    columns = Counter(examples.header)
    for column, count in columns.items():
        if not column.strip():
            yield _issue(
                path,
                examples.line,
                "examples.empty-column",
                "Examples table has an empty column name",
            )
        elif count > 1:
            yield _issue(
                path,
                examples.line,
                "examples.duplicate-column",
                f"column {column!r} appears {count} times",
            )
    for placeholder, line in used.items():
        if placeholder not in columns:
            yield _issue(
                path,
                line,
                "examples.missing-column",
                f"placeholder <{placeholder}> has no column in Examples at line {examples.line}",
            )
    for column in columns:
        if column.strip() and column not in used:
            yield _issue(
                path,
                examples.line,
                "examples.unused-column",
                f"column {column!r} is not used by any step",
                _WARNING,
            )


def _placeholders(scenario: Scenario) -> dict[str, int]:
    """Placeholder name -> first line where it is used (name, steps and their arguments).

    Background steps are excluded: Gherkin does not substitute values in them.
    """
    found: dict[str, int] = {}

    def collect(text: str, line: int) -> None:
        for name in PLACEHOLDER.findall(text):
            found.setdefault(name, line)

    collect(scenario.name, scenario.line)
    for step in scenario.steps:
        for text in _step_texts(step):
            collect(text, step.line)
    return found


def _step_texts(step: ScenarioStep) -> Iterator[str]:
    yield step.text
    if step.data_table:
        for row in step.data_table:
            yield from row
    if step.doc_string:
        yield step.doc_string.content
