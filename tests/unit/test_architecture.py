"""The package dependency rules of docs/architecture.md, enforced on imports."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = {
    "qa_schemas": ROOT / "packages" / "qa_schemas",
    "qa_core": ROOT / "packages" / "qa_core",
    "qa_reporting": ROOT / "packages" / "qa_reporting",
    "qa_execution": ROOT / "packages" / "qa_execution",
    "qa_cli": ROOT / "apps" / "cli" / "qa_cli",
}
ALLOWED = {
    "qa_schemas": set(),
    "qa_core": {"qa_schemas"},
    "qa_reporting": {"qa_schemas"},
    "qa_execution": {"qa_schemas", "qa_core", "qa_reporting"},
    "qa_cli": {"qa_schemas", "qa_core", "qa_execution", "qa_reporting"},
}


def _imported_platform_packages(source: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source.read_text(), filename=str(source))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        found.update(name.split(".")[0] for name in names if name.split(".")[0] in PACKAGES)
    return found


@pytest.mark.parametrize("package", sorted(PACKAGES))
def test_package_imports_only_what_it_may_depend_on(package: str) -> None:
    violations = {
        str(source.relative_to(ROOT)): sorted(forbidden)
        for source in sorted(PACKAGES[package].rglob("*.py"))
        if (forbidden := _imported_platform_packages(source) - ALLOWED[package] - {package})
    }
    assert violations == {}


def test_every_package_is_checked() -> None:
    assert sorted(path.name for path in PACKAGES.values()) == sorted(PACKAGES)
    assert all(path.is_dir() for path in PACKAGES.values())
