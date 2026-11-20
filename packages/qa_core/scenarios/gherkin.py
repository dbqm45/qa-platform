"""Gherkin parsing with the official Cucumber parser (TASK-019).

The Cucumber AST is converted into the platform's own models
(``qa_schemas.scenario``), so nothing downstream depends on the library.
Parsing is purely syntactic and deterministic; no step is interpreted here.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any, cast

from gherkin.dialect import Dialect
from gherkin.errors import CompositeParserException, ParserException
from gherkin.parser import Parser

from qa_schemas.enums import StepKeywordType
from qa_schemas.scenario import (
    DocString,
    Examples,
    ExamplesRow,
    ParsedFeature,
    ParseIssue,
    ParseResult,
    RuleReference,
    Scenario,
    ScenarioDocument,
    ScenarioStep,
)

Node = Mapping[str, Any]

_KEYWORD_TYPES = {
    "Context": StepKeywordType.CONTEXT,
    "Action": StepKeywordType.ACTION,
    "Outcome": StepKeywordType.OUTCOME,
    "Conjunction": StepKeywordType.CONJUNCTION,
}

_TOKEN_NAMES = {
    "#EOF": "end of file",
    "#Language": "language header",
    "#TagLine": "tags",
    "#FeatureLine": "Feature",
    "#RuleLine": "Rule",
    "#BackgroundLine": "Background",
    "#ScenarioLine": "Scenario",
    "#ExamplesLine": "Examples",
    "#StepLine": "step",
    "#DocStringSeparator": "doc string",
    "#TableRow": "table row",
    "#Other": "text",
}
_LOCATION_PREFIX = re.compile(r"^\(\d+:\d+\): ")
_UNEXPECTED = re.compile(r"^expected: (?P<expected>.*), got '(?P<got>.*)'$", re.S)


def parse_gherkin(document: ScenarioDocument) -> ParseResult:
    """Parse one Gherkin document. Syntax errors are returned, never raised."""
    try:
        ast = cast(Node, Parser().parse(document.content))
    except CompositeParserException as exc:
        return _failure(document, exc.errors)
    except ParserException as exc:
        return _failure(document, [exc])

    feature = ast.get("feature")
    if feature is None:  # empty file or only comments
        return ParseResult(document=document.path)
    return ParseResult(document=document.path, feature=_feature(document, feature))


# --- Errors ------------------------------------------------------------------


def _failure(document: ScenarioDocument, errors: Iterable[ParserException]) -> ParseResult:
    issues = [
        ParseIssue(
            path=document.path,
            line=error.location.get("line") or None,
            column=error.location.get("column") or None,
            message=_readable(str(error)),
        )
        for error in errors
    ]
    issues.sort(key=lambda issue: (issue.line or 0, issue.column or 0))
    return ParseResult(document=document.path, issues=tuple(issues))


def _readable(message: str) -> str:
    """Turn the parser's token-level message into something a test author understands."""
    message = _LOCATION_PREFIX.sub("", message)
    match = _UNEXPECTED.match(message)
    if match is None:
        return message
    expected = [
        _TOKEN_NAMES[token.strip()]
        for token in match["expected"].split(",")
        if token.strip() in _TOKEN_NAMES
    ]
    return f"unexpected {match['got'].strip()!r}; expected {', '.join(expected)}"


# --- AST conversion ----------------------------------------------------------


def _feature(document: ScenarioDocument, node: Node) -> ParsedFeature:
    dialect = Dialect.for_name(node["language"])
    if dialect is None:  # the parser has already rejected unknown languages
        raise ValueError(f"unknown Gherkin language {node['language']!r}")
    outline_keywords = set(dialect.scenario_outline_keywords)

    scenarios: list[Scenario] = []
    background: tuple[ScenarioStep, ...] = ()
    for child in node["children"]:
        if "background" in child:
            background = _steps(child["background"]["steps"])
        elif "scenario" in child:
            scenarios.append(_scenario(child["scenario"], background, None, outline_keywords))
        elif "rule" in child:
            scenarios.extend(_rule(child["rule"], background, outline_keywords))

    return ParsedFeature(
        path=document.path,
        content_hash=document.content_hash,
        language=node["language"],
        name=node["name"],
        keyword=node["keyword"],
        line=node["location"]["line"],
        description=_description(node),
        tags=_tags(node),
        scenarios=tuple(scenarios),
    )


def _rule(
    node: Node, feature_background: tuple[ScenarioStep, ...], outline_keywords: set[str]
) -> list[Scenario]:
    rule = RuleReference(name=node["name"], line=node["location"]["line"], tags=_tags(node))
    background = feature_background
    scenarios = []
    for child in node["children"]:
        if "background" in child:
            background = feature_background + _steps(child["background"]["steps"])
        elif "scenario" in child:
            scenarios.append(_scenario(child["scenario"], background, rule, outline_keywords))
    return scenarios


def _scenario(
    node: Node,
    background: tuple[ScenarioStep, ...],
    rule: RuleReference | None,
    outline_keywords: set[str],
) -> Scenario:
    return Scenario(
        name=node["name"],
        keyword=node["keyword"],
        line=node["location"]["line"],
        description=_description(node),
        tags=_tags(node),
        rule=rule,
        background=background,
        steps=_steps(node["steps"]),
        is_outline=node["keyword"] in outline_keywords,
        examples=tuple(_examples(e) for e in node.get("examples", [])),
    )


def _steps(nodes: Iterable[Node]) -> tuple[ScenarioStep, ...]:
    return tuple(
        ScenarioStep(
            keyword=node["keyword"].strip(),
            keyword_type=_KEYWORD_TYPES.get(node.get("keywordType", ""), StepKeywordType.UNKNOWN),
            text=node["text"],
            line=node["location"]["line"],
            data_table=_table(node["dataTable"]) if "dataTable" in node else None,
            doc_string=(
                DocString(
                    content=node["docString"]["content"],
                    media_type=node["docString"].get("mediaType") or None,
                )
                if "docString" in node
                else None
            ),
        )
        for node in nodes
    )


def _examples(node: Node) -> Examples:
    header = node.get("tableHeader")
    return Examples(
        name=node["name"],
        line=node["location"]["line"],
        tags=_tags(node),
        header=_cells(header) if header else None,
        rows=tuple(
            ExamplesRow(line=row["location"]["line"], values=_cells(row))
            for row in node.get("tableBody", [])
        ),
    )


def _table(node: Node) -> tuple[tuple[str, ...], ...]:
    return tuple(_cells(row) for row in node["rows"])


def _cells(row: Node) -> tuple[str, ...]:
    return tuple(cell["value"] for cell in row["cells"])


def _tags(node: Node) -> tuple[str, ...]:
    return tuple(tag["name"].removeprefix("@") for tag in node.get("tags", []))


def _description(node: Node) -> str:
    return "\n".join(line.strip() for line in str(node.get("description", "")).splitlines()).strip()
