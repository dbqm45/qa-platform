"""Entry point of the ``qa`` command."""

from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from qa_core.config import CONFIG_FILENAME, ConfigError
from qa_core.config_edit import ConfigEditError, add_environment, add_repository
from qa_core.init import InitError, initialize_project
from qa_core.scenarios.compilation import source_step_key
from qa_core.scenarios.service import (
    compile_project,
    specifications_dir,
    validate_project,
    write_specifications,
)
from qa_core.steps.builtin import builtin_registry
from qa_core.storage import StorageError
from qa_execution.registry import builtin_adapters
from qa_schemas.enums import CompilationStatus, IssueSeverity

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
project_app.add_typer(repo_app, name="repo")
project_app.add_typer(env_app, name="env")

EXIT_ERROR = 1

ConfigOption = Annotated[
    Path, typer.Option("--config", "-c", help="Path to the project configuration file.")
]


@app.callback()
def main() -> None:
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
            cases_per_step = Counter(source_step_key(step) for step in compiled.unresolved)
            shown: set[tuple[int | None, str]] = set()
            for step in compiled.unresolved:
                key = source_step_key(step)
                if key in shown:  # outline cases repeat the same source step
                    continue
                shown.add(key)
                repeated = (
                    f" (in {cases_per_step[key]} test cases)" if cases_per_step[key] > 1 else ""
                )
                typer.echo(
                    f"  line {step.line}: {step.kind.value} {step.text!r}: {step.reason}{repeated}"
                )

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


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


@contextmanager
def _cli_errors() -> Iterator[None]:
    """Turn expected domain errors into a message and exit code 1."""
    try:
        yield
    except (ConfigError, ConfigEditError, InitError, StorageError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
