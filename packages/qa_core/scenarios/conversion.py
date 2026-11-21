"""Scenario -> Test Specification conversion (TASK-023).

Turns validated, parsed scenarios into runner-independent specifications:

- ``And`` / ``But`` / ``*`` take the kind of the previous step;
- a Scenario Outline becomes one test case per Examples row, with values
  substituted in the name, step texts, data tables and doc strings;
- ids are derived deterministically from the file path and scenario name;
- nothing about execution (URLs, adapters, environments) is added.

Input must have passed validation (TASK-020); anything that still cannot be
represented raises :class:`ConversionError` with the source location.
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from pathlib import PurePosixPath

from pydantic import ValidationError

from qa_core.scenarios.validation import PLACEHOLDER
from qa_schemas.enums import StepKeywordType, StepKind
from qa_schemas.scenario import DocString, Examples, ParsedFeature, Scenario, ScenarioStep
from qa_schemas.specification import (
    SourceReference,
    SpecificationMetadata,
    Step,
    TestCase,
    TestSpecification,
)

_KIND_BY_KEYWORD = {
    StepKeywordType.CONTEXT: StepKind.PRECONDITION,
    StepKeywordType.ACTION: StepKind.ACTION,
    StepKeywordType.OUTCOME: StepKind.EXPECTATION,
}
_MAX_SLUG = 80
_NO_BASE = PurePosixPath()
_TRANSLITERATE = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "ß": "ss"})


class ConversionError(Exception):
    """A scenario cannot be represented as a Test Specification."""

    def __init__(self, path: PurePosixPath, line: int, message: str) -> None:
        self.path = path
        self.line = line
        super().__init__(f"{path}:{line}: {message}")


def convert_feature(
    feature: ParsedFeature, base: PurePosixPath = _NO_BASE
) -> list[TestSpecification]:
    """One specification per scenario, in source order.

    ``base`` (usually the scenario directory) is removed from the path when
    building ids, so ``scenarios/auth/login.feature`` yields ``auth.login.*``.
    """
    prefix = _file_prefix(feature.path, base)
    ids = _unique_ids(prefix, feature.scenarios)
    return [
        _specification(feature, scenario, spec_id)
        for scenario, spec_id in zip(feature.scenarios, ids, strict=True)
    ]


# --- Ids ---------------------------------------------------------------------


def slugify(text: str) -> str:
    """Lowercase ASCII words joined by ``-``; accents are removed (``Żółw`` -> ``zolw``)."""
    ascii_text = (
        unicodedata.normalize("NFKD", text.translate(_TRANSLITERATE))
        .encode("ascii", "ignore")
        .decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:_MAX_SLUG].rstrip("-")


def _file_prefix(path: PurePosixPath, base: PurePosixPath) -> str:
    relative = path.relative_to(base) if path.is_relative_to(base) else path
    parts = [slugify(part) for part in relative.with_suffix("").parts]
    return ".".join(part for part in parts if part) or "feature"


def _unique_ids(prefix: str, scenarios: Iterable[Scenario]) -> list[str]:
    """``prefix.slug``; repeated slugs get ``-2``, ``-3``... in source order."""
    seen: Counter[str] = Counter()
    ids = []
    for scenario in scenarios:
        slug = slugify(scenario.name) or f"scenario-{scenario.line}"
        seen[slug] += 1
        suffix = "" if seen[slug] == 1 else f"-{seen[slug]}"
        ids.append(f"{prefix}.{slug}{suffix}")
    return ids


# --- Specification -----------------------------------------------------------


def _specification(feature: ParsedFeature, scenario: Scenario, spec_id: str) -> TestSpecification:
    try:
        return TestSpecification(
            id=spec_id,
            source=SourceReference(
                path=feature.path,
                feature=feature.name,
                scenario=scenario.name,
                line=scenario.line,
                content_hash=scenario.content_hash,
            ),
            test_cases=tuple(_test_cases(feature, scenario, spec_id)),
            metadata=SpecificationMetadata(
                tags=_tags(feature, scenario),
                description=scenario.description or None,
            ),
        )
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_url=False)
        )
        raise ConversionError(feature.path, scenario.line, problems) from None


def _tags(feature: ParsedFeature, scenario: Scenario) -> tuple[str, ...]:
    """Feature, Rule and scenario tags, in that order, without duplicates."""
    rule_tags = scenario.rule.tags if scenario.rule else ()
    return tuple(dict.fromkeys((*feature.tags, *rule_tags, *scenario.tags)))


def _test_cases(feature: ParsedFeature, scenario: Scenario, spec_id: str) -> Iterator[TestCase]:
    if not (scenario.is_outline or scenario.examples):
        yield TestCase(id=spec_id, name=scenario.name, steps=_steps(feature, scenario, {}))
        return

    rows = list(_example_rows(scenario.examples))
    names = [_substitute(scenario.name, values) for values in rows]
    repeated = {name for name, count in Counter(names).items() if count > 1}
    for number, (values, name) in enumerate(zip(rows, names, strict=True), start=1):
        yield TestCase(
            id=f"{spec_id}:{number}",
            name=f"{name} #{number}" if name in repeated else name,
            steps=_steps(feature, scenario, values),
            parameters=values,
        )


def _example_rows(examples: Iterable[Examples]) -> Iterator[dict[str, str]]:
    for table in examples:
        if table.header is None:
            continue
        for row in table.rows:
            yield dict(zip(table.header, row.values, strict=True))


def _steps(
    feature: ParsedFeature, scenario: Scenario, values: Mapping[str, str]
) -> tuple[Step, ...]:
    """Background (not substituted, as in Gherkin) followed by the scenario's own steps."""
    no_values: Mapping[str, str] = {}
    sequence = [(step, no_values) for step in scenario.background]
    sequence += [(step, values) for step in scenario.steps]

    steps: list[Step] = []
    previous: StepKind | None = None
    for source, substitutions in sequence:
        kind = _KIND_BY_KEYWORD.get(source.keyword_type, previous)
        if kind is None:
            raise ConversionError(
                feature.path, source.line, f"cannot tell what kind of step {source.keyword!r} is"
            )
        steps.append(_step(source, kind, substitutions))
        previous = kind
    return tuple(steps)


def _step(source: ScenarioStep, kind: StepKind, values: Mapping[str, str]) -> Step:
    doc = source.doc_string
    return Step(
        kind=kind,
        keyword=source.keyword,
        text=_substitute(source.text, values),
        line=source.line,
        data_table=(
            tuple(tuple(_substitute(cell, values) for cell in row) for row in source.data_table)
            if source.data_table is not None
            else None
        ),
        doc_string=(
            DocString(content=_substitute(doc.content, values), media_type=doc.media_type)
            if doc is not None
            else None
        ),
    )


def _substitute(text: str, values: Mapping[str, str]) -> str:
    """Replace ``<name>`` with its value; unknown placeholders are left as written."""
    if not values:
        return text
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)
