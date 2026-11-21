"""Compilation: scenarios -> specifications with an explicit status (TASK-026).

Per document: validate -> convert -> resolve steps -> assign a status.

| Status       | When                                                                  |
|--------------|-----------------------------------------------------------------------|
| BLOCKED      | the file has validation or conversion errors, or a step is unresolved |
| UNSUPPORTED  | a required capability is not provided by any available adapter        |
| NEEDS_REVIEW | a test case has no expectation, so it would pass without checking     |
| READY        | otherwise                                                             |

Only READY specifications are executable (``CompilationStatus.is_executable``).
"""

from collections.abc import Collection, Iterable
from pathlib import PurePosixPath

from qa_core.scenarios.conversion import ConversionError, convert_feature
from qa_core.scenarios.validation import validate_result
from qa_core.steps.registry import StepRegistry
from qa_core.steps.resolution import resolve_specification
from qa_schemas.base import SchemaModel
from qa_schemas.compilation import CompiledSpecification, UnresolvedStep
from qa_schemas.enums import CompilationStatus, IssueSeverity
from qa_schemas.scenario import ParseResult, ValidationIssue
from qa_schemas.specification import TestSpecification

_NO_BASE = PurePosixPath()


class DocumentCompilation(SchemaModel):
    path: PurePosixPath
    issues: tuple[ValidationIssue, ...] = ()
    """Validation findings (errors block the whole document) and conversion errors."""
    specifications: tuple[CompiledSpecification, ...] = ()

    @property
    def blocked(self) -> bool:
        return any(i.severity is IssueSeverity.ERROR for i in self.issues)


class CompilationReport(SchemaModel):
    documents: tuple[DocumentCompilation, ...] = ()

    @property
    def specifications(self) -> tuple[CompiledSpecification, ...]:
        return tuple(s for d in self.documents for s in d.specifications)

    def count(self, status: CompilationStatus) -> int:
        return sum(1 for s in self.specifications if s.status is status)

    @property
    def ok(self) -> bool:
        """No blocked document and no blocked specification."""
        return not any(d.blocked for d in self.documents) and not self.count(
            CompilationStatus.BLOCKED
        )


def compile_documents(
    results: Iterable[ParseResult],
    registry: StepRegistry,
    *,
    base: PurePosixPath = _NO_BASE,
    available_capabilities: Collection[str] | None = None,
) -> CompilationReport:
    """Compile parsed documents.

    ``available_capabilities=None`` skips the capability check (no adapters
    known yet); pass a collection to mark specifications UNSUPPORTED.
    """
    return CompilationReport(
        documents=tuple(
            _compile_document(result, registry, base, available_capabilities) for result in results
        )
    )


def _compile_document(
    result: ParseResult,
    registry: StepRegistry,
    base: PurePosixPath,
    available: Collection[str] | None,
) -> DocumentCompilation:
    issues = validate_result(result)
    if result.feature is None or any(i.severity is IssueSeverity.ERROR for i in issues):
        return DocumentCompilation(path=result.document, issues=tuple(issues))
    try:
        specifications = convert_feature(result.feature, base)
    except ConversionError as error:
        conversion_issue = ValidationIssue(
            path=error.path,
            line=error.line,
            severity=IssueSeverity.ERROR,
            code="conversion",
            message=str(error).removeprefix(f"{error.path}:{error.line}: "),
        )
        return DocumentCompilation(path=result.document, issues=(*issues, conversion_issue))

    return DocumentCompilation(
        path=result.document,
        issues=tuple(issues),
        specifications=tuple(
            _compile_specification(s, registry, available) for s in specifications
        ),
    )


def _compile_specification(
    specification: TestSpecification,
    registry: StepRegistry,
    available: Collection[str] | None,
) -> CompiledSpecification:
    resolution = resolve_specification(specification, registry)
    resolved = resolution.specification
    status, reasons = _status(resolved, resolution.unresolved, available)
    return CompiledSpecification(
        status=status, reasons=reasons, unresolved=resolution.unresolved, specification=resolved
    )


def source_step_key(step: UnresolvedStep) -> tuple[int | None, str]:
    """Identifies the source step: outline cases repeat it with different values."""
    return (step.line, "") if step.line is not None else (None, step.text)


def _status(
    specification: TestSpecification,
    unresolved: tuple[UnresolvedStep, ...],
    available: Collection[str] | None,
) -> tuple[CompilationStatus, tuple[str, ...]]:
    if unresolved:
        steps = len({source_step_key(u) for u in unresolved})
        return CompilationStatus.BLOCKED, (f"{steps} step(s) cannot be resolved",)

    if available is not None:
        missing = sorted(set(specification.required_capabilities) - set(available))
        if missing:
            return CompilationStatus.UNSUPPORTED, (
                f"no adapter provides the required capabilities: {', '.join(missing)}",
            )

    unchecked = [case.id for case in specification.test_cases if not case.expected_results]
    if unchecked:
        return CompilationStatus.NEEDS_REVIEW, (
            f"test case(s) without any expectation step: {', '.join(unchecked)}",
        )
    return CompilationStatus.READY, ()
