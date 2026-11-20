"""Scenario sources: where raw scenario documents come from (TASK-017, TASK-018).

A source only finds and reads documents; it never parses them. Parsers select
by ``ScenarioDocument.format``, so a new source (another format, a remote
system) needs no parser changes, and a new format needs no source changes.
"""

import os
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Protocol

from qa_schemas.base import SchemaModel
from qa_schemas.enums import ScenarioFormat
from qa_schemas.project import Project
from qa_schemas.scenario import ScenarioDocument, content_hash

MAX_DOCUMENT_BYTES = 1_000_000
"""Larger files are reported instead of read; scenarios are never this big."""

FORMAT_BY_SUFFIX: dict[str, ScenarioFormat] = {".feature": ScenarioFormat.GHERKIN}
"""Supported file extensions (compared case-insensitively). Others are ignored."""


class DiscoveryProblem(SchemaModel):
    """A location that should contain scenarios but could not be used."""

    path: PurePosixPath
    message: str


class DiscoveryResult(SchemaModel):
    documents: tuple[ScenarioDocument, ...] = ()
    """Sorted by path."""
    problems: tuple[DiscoveryProblem, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems


class ScenarioSource(Protocol):
    """Anything that can deliver scenario documents."""

    def discover(self) -> DiscoveryResult: ...


class LocalFileSource:
    """Scenario files under one or more directories of a project.

    - searches recursively, in a deterministic (sorted) order;
    - ignores files with unsupported extensions, and hidden files/directories;
    - does not follow directory symlinks; file symlinks must stay inside the project;
    - reports unreadable, oversized or non-UTF-8 files as problems.
    """

    def __init__(self, root: Path, directories: Sequence[Path]) -> None:
        self._root = root.resolve()
        self._directories = list(directories)

    @classmethod
    def for_project(cls, project: Project, root: Path) -> "LocalFileSource":
        """Source for the project's configured ``scenario_dir``; ``root`` holds ``qa.yaml``."""
        return cls(root, [project.scenario_dir])

    def discover(self) -> DiscoveryResult:
        documents: dict[PurePosixPath, ScenarioDocument] = {}
        problems: list[DiscoveryProblem] = []
        for directory in self._directories:
            for path, format_ in self._files_in(directory, problems):
                relative = self._relative(path)
                if relative in documents:  # overlapping directories
                    continue
                document = self._read(path, relative, format_, problems)
                if document is not None:
                    documents[relative] = document
        return DiscoveryResult(
            documents=tuple(documents[key] for key in sorted(documents)),
            problems=tuple(problems),
        )

    # --- Internals -----------------------------------------------------------

    def _relative(self, path: Path) -> PurePosixPath:
        return PurePosixPath(path.relative_to(self._root).as_posix())

    def _files_in(
        self, directory: Path, problems: list[DiscoveryProblem]
    ) -> list[tuple[Path, ScenarioFormat]]:
        start = (self._root / directory).resolve()
        label = PurePosixPath(directory.as_posix())
        if not start.is_relative_to(self._root):
            problems.append(
                DiscoveryProblem(path=label, message="directory is outside the project")
            )
            return []
        if not start.is_dir():
            message = "is not a directory" if start.exists() else "directory does not exist"
            problems.append(DiscoveryProblem(path=label, message=message))
            return []

        found: list[tuple[Path, ScenarioFormat]] = []
        for current, dirnames, filenames in os.walk(start, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                format_ = FORMAT_BY_SUFFIX.get(Path(name).suffix.lower())
                if format_ is not None and not name.startswith("."):
                    found.append((Path(current) / name, format_))
        return found

    def _read(
        self,
        path: Path,
        relative: PurePosixPath,
        format_: ScenarioFormat,
        problems: list[DiscoveryProblem],
    ) -> ScenarioDocument | None:
        def problem(message: str) -> None:
            problems.append(DiscoveryProblem(path=relative, message=message))

        if path.is_symlink():
            target = path.resolve()
            if not target.exists():
                problem("broken symbolic link")
                return None
            if not target.is_relative_to(self._root):
                problem("symbolic link points outside the project")
                return None
        try:
            size = path.stat().st_size
            if size > MAX_DOCUMENT_BYTES:
                problem(f"file is too large ({size} bytes, limit {MAX_DOCUMENT_BYTES})")
                return None
            data = path.read_bytes()
        except OSError as exc:
            problem(f"cannot read file: {exc.strerror}")
            return None
        try:
            text = data.decode("utf-8-sig")  # tolerate a UTF-8 byte order mark
        except UnicodeDecodeError as exc:
            problem(f"file is not valid UTF-8 (byte {exc.start})")
            return None

        return ScenarioDocument(
            path=relative, format=format_, content=text, content_hash=content_hash(data)
        )
