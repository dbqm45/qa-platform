"""``qa test``: compile one scenario file, plan and execute its specifications (TASK-062).

Results of every execution are stored in ``.qa/executions/<id>/``:

- ``results.json`` -- the complete ``ExecutionReport`` (TASK-058);
- ``report.html`` -- human-readable report (TASK-059);
- ``<test case>/`` -- evidence written by the adapters;
- execution metadata (status, timestamps) is also kept in ``.qa/qa.db``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from qa_core.config import load_config
from qa_core.files import write_text_atomically
from qa_core.init import PLATFORM_DIRNAME
from qa_core.scenarios.compilation import compile_documents
from qa_core.scenarios.parsing import parse_documents
from qa_core.scenarios.sources import LocalFileSource
from qa_core.steps.registry import StepRegistry
from qa_core.storage import DATABASE_FILENAME, ExecutionRepository, ProjectRepository, open_database
from qa_execution.builtin import builtin_adapters, builtin_registry
from qa_execution.planning import PlanningError, create_plan
from qa_execution.registry import AdapterRegistry
from qa_execution.runner import ExecutionRequest, LocalRunner, NotExecutableError
from qa_reporting.html import write_html_report
from qa_schemas.compilation import CompiledSpecification
from qa_schemas.config import ProjectConfig
from qa_schemas.enums import ExecutionMode, ExecutionStatus, IssueSeverity, TestCategory
from qa_schemas.project import Environment
from qa_schemas.results import ExecutionReport
from qa_schemas.scenario import ValidationIssue

EXECUTIONS_DIRNAME = "executions"
RESULTS_FILENAME = "results.json"


class TestRunError(Exception):
    """The request cannot be carried out (unknown environment, missing file, ...)."""

    __test__ = False


@dataclass(frozen=True)
class SpecificationRun:
    compiled: CompiledSpecification
    report: ExecutionReport | None = None
    """None when the specification was not executed."""
    problem: str | None = None
    """Why it was not executed."""
    results_path: Path | None = None
    report_path: Path | None = None
    """``report.html`` next to ``results.json`` and the evidence."""


@dataclass(frozen=True)
class TestRun:
    __test__ = False

    project: str
    scenario: PurePosixPath
    environment: str
    issues: tuple[ValidationIssue, ...] = ()
    runs: tuple[SpecificationRun, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = ()
    """Problems that did not stop the run (e.g. a rerun of a changed scenario)."""

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is IssueSeverity.ERROR)

    @property
    def ok(self) -> bool:
        """Everything was valid, executed and passed."""
        return (
            not self.errors
            and bool(self.runs)
            and all(
                r.report is not None and r.report.execution.status is ExecutionStatus.PASSED
                for r in self.runs
            )
        )


def executions_dir(config_path: Path) -> Path:
    return config_path.resolve().parent / PLATFORM_DIRNAME / EXECUTIONS_DIRNAME


def run_scenario(
    config_path: Path,
    scenario: Path,
    *,
    environment: str | None = None,
    mode: ExecutionMode | None = None,
    category: TestCategory = TestCategory.FUNCTIONAL,
    steps: StepRegistry | None = None,
    adapters: AdapterRegistry | None = None,
    timeout: float | None = None,
) -> TestRun:
    """Compile ``scenario`` and execute every specification that is READY.

    Raises:
        ConfigError: ``qa.yaml`` cannot be loaded.
        StorageError: the local database is missing or unusable.
        TestRunError: the environment or scenario file cannot be used.
    """
    config = load_config(config_path)
    root = config_path.resolve().parent
    target = _environment(config, environment)
    relative = _locate(root, config, scenario)
    return run_file(
        config_path,
        config,
        PurePosixPath(relative.as_posix()),
        target,
        mode=mode,
        category=category,
        steps=steps,
        adapters=adapters,
        timeout=timeout,
    )


Select = Callable[[tuple[CompiledSpecification, ...]], tuple[CompiledSpecification, ...]]


def run_file(
    config_path: Path,
    config: ProjectConfig,
    scenario: PurePosixPath,
    environment: Environment,
    *,
    mode: ExecutionMode | None = None,
    category: TestCategory = TestCategory.FUNCTIONAL,
    steps: StepRegistry | None = None,
    adapters: AdapterRegistry | None = None,
    timeout: float | None = None,
    select: Select | None = None,
    rerun_of: str | None = None,
) -> TestRun:
    """Compile one scenario file (relative to the project root) and execute it.

    ``select`` picks the specifications to execute from the compiled ones (all
    by default); ``rerun_of`` links the new executions to the one they repeat.
    """
    root = config_path.resolve().parent
    steps = steps or builtin_registry()
    adapters = adapters or builtin_adapters()

    discovery = LocalFileSource(root, []).read_file(Path(scenario))
    if discovery.problems:
        problem = discovery.problems[0]
        raise TestRunError(f"{problem.path}: {problem.message}")
    report = compile_documents(
        parse_documents(discovery.documents),
        steps,
        base=PurePosixPath(config.project.scenario_dir.as_posix()),
        available_capabilities=adapters.available_capabilities,
    )
    [document] = report.documents
    if document.blocked:
        return TestRun(
            project=config.project.id,
            scenario=scenario,
            environment=environment.name,
            issues=document.issues,
        )
    specifications = select(document.specifications) if select else document.specifications

    output = executions_dir(config_path)
    runs: list[SpecificationRun] = []
    with open_database(root / PLATFORM_DIRNAME / DATABASE_FILENAME) as db:
        ProjectRepository(db).upsert(config.project)
        runner = LocalRunner(
            steps,
            adapters,
            evidence_root=output,
            store=ExecutionRepository(db),
            adapter_config=config.adapters,
        )
        for compiled in specifications:
            runs.append(
                _run_one(
                    runner,
                    config,
                    compiled,
                    environment,
                    adapters,
                    mode,
                    category,
                    output,
                    timeout,
                    rerun_of,
                )
            )
    return TestRun(
        project=config.project.id,
        scenario=scenario,
        environment=environment.name,
        issues=document.issues,
        runs=tuple(runs),
    )


# --- Internals ---------------------------------------------------------------


def _run_one(
    runner: LocalRunner,
    config: ProjectConfig,
    compiled: CompiledSpecification,
    environment: Environment,
    adapters: AdapterRegistry,
    mode: ExecutionMode | None,
    category: TestCategory,
    output: Path,
    timeout: float | None,
    rerun_of: str | None = None,
) -> SpecificationRun:
    if not compiled.status.is_executable:
        reasons = "; ".join(compiled.reasons) or compiled.status.value
        return SpecificationRun(
            compiled, problem=f"not executed ({compiled.status.value}): {reasons}"
        )
    try:
        plan = create_plan(
            compiled.specification,
            environment,
            adapters,
            mode=mode,
            category=category,
            execution_timeout=timeout,
        )
        report = runner.run(
            ExecutionRequest(config.project.id, compiled, plan, environment, rerun_of=rerun_of)
        )
    except (PlanningError, NotExecutableError) as error:
        return SpecificationRun(compiled, problem=f"not executed: {error}")

    results_path = output / report.execution.id / RESULTS_FILENAME
    results_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomically(results_path, report.model_dump_json(indent=2) + "\n")
    report_path = write_html_report(report, results_path.parent, compiled.specification)
    return SpecificationRun(
        compiled, report=report, results_path=results_path, report_path=report_path
    )


def _environment(config: ProjectConfig, name: str | None) -> Environment:
    project = config.project
    name = name or project.default_environment
    known = ", ".join(e.name for e in project.environments) or "none"
    if name is None:
        raise TestRunError(f"no --environment given and no default_environment set; known: {known}")
    environment = project.environment(name)
    if environment is None:
        raise TestRunError(f"unknown environment {name!r}; known: {known}")
    return environment


def _locate(root: Path, config: ProjectConfig, scenario: Path) -> Path:
    """Path of the scenario relative to the project root.

    Tried in order: as given (absolute or relative to the current directory),
    relative to the project root, relative to ``scenario_dir``.
    """
    candidates = [scenario] if scenario.is_absolute() else [
        Path.cwd() / scenario,
        root / scenario,
        root / config.project.scenario_dir / scenario,
    ]  # fmt: skip
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            if not resolved.is_relative_to(root):
                raise TestRunError(f"{scenario} is outside the project ({root})")
            return resolved.relative_to(root)
    looked = ", ".join(dict.fromkeys(str(c.resolve()) for c in candidates))
    raise TestRunError(f"scenario file {scenario} not found (looked for: {looked})")
