"""Tests for the central status, mode and category definitions."""

import importlib
import inspect
import itertools
import pkgutil
from enum import Enum
from types import ModuleType

import pytest

from qa_schemas import enums
from qa_schemas.enums import CompilationStatus, ExecutionMode, ExecutionStatus, TestCategory

PLATFORM_PACKAGES = ["qa_cli", "qa_core", "qa_schemas", "qa_execution", "qa_reporting"]
STATUS_VALUES = {s.value for s in itertools.chain(CompilationStatus, ExecutionStatus)}


# --- TASK-007: statuses ------------------------------------------------------


def test_statuses_cover_the_backlog_definition() -> None:
    expected = {
        "READY", "NEEDS_REVIEW", "BLOCKED", "UNSUPPORTED",
        "PENDING", "RUNNING", "PASSED", "FAILED", "ERROR", "CANCELLED",
    }  # fmt: skip
    names = {s.name for s in itertools.chain(CompilationStatus, ExecutionStatus)}
    assert names == expected


def test_compilation_and_execution_statuses_do_not_overlap() -> None:
    assert not {s.value for s in CompilationStatus} & {s.value for s in ExecutionStatus}


@pytest.mark.parametrize("status", list(CompilationStatus))
def test_only_ready_is_executable(status: CompilationStatus) -> None:
    assert status.is_executable is (status is CompilationStatus.READY)


@pytest.mark.parametrize(
    ("status", "terminal"),
    [
        (ExecutionStatus.PENDING, False),
        (ExecutionStatus.RUNNING, False),
        (ExecutionStatus.PASSED, True),
        (ExecutionStatus.FAILED, True),
        (ExecutionStatus.ERROR, True),
        (ExecutionStatus.CANCELLED, True),
    ],
)
def test_terminal_execution_statuses(status: ExecutionStatus, terminal: bool) -> None:
    assert status.is_terminal is terminal


def _platform_modules() -> list[ModuleType]:
    modules = []
    for name in PLATFORM_PACKAGES:
        package = importlib.import_module(name)
        modules.append(package)
        for info in pkgutil.walk_packages(package.__path__, prefix=f"{name}."):
            modules.append(importlib.import_module(info.name))
    return modules


def test_no_module_defines_its_own_status_values() -> None:
    offenders = []
    for module in _platform_modules():
        if module is enums:
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Enum) and obj.__module__ == module.__name__:
                clash = {str(m.value).lower() for m in obj} & STATUS_VALUES
                if clash:
                    offenders.append(f"{module.__name__}.{obj.__name__}: {sorted(clash)}")
    assert not offenders, f"Use qa_schemas.enums instead of redefining statuses: {offenders}"


# --- TASK-010: execution modes -----------------------------------------------


def test_execution_modes() -> None:
    assert [m.name for m in ExecutionMode] == ["FE", "BE", "FULL", "CONTRACT"]


@pytest.mark.parametrize("value", ["fe", "be", "full", "contract"])
def test_valid_mode_is_parsed(value: str) -> None:
    assert ExecutionMode(value).value == value


@pytest.mark.parametrize("value", ["e2e", "FULL", "", " full"])
def test_invalid_mode_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="is not a valid ExecutionMode"):
        ExecutionMode(value)


# --- TASK-011: test categories -----------------------------------------------


def test_test_categories() -> None:
    assert [c.name for c in TestCategory] == [
        "FUNCTIONAL", "VISUAL", "ACCESSIBILITY", "PERFORMANCE", "SECURITY", "CONTRACT",
    ]  # fmt: skip


def test_invalid_category_is_rejected() -> None:
    with pytest.raises(ValueError, match="is not a valid TestCategory"):
        TestCategory("smoke")


def test_category_is_independent_of_mode() -> None:
    """Every mode/category pair is representable, e.g. FULL+FUNCTIONAL, BE+FUNCTIONAL."""
    pairs = set(itertools.product(ExecutionMode, TestCategory))
    assert len(pairs) == len(ExecutionMode) * len(TestCategory)
    assert (ExecutionMode.FULL, TestCategory.FUNCTIONAL) in pairs
    assert (ExecutionMode.BE, TestCategory.FUNCTIONAL) in pairs


# --- Serialization -----------------------------------------------------------


@pytest.mark.parametrize("enum_cls", [CompilationStatus, ExecutionStatus, ExecutionMode])
def test_values_are_lowercase_names(enum_cls: type[Enum]) -> None:
    for member in enum_cls:
        assert member.value == member.name.lower()
