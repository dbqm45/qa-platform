"""Entry point of the ``qa`` command."""

import os
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from typer.exceptions import TyperException

from qa_core import __version__
from qa_core.config import CONFIG_FILENAME, ConfigError, load_config
from qa_core.config_edit import ConfigEditError, add_environment, add_repository
from qa_core.files import write_text_atomically
from qa_core.init import InitError, initialize_project
from qa_core.scenarios.compilation import source_step_key
from qa_core.scenarios.service import (
    compile_project,
    specifications_dir,
    validate_project,
    write_specifications,
)
from qa_core.scenarios.sources import LocalFileSource
from qa_core.storage import StorageError
from qa_execution.builtin import builtin_adapters, builtin_registry
from qa_execution.history import ExecutionNotFoundError, list_executions, show_execution
from qa_execution.rerun import NothingToRerunError, rerun_execution
from qa_execution.service import TestRun, TestRunError, run_scenario
from qa_execution.summary import summarize
from qa_schemas.compilation import CompiledSpecification
from qa_schemas.enums import (
    CompilationStatus,
    ExecutionMode,
    ExecutionStatus,
    IssueSeverity,
    TestCategory,
)
from qa_schemas.results import ExecutionReport, TestResult

app = typer.Typer(
    name="qa",
    help="Local-first, deterministic QA automation platform.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

project_app = typer.Typer(help="Inspect and edit the project configuration.", no_args_is_help=True)
repo_app = typer.Typer(
    help="Manage repositories of the application under test.", no_args_is_help=True
)
env_app = typer.Typer(help="Manage target environments.", no_args_is_help=True)
scenario_app = typer.Typer(help="Validate and compile scenarios.", no_args_is_help=True)
app.add_typer(project_app, name="project")
app.add_typer(scenario_app, name="scenario")
execution_app = typer.Typer(help="Inspect past executions.", no_args_is_help=True)
app.add_typer(execution_app, name="execution")
project_app.add_typer(repo_app, name="repo")
project_app.add_typer(env_app, name="env")

EXIT_ERROR = 1
EXIT_INTERRUPTED = 130  # 128 + SIGINT, as shells report it
DEBUG_VARIABLE = "QA_DEBUG"

ConfigOption = Annotated[
    Path, typer.Option("--config", "-c", help="Path to the project configuration file.")
]


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"qa-platform {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """Local-first, deterministic QA automation platform."""


@app.command()
def init(
    directory: Annotated[
        Path, typer.Argument(help="Project directory; created if missing.")
    ] = Path("."),
    project_id: Annotated[
        str | None,
        typer.Option("--id", help="Project identifier. Default: derived from the name."),
    ] = None,
    name: Annotated[
        str | None, typer.Option(help="Project display name. Default: directory name.")
    ] = None,
) -> None:
    """Initialize a QA project. Safe to re-run: existing files are never overwritten."""
    with _cli_errors():
        result = initialize_project(directory, project_id=project_id, name=name)

    for path in result.created:
        typer.echo(f"  created  {path}")
    for path in result.existing:
        typer.echo(f"  exists   {path}")

    if Path(CONFIG_FILENAME) in result.existing and (project_id or name):
        typer.echo(
            f"Warning: {CONFIG_FILENAME} already exists; --id/--name were ignored.", err=True
        )

    project = result.config.project
    verb = "Initialized" if result.created else "Already initialized"
    typer.echo(f"{verb} project '{project.id}' in {result.root}")


@repo_app.command("add")
def repo_add(
    name: Annotated[str, typer.Argument(help="Repository name (identifier).")],
    path: Annotated[str | None, typer.Option(help="Local checkout location.")] = None,
    url: Annotated[str | None, typer.Option(help="Remote http(s) location.")] = None,
    config: ConfigOption = Path(CONFIG_FILENAME),
) -> None:
    """Add a repository to qa.yaml. At least one of --path / --url is required."""
    with _cli_errors():
        add_repository(config, name, path=path, url=url)
    typer.echo(f"Added repository '{name}' to {config}")


@project_app.command("show")
def project_show(config: ConfigOption = Path(CONFIG_FILENAME)) -> None:
    """Show the project configuration: repositories, environments, scenarios, adapters.

    Secret values are never shown: headers appear as written (with ``${NAME}``
    references), variables by name only.
    """
    with _cli_errors():
        loaded = load_config(config)
        root = config.resolve().parent
        discovery = LocalFileSource.for_project(loaded.project, root).discover()
    project = loaded.project
    typer.echo(f"Project      {project.name} ({project.id})")
    typer.echo(f"Config       {_display_path(config.resolve())}")
    scenario_dir = _display_path(root / project.scenario_dir)
    typer.echo(f"Scenarios    {scenario_dir}  ({_plural(len(discovery.documents), 'file')})")
    for problem in discovery.problems:
        typer.echo(f"             {problem.path}: {problem.message}")

    typer.echo("\nRepositories")
    if not project.repositories:
        typer.echo("  (none)")
    for repo in project.repositories:
        location = ", ".join(str(x) for x in (repo.path, repo.url) if x is not None)
        typer.echo(f"  {repo.name:<12} {location}")

    typer.echo("\nEnvironments")
    if not project.environments:
        typer.echo("  (none)")
    for env in project.environments:
        default = "  (default)" if env.name == project.default_environment else ""
        protected = "  (protected: read-only)" if env.protected else ""
        typer.echo(f"  {env.name}{default}{protected}")
        typer.echo(f"    base_url   {env.base_url or '-'}")
        for name, url in env.services.items():
            typer.echo(f"    service    {name} = {url}")
        typer.echo(f"    timeout    {env.timeout_seconds:g} s")
        if env.variables:
            typer.echo(f"    variables  {', '.join(sorted(env.variables))}")
        for name, value in env.headers.items():
            typer.echo(f"    header     {name}: {value}")
        for hook in env.setup:
            typer.echo(f"    setup      {hook}")
        for hook in env.cleanup:
            typer.echo(f"    cleanup    {hook}")
        for name, file in env.mocks.items():
            typer.echo(f"    mock       {name} = {file}")

    typer.echo("\nAdapters")
    for adapter in builtin_adapters().adapters:
        configured = "configured" if adapter.name in loaded.adapters else "defaults"
        capabilities = ", ".join(sorted(adapter.capabilities))
        typer.echo(f"  {adapter.name:<12} {capabilities}  ({configured})")


@env_app.command("add")
def env_add(
    name: Annotated[str, typer.Argument(help="Environment name (identifier).")],
    base_url: Annotated[str | None, typer.Option(help="Entry point for browser tests.")] = None,
    service: Annotated[
        list[str] | None,
        typer.Option(help="Service endpoint as NAME=URL; repeatable.", metavar="NAME=URL"),
    ] = None,
    timeout: Annotated[
        float | None, typer.Option(help="Default timeout in seconds.", min=0)
    ] = None,
    default: Annotated[
        bool, typer.Option("--default", help="Make it the default environment.")
    ] = False,
    protected: Annotated[
        bool,
        typer.Option("--protected", help="Read-only: tests may not change data here (production)."),
    ] = False,
    config: ConfigOption = Path(CONFIG_FILENAME),
) -> None:
    """Add an environment to qa.yaml."""
    with _cli_errors():
        add_environment(
            config,
            name,
            base_url=base_url,
            services=_parse_services(service or []),
            timeout_seconds=timeout,
            make_default=default,
            protected=protected,
        )
    suffix = " as the default environment" if default else ""
    typer.echo(f"Added environment '{name}' to {config}{suffix}")


def _parse_services(values: list[str]) -> dict[str, str]:
    services: dict[str, str] = {}
    for value in values:
        key, sep, url = value.partition("=")
        if not sep or not key or not url:
            raise typer.BadParameter(f"expected NAME=URL, got {value!r}", param_hint="--service")
        if key in services:
            raise typer.BadParameter(f"service {key!r} given twice", param_hint="--service")
        services[key] = url
    return services


@scenario_app.command("validate")
def scenario_validate(config: ConfigOption = Path(CONFIG_FILENAME)) -> None:
    """Validate all scenarios of the project. Exits with 1 if any error is found."""
    with _cli_errors():
        report = validate_project(config)

    for issue in report.issues:
        typer.echo(f"{issue.location()}: {issue.severity.value} [{issue.code}] {issue.message}")

    errors, warnings = len(report.errors), len(report.warnings)
    summary = (
        f"Validated {_plural(report.documents, 'file')}, {_plural(report.scenarios, 'scenario')}: "
        f"{_plural(errors, 'error')}, {_plural(warnings, 'warning')}"
    )
    if report.issues:
        typer.echo("")
    typer.echo(summary)
    if not report.ok:
        raise typer.Exit(EXIT_ERROR)


@scenario_app.command("compile")
def scenario_compile(config: ConfigOption = Path(CONFIG_FILENAME)) -> None:
    """Compile scenarios into Test Specifications and save them in .qa/specifications.

    Exits with 1 if a file has errors or a specification is BLOCKED.
    """
    with _cli_errors():
        report = compile_project(
            config,
            builtin_registry(),
            available_capabilities=builtin_adapters().available_capabilities,
        )
        output = specifications_dir(config)
        write_specifications(report, output)

    for document in report.documents:
        errors = [i for i in document.issues if i.severity is IssueSeverity.ERROR]
        if errors:
            typer.echo(f"{'BLOCKED':<13}{document.path}  ({_plural(len(errors), 'error')})")
            for issue in errors:
                typer.echo(f"  {issue.location()}: [{issue.code}] {issue.message}")
        for compiled in document.specifications:
            spec = compiled.specification
            typer.echo(
                f"{compiled.status.value.upper():<13}{spec.id}  "
                f"({spec.source.path}:{spec.source.line})"
            )
            for reason in compiled.reasons:
                typer.echo(f"  {reason}")
            _print_unresolved(compiled, indent="  ")

    counts = ", ".join(
        f"{report.count(status)} {status.value.replace('_', ' ')}" for status in CompilationStatus
    )
    blocked_files = sum(1 for d in report.documents if d.blocked)
    typer.echo("")
    typer.echo(
        f"Compiled {_plural(len(report.specifications), 'specification')} from "
        f"{_plural(len(report.documents), 'file')}: {counts}"
        + (f"; {_plural(blocked_files, 'file')} with errors" if blocked_files else "")
    )
    typer.echo(f"Specifications written to {output}")
    if not report.ok:
        raise typer.Exit(EXIT_ERROR)


@app.command("test")
def test_command(
    scenario: Annotated[
        Path,
        typer.Option(
            "--scenario",
            "-s",
            help="Scenario file (relative to here, the project or scenario_dir).",
        ),
    ],
    environment: Annotated[
        str | None,
        typer.Option(
            "--environment", "-e", help="Target environment. Default: default_environment."
        ),
    ] = None,
    mode: Annotated[
        ExecutionMode | None,
        typer.Option(
            help="fe, be or full. Default: derived from the steps used.", case_sensitive=False
        ),
    ] = None,
    category: Annotated[
        TestCategory, typer.Option(help="Test category.", case_sensitive=False)
    ] = TestCategory.FUNCTIONAL,
    timeout: Annotated[
        float | None,
        typer.Option(help="Limit for each execution in seconds (default 600).", min=1, max=86_400),
    ] = None,
    mock: Annotated[
        list[str] | None,
        typer.Option(
            "--mock",
            help="Answer this service from its mock file (environment mocks:); repeatable.",
            metavar="SERVICE",
        ),
    ] = None,
    allow_writes: Annotated[
        bool,
        typer.Option(
            "--allow-writes", help="Allow changing data in a protected (read-only) environment."
        ),
    ] = False,
    json_path: Annotated[
        Path | None,
        typer.Option(
            "--json",
            help="Also write a JSON summary of the run (for CI) to this file.",
            dir_okay=False,
        ),
    ] = None,
    config: ConfigOption = Path(CONFIG_FILENAME),
) -> None:
    """Compile a scenario file and execute its ready specifications.

    Exits with 0 only if every specification was executed and passed.
    """
    with _cli_errors():
        run = run_scenario(
            config,
            scenario,
            environment=environment,
            mode=mode,
            category=category,
            steps=builtin_registry(),
            adapters=builtin_adapters(),
            timeout=timeout,
            allow_writes=allow_writes,
            mocks=mock or [],
        )
    _print_test_run(run)
    if json_path is not None:
        _write_summary(run, config, json_path)
    if not run.ok:
        raise typer.Exit(EXIT_ERROR)


@app.command("rerun")
def rerun_command(
    execution_id: Annotated[str, typer.Argument(help="Execution id, or a unique prefix of it.")],
    failed_only: Annotated[
        bool, typer.Option("--failed-only", help="Only the test cases that did not pass.")
    ] = False,
    timeout: Annotated[
        float | None,
        typer.Option(help="Limit for the execution in seconds (default 600).", min=1, max=86_400),
    ] = None,
    allow_writes: Annotated[
        bool,
        typer.Option(
            "--allow-writes", help="Allow changing data in a protected (read-only) environment."
        ),
    ] = False,
    json_path: Annotated[
        Path | None,
        typer.Option(
            "--json", help="Also write a JSON summary of the run (for CI).", dir_okay=False
        ),
    ] = None,
    config: ConfigOption = Path(CONFIG_FILENAME),
) -> None:
    """Run an earlier execution again: same environment, mode and category,
    the scenario as it is now.

    Exits with 0 only if everything that was rerun passed.
    """
    with _cli_errors():
        try:
            run = rerun_execution(
                config,
                execution_id,
                failed_only=failed_only,
                steps=builtin_registry(),
                adapters=builtin_adapters(),
                timeout=timeout,
                allow_writes=allow_writes,
            )
        except NothingToRerunError as error:
            typer.echo(f"Nothing to rerun: {error}")
            return
    for warning in run.warnings:
        typer.echo(f"Warning: {warning}")
    _print_test_run(run)
    if json_path is not None:
        _write_summary(run, config, json_path)
    if not run.ok:
        raise typer.Exit(EXIT_ERROR)


def _write_summary(run: TestRun, config: Path, path: Path) -> None:
    summary = summarize(run, config.resolve().parent)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomically(path, summary.model_dump_json(indent=2) + "\n")
    except OSError as error:
        typer.echo(f"Error: cannot write {path}: {error.strerror or error}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
    typer.echo(f"summary: {_display_path(path.resolve())}")


def _print_unresolved(compiled: CompiledSpecification, indent: str) -> None:
    """One line per source step that matches no step definition."""
    cases_per_step = Counter(source_step_key(step) for step in compiled.unresolved)
    shown: set[tuple[int | None, str]] = set()
    for step in compiled.unresolved:
        key = source_step_key(step)
        if key in shown:  # outline cases repeat the same source step
            continue
        shown.add(key)
        repeated = f" (in {cases_per_step[key]} test cases)" if cases_per_step[key] > 1 else ""
        typer.echo(
            f"{indent}line {step.line}: {step.kind.value} {step.text!r}: {step.reason}{repeated}"
        )


def _print_test_run(run: TestRun) -> None:
    for issue in run.errors:
        typer.echo(f"{issue.location()}: error [{issue.code}] {issue.message}")
    if run.errors:
        typer.echo(
            f"\n{run.scenario} has errors; nothing was executed (see `qa scenario validate`)"
        )
        return

    counts: Counter[str] = Counter()
    for spec_run in run.runs:
        spec = spec_run.compiled.specification
        typer.echo(f"{spec.id}  ({spec.source.path}:{spec.source.line})")
        if spec_run.report is None:
            counts["not executed"] += 1
            typer.echo(f"  NOT RUN  {spec_run.problem}")
            _print_unresolved(spec_run.compiled, indent=" " * 11)
            continue
        report = spec_run.report
        counts[report.execution.status.value] += 1
        for result in report.results:
            _print_result(result)
            evidence_dir = spec_run.results_path.parent if spec_run.results_path else None
            if result.status is not ExecutionStatus.PASSED and evidence_dir is not None:
                for ref in result.evidence:
                    if ref.kind == "screenshot":
                        typer.echo(
                            f"            screenshot: {_display_path(evidence_dir / ref.path)}"
                        )
        _print_execution_problems(report)
        typer.echo(
            f"  execution {report.execution.id}: {report.execution.status.value.upper()}  "
            f"-> {_display_path(spec_run.results_path) if spec_run.results_path else '-'}"
        )
        if spec_run.report_path is not None:
            typer.echo(f"  report: {_display_path(spec_run.report_path)}")

    summary = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
    mocked = f" (mocked: {', '.join(run.mocked)})" if run.mocked else ""
    typer.echo(
        f"\nRan {_plural(len(run.runs), 'specification')} from {run.scenario} "
        f"on {run.environment}{mocked}: {summary or 'nothing to run'}"
    )


@execution_app.command("list")
def execution_list(
    limit: Annotated[int, typer.Option(help="How many executions to show.", min=1)] = 20,
    config: ConfigOption = Path(CONFIG_FILENAME),
) -> None:
    """List the most recent executions."""
    with _cli_errors():
        executions = list_executions(config, limit)
    if not executions:
        typer.echo("No executions yet; run `qa test`.")
        return
    for execution in executions:
        started = execution.started_at or execution.created_at
        duration = (
            f"{(execution.finished_at - execution.started_at).total_seconds():.1f}s"
            if execution.started_at and execution.finished_at
            else "-"
        )
        typer.echo(
            f"{execution.id}  {execution.status.value.upper():<9} "
            f"{started.astimezone():%Y-%m-%d %H:%M}  {duration:>7}  "
            f"{execution.environment:<10} {execution.specification_id}"
        )


@execution_app.command("show")
def execution_show(
    execution_id: Annotated[str, typer.Argument(help="Execution id, or a unique prefix of it.")],
    config: ConfigOption = Path(CONFIG_FILENAME),
) -> None:
    """Show the status, results and report location of one execution."""
    with _cli_errors():
        details = show_execution(config, execution_id)
    execution = details.execution
    typer.echo(f"Execution     {execution.id}")
    typer.echo(f"Status        {execution.status.value.upper()}")
    typer.echo(f"Specification {execution.specification_id}")
    typer.echo(
        f"Plan          {execution.plan_id} ({execution.mode.value}, {execution.category.value})"
    )
    typer.echo(f"Environment   {execution.environment}")
    if execution.rerun_of:
        typer.echo(f"Rerun of      {execution.rerun_of}")
    if execution.started_at:
        typer.echo(f"Started       {execution.started_at.astimezone():%Y-%m-%d %H:%M:%S %Z}")
    if execution.started_at and execution.finished_at:
        seconds = (execution.finished_at - execution.started_at).total_seconds()
        typer.echo(f"Duration      {seconds:.1f}s")

    report = details.report
    if report is not None and report.mocked:
        typer.echo(f"Mocked        {', '.join(report.mocked)}")
    if report is None:
        typer.echo("\nNo results recorded (the execution may have been interrupted).")
    else:
        typer.echo("")
        for result in report.results:
            _print_result(result)
        _print_execution_problems(report)

    typer.echo("")
    for label, path in (
        ("Report", details.report_path),
        ("Results", details.results_path),
        ("Log", details.log_path),
    ):
        typer.echo(f"{label + ':':<9}{_display_path(path) if path else 'not available'}")


def _print_execution_problems(report: ExecutionReport) -> None:
    """Execution-level failure (unless every test case already shows it) and cleanup errors."""
    failure = report.failure
    shown = {r.failure.message for r in report.results if r.failure is not None}
    if failure is not None and not (report.results and shown == {failure.message}):
        typer.echo(f"  {failure.classification.value}: {failure.message}")
    for error in report.cleanup_errors:
        typer.echo(f"  cleanup: {error}")


def _print_result(result: TestResult) -> None:
    seconds = result.duration_ms / 1000
    typer.echo(f"  {result.status.value.upper():<9} {result.name}  ({seconds:.1f}s)")
    if result.failure is not None:
        typer.echo(f"            {result.failure.classification.value}: {result.failure.message}")
    for note in result.notes:
        typer.echo(f"            note: {note}")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


@contextmanager
def _cli_errors() -> Iterator[None]:
    """Turn expected domain errors into a message and exit code 1."""
    try:
        yield
    except (
        ConfigError,
        ConfigEditError,
        InitError,
        StorageError,
        TestRunError,
        ExecutionNotFoundError,
    ) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
    except (typer.Exit, typer.Abort, TyperException):
        raise  # normal exits and usage errors are handled by Typer
    except KeyboardInterrupt:
        # The runner has already marked a running execution as cancelled.
        typer.echo("\nInterrupted.", err=True)
        raise typer.Exit(EXIT_INTERRUPTED) from None
    except Exception as error:
        if os.environ.get(DEBUG_VARIABLE) == "1":
            raise
        typer.echo(
            f"Internal error: {type(error).__name__}: {error}\n"
            f"This is a bug in qa-platform. Run again with {DEBUG_VARIABLE}=1 for the traceback.",
            err=True,
        )
        raise typer.Exit(EXIT_ERROR) from None
