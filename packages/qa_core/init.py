"""Project initialization: the logic behind ``qa init`` (TASK-013).

Initialization is idempotent: it only creates what is missing and never
overwrites or deletes existing files.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from qa_core.config import CONFIG_FILENAME, ConfigError, load_config, parse_config
from qa_core.storage import DATABASE_FILENAME, ProjectRepository, open_database
from qa_schemas.config import ProjectConfig

PLATFORM_DIRNAME = ".qa"
"""Local platform data (database, evidence, reports). Never committed."""

_MAX_ID_LENGTH = 64


class InitError(Exception):
    """The project cannot be initialized in the requested location."""


@dataclass(frozen=True)
class InitResult:
    root: Path
    config: ProjectConfig
    created: list[Path] = field(default_factory=list)
    """Paths created by this run, relative to ``root``."""
    existing: list[Path] = field(default_factory=list)
    """Paths that already existed and were left untouched, relative to ``root``."""


def derive_project_id(name: str) -> str:
    """Turn a directory or display name into a valid project identifier."""
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower())
    slug = re.sub(r"^[^a-z]+", "", slug)[:_MAX_ID_LENGTH].strip("-_")
    return slug or "project"


def render_config(project_id: str, name: str) -> str:
    """Default ``qa.yaml`` content, with comments to guide the first edit."""
    return f"""\
# QA platform project configuration. Reference: docs/configuration.md
# Never put credentials in this file.
version: 1

project:
  id: {project_id}
  name: {json.dumps(name, ensure_ascii=False)}
  scenario_dir: scenarios
  default_environment: local

  # Source repositories of the application under test (read-only for the platform).
  repositories: []
  #  - name: web
  #    path: ../my-app

  environments:
    - name: local
      # base_url: http://localhost:3000
      # services:
      #   api: http://localhost:8000
"""


def initialize_project(
    root: Path, *, project_id: str | None = None, name: str | None = None
) -> InitResult:
    """Initialize a project in ``root``, creating only what is missing.

    Raises:
        ConfigError: an existing ``qa.yaml`` is invalid.
        InitError: the given id/name are invalid, or ``root`` cannot be used.
        StorageError: the local database cannot be created or migrated.
    """
    root = root.resolve()
    if root.exists() and not root.is_dir():
        raise InitError(f"{root} exists and is not a directory")

    config_path = root / CONFIG_FILENAME
    new_config_text: str | None = None
    if config_path.exists():
        # Existing configuration is the source of truth; --id/--name do not override it.
        config = load_config(config_path)
    else:
        display_name = name or root.name or "Project"
        new_config_text = render_config(project_id or derive_project_id(display_name), display_name)
        try:
            config = parse_config(new_config_text, config_path)
        except ConfigError as error:
            raise InitError("invalid project id or name: " + "; ".join(error.issues)) from None

    scenario_dir = (root / config.project.scenario_dir).resolve()
    if not scenario_dir.is_relative_to(root):
        raise InitError(f"scenario_dir {config.project.scenario_dir} is outside the project")

    # Everything is validated; only now touch the filesystem.
    result = InitResult(root=root, config=config)
    _ensure_dir(root, root, result)
    if new_config_text is None:
        result.existing.append(config_path.relative_to(root))
    else:
        _write_new(config_path, new_config_text, root, result)
    _ensure_dir(scenario_dir, root, result)
    platform_dir = root / PLATFORM_DIRNAME
    _ensure_dir(platform_dir, root, result)
    _write_new(platform_dir / ".gitignore", "# Local QA platform data\n*\n", root, result)
    _init_database(platform_dir / DATABASE_FILENAME, config, root, result)
    return result


def _init_database(path: Path, config: ProjectConfig, root: Path, result: InitResult) -> None:
    """Create or migrate the local database and register the project in it."""
    existed = path.exists()
    with open_database(path) as connection:
        ProjectRepository(connection).upsert(config.project)
    (result.existing if existed else result.created).append(path.relative_to(root))


def _ensure_dir(path: Path, root: Path, result: InitResult) -> None:
    relative = path.relative_to(root)
    if path.is_dir():
        if path != root:
            result.existing.append(relative)
        return
    try:
        path.mkdir(parents=True)
    except OSError as exc:
        raise InitError(f"cannot create directory {path}: {exc.strerror}") from None
    if path != root:
        result.created.append(relative)


def _write_new(path: Path, content: str, root: Path, result: InitResult) -> None:
    try:
        with path.open("x", encoding="utf-8") as file:  # "x": never overwrite
            file.write(content)
    except FileExistsError:
        result.existing.append(path.relative_to(root))
        return
    except OSError as exc:
        raise InitError(f"cannot write {path}: {exc.strerror}") from None
    result.created.append(path.relative_to(root))
