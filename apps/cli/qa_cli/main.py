"""Entry point of the ``qa`` command."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from qa_core.config import CONFIG_FILENAME, ConfigError
from qa_core.config_edit import ConfigEditError, add_environment, add_repository
from qa_core.init import InitError, initialize_project
from qa_core.storage import StorageError

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
app.add_typer(project_app, name="project")
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


@contextmanager
def _cli_errors() -> Iterator[None]:
    """Turn expected domain errors into a message and exit code 1."""
    try:
        yield
    except (ConfigError, ConfigEditError, InitError, StorageError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from None
