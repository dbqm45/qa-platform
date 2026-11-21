"""Project-level scenario workflows used by the CLI (TASK-022).

Discovery, parsing and validation are combined here so that commands stay thin
and the same workflow can be reused by other entry points.
"""

from pathlib import Path, PurePosixPath

from qa_core.config import load_config
from qa_core.files import write_text_atomically
from qa_core.init import PLATFORM_DIRNAME
from qa_core.scenarios.compilation import CompilationReport, DocumentCompilation, compile_documents
from qa_core.scenarios.parsing import parse_documents
from qa_core.scenarios.sources import DiscoveryResult, LocalFileSource
from qa_core.scenarios.validation import ValidationReport, validate
from qa_core.steps.registry import StepRegistry
from qa_schemas.enums import IssueSeverity
from qa_schemas.scenario import ValidationIssue


def validate_project(config_path: Path) -> ValidationReport:
    """Discover, parse and validate all scenarios of the project.

    Raises:
        ConfigError: the configuration cannot be loaded.
    """
    config = load_config(config_path)
    root = config_path.resolve().parent
    discovery = LocalFileSource.for_project(config.project, root).discover()
    report = validate(parse_documents(discovery.documents))

    issues = [*_discovery_issues(discovery, config.project.scenario_dir), *report.issues]
    issues.sort(key=lambda i: (str(i.path), i.line or 0, i.column or 0))
    return report.model_copy(update={"issues": tuple(issues)})


def _discovery_issues(discovery: DiscoveryResult, scenario_dir: Path) -> list[ValidationIssue]:
    issues = [
        ValidationIssue(
            path=problem.path,
            severity=IssueSeverity.ERROR,
            code="discovery",
            message=problem.message,
        )
        for problem in discovery.problems
    ]
    if not discovery.documents and not discovery.problems:
        issues.append(
            ValidationIssue(
                path=PurePosixPath(scenario_dir.as_posix()),
                severity=IssueSeverity.WARNING,
                code="discovery.no-files",
                message="no scenario files (*.feature) found",
            )
        )
    return issues


SPECIFICATIONS_DIRNAME = "specifications"


def compile_project(config_path: Path, registry: StepRegistry) -> CompilationReport:
    """Discover, parse and compile all scenarios of the project.

    Raises:
        ConfigError: the configuration cannot be loaded.
    """
    config = load_config(config_path)
    root = config_path.resolve().parent
    discovery = LocalFileSource.for_project(config.project, root).discover()
    report = compile_documents(
        parse_documents(discovery.documents),
        registry,
        base=PurePosixPath(config.project.scenario_dir.as_posix()),
    )
    unreadable = [
        DocumentCompilation(path=issue.path, issues=(issue,))
        for issue in _discovery_issues(discovery, config.project.scenario_dir)
    ]
    documents = sorted((*unreadable, *report.documents), key=lambda d: str(d.path))
    return CompilationReport(documents=tuple(documents))


def specifications_dir(config_path: Path) -> Path:
    return config_path.resolve().parent / PLATFORM_DIRNAME / SPECIFICATIONS_DIRNAME


def write_specifications(report: CompilationReport, directory: Path) -> list[Path]:
    """Write one ``<id>.json`` per compiled specification and remove stale ones.

    The directory belongs to the platform, so files that no longer correspond
    to a scenario are deleted. Each file is replaced atomically.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for compiled in report.specifications:
        path = directory / f"{compiled.specification.id}.json"
        write_text_atomically(path, compiled.model_dump_json(indent=2) + "\n")
        written.append(path)
    keep = set(written)
    for stale in directory.glob("*.json"):
        if stale not in keep:
            stale.unlink()
    return written
