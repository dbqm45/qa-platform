"""Choosing a parser by document format (TASK-019).

Adding a format means adding a parser to ``PARSERS``; sources are unaffected.
"""

from collections.abc import Callable, Iterable

from qa_core.scenarios.gherkin import parse_gherkin
from qa_schemas.enums import ScenarioFormat
from qa_schemas.scenario import ParseResult, ScenarioDocument

Parser = Callable[[ScenarioDocument], ParseResult]

PARSERS: dict[ScenarioFormat, Parser] = {ScenarioFormat.GHERKIN: parse_gherkin}


def parse_document(document: ScenarioDocument) -> ParseResult:
    return PARSERS[document.format](document)


def parse_documents(documents: Iterable[ScenarioDocument]) -> list[ParseResult]:
    return [parse_document(document) for document in documents]
