"""Entry point of the ``qa`` command."""

from pathlib import Path
from typing import Annotated

import typer

from qa_core.config import CONFIG_FILENAME, ConfigError
from qa_core.init import InitError, initialize_project

app = typer.Typer(
    name="qa",
    help="Local-first, deterministic QA automation platform.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

EXIT_ERROR = 1


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
    try:
        result = initialize_project(directory, project_id=project_id, name=name)
    except (ConfigError, InitError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(EXIT_ERROR) from None

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
