"""Scenario discovery from the local filesystem (TASK-017, TASK-018)."""

import hashlib
from pathlib import Path, PurePosixPath

import pytest

from qa_core.config import load_config
from qa_core.scenarios.sources import (
    MAX_DOCUMENT_BYTES,
    DiscoveryResult,
    LocalFileSource,
    ScenarioSource,
)
from qa_schemas.enums import ScenarioFormat

ROOT = Path(__file__).parents[2]
FEATURE = "Feature: Login\n  Scenario: ok\n    Given x\n"


def _write(root: Path, relative: str, content: str | bytes = FEATURE) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _discover(root: Path, *directories: str) -> DiscoveryResult:
    return LocalFileSource(root, [Path(d) for d in directories or ("scenarios",)]).discover()


def _paths(result: DiscoveryResult) -> list[str]:
    return [str(d.path) for d in result.documents]


def _problems(result: DiscoveryResult) -> dict[str, str]:
    return {str(p.path): p.message for p in result.problems}


# --- Interface ---------------------------------------------------------------


def test_local_file_source_satisfies_the_interface(tmp_path: Path) -> None:
    source: ScenarioSource = LocalFileSource(tmp_path, [Path(".")])
    assert isinstance(source.discover(), DiscoveryResult)


def test_example_project_scenarios_are_discovered() -> None:
    root = ROOT / "examples"
    config = load_config(root / "qa.yaml")

    result = LocalFileSource.for_project(config.project, root).discover()

    assert result.ok
    [document] = result.documents
    assert document.path == PurePosixPath("scenarios/login.feature")
    assert document.format is ScenarioFormat.GHERKIN
    assert document.content.startswith("@smoke\nFeature: Login")


# --- Discovery ---------------------------------------------------------------


def test_nested_directories_are_searched_in_sorted_order(tmp_path: Path) -> None:
    for name in ["scenarios/z.feature", "scenarios/b/a.feature", "scenarios/a.feature",
                 "scenarios/b/c/deep.feature"]:  # fmt: skip
        _write(tmp_path, name)

    result = _discover(tmp_path)

    assert result.ok
    assert _paths(result) == [
        "scenarios/a.feature",
        "scenarios/b/a.feature",
        "scenarios/b/c/deep.feature",
        "scenarios/z.feature",
    ]


def test_unsupported_and_hidden_files_are_ignored(tmp_path: Path) -> None:
    _write(tmp_path, "scenarios/login.feature")
    _write(tmp_path, "scenarios/LOUD.FEATURE")
    for ignored in ["README.md", "notes.txt", "login.feature.bak", ".hidden.feature",
                    ".git/x.feature", "drafts/.cache/y.feature"]:  # fmt: skip
        _write(tmp_path, f"scenarios/{ignored}")

    result = _discover(tmp_path)

    assert result.ok
    assert _paths(result) == ["scenarios/LOUD.FEATURE", "scenarios/login.feature"]


def test_several_and_overlapping_directories(tmp_path: Path) -> None:
    _write(tmp_path, "scenarios/a.feature")
    _write(tmp_path, "scenarios/sub/b.feature")
    _write(tmp_path, "more/c.feature")

    result = _discover(tmp_path, "scenarios", "scenarios/sub", "more")

    assert _paths(result) == ["more/c.feature", "scenarios/a.feature", "scenarios/sub/b.feature"]


def test_empty_directory_gives_no_documents_and_no_problems(tmp_path: Path) -> None:
    (tmp_path / "scenarios").mkdir()
    result = _discover(tmp_path)
    assert result.documents == ()
    assert result.ok


def test_discovery_is_deterministic(tmp_path: Path) -> None:
    for i in range(20):
        _write(tmp_path, f"scenarios/d{i % 3}/f{i}.feature", f"Feature: F{i}\n")
    assert _discover(tmp_path) == _discover(tmp_path)


# --- Content -----------------------------------------------------------------


def test_content_and_hash_are_read(tmp_path: Path) -> None:
    raw = "Feature: Zażółć\n".encode()
    _write(tmp_path, "scenarios/pl.feature", raw)

    [document] = _discover(tmp_path).documents

    assert document.content == "Feature: Zażółć\n"
    assert document.content_hash == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_byte_order_mark_is_removed_but_hashed(tmp_path: Path) -> None:
    raw = b"\xef\xbb\xbf" + FEATURE.encode()
    _write(tmp_path, "scenarios/bom.feature", raw)

    [document] = _discover(tmp_path).documents

    assert document.content == FEATURE
    assert document.content_hash == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_hash_changes_when_content_changes(tmp_path: Path) -> None:
    path = _write(tmp_path, "scenarios/a.feature")
    first = _discover(tmp_path).documents[0].content_hash
    path.write_text(FEATURE + "    Then y\n")
    assert _discover(tmp_path).documents[0].content_hash != first


# --- Problems ----------------------------------------------------------------


def test_missing_directory_is_a_problem(tmp_path: Path) -> None:
    assert _problems(_discover(tmp_path)) == {"scenarios": "directory does not exist"}


def test_file_instead_of_directory_is_a_problem(tmp_path: Path) -> None:
    _write(tmp_path, "scenarios", "not a dir")
    assert _problems(_discover(tmp_path)) == {"scenarios": "is not a directory"}


@pytest.mark.parametrize("directory", ["..", "../elsewhere", "/etc"])
def test_directory_outside_project_is_a_problem(tmp_path: Path, directory: str) -> None:
    root = tmp_path / "project"
    root.mkdir()
    assert _problems(_discover(root, directory)) == {directory: "directory is outside the project"}


def test_bad_files_are_reported_and_good_ones_still_read(tmp_path: Path) -> None:
    _write(tmp_path, "scenarios/good.feature")
    _write(tmp_path, "scenarios/latin1.feature", "Feature: Café\n".encode("latin-1"))
    _write(tmp_path, "scenarios/huge.feature", "#" * (MAX_DOCUMENT_BYTES + 1))

    result = _discover(tmp_path)

    assert _paths(result) == ["scenarios/good.feature"]
    problems = _problems(result)
    assert problems["scenarios/latin1.feature"].startswith("file is not valid UTF-8")
    assert problems["scenarios/huge.feature"].startswith("file is too large")


def test_unreadable_file_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "scenarios/good.feature")
    locked = _write(tmp_path, "scenarios/locked.feature")
    original = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self == locked:
            raise PermissionError(13, "Permission denied")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    result = _discover(tmp_path)

    assert _paths(result) == ["scenarios/good.feature"]
    assert _problems(result) == {"scenarios/locked.feature": "cannot read file: Permission denied"}


def test_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    _write(outside, "external.feature")
    _write(outside, "dir/inner.feature")
    target = _write(root, "shared/shared.feature")
    scenarios = root / "scenarios"
    scenarios.mkdir()
    (scenarios / "inside.feature").symlink_to(target)
    (scenarios / "escape.feature").symlink_to(outside / "external.feature")
    (scenarios / "broken.feature").symlink_to(root / "missing.feature")
    (scenarios / "linked-dir").symlink_to(outside / "dir", target_is_directory=True)

    result = _discover(root)

    assert _paths(result) == ["scenarios/inside.feature"]
    assert _problems(result) == {
        "scenarios/broken.feature": "broken symbolic link",
        "scenarios/escape.feature": "symbolic link points outside the project",
    }
