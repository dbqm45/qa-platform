"""TestAdapter contract and Adapter Registry (TASK-029, TASK-030)."""

from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from pydantic import ValidationError

from qa_execution.adapters import (
    AdapterNotPreparedError,
    ExecutionContext,
    TestAdapter,
)
from qa_execution.registry import (
    AdapterRegistrationError,
    AdapterRegistry,
    AdapterSelectionError,
    builtin_adapters,
)
from qa_schemas.evidence import EvidenceReference
from qa_schemas.plan import ExecutionSettings
from qa_schemas.project import Environment
from qa_schemas.specification import TestSpecification

ROOT = Path(__file__).parents[2]


class _Resourceful(TestAdapter):
    """Minimal adapter: a resource that exists only between prepare and cleanup."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._resource: object | None = None

    def prepare(self, context: ExecutionContext) -> None:
        self.calls.append(f"prepare:{context.execution_id}")
        self._resource = object()

    def cleanup(self) -> None:
        self.calls.append("cleanup")
        self._resource = None

    @property
    def resource(self) -> Any:
        if self._resource is None:
            raise AdapterNotPreparedError(f"{self.name} is not prepared")
        return self._resource


class Browser(_Resourceful):
    name = "browser-a"
    capabilities = frozenset({"browser"})


class OtherBrowser(_Resourceful):
    name = "browser-b"
    capabilities = frozenset({"browser", "screenshots"})


class Http(_Resourceful):
    name = "http"
    capabilities = frozenset({"http"})


def _context(tmp_path: Path) -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-1",
        environment=Environment(name="local"),
        settings=ExecutionSettings(),
        evidence_dir=tmp_path,
    )


def _spec() -> TestSpecification:
    return TestSpecification.model_validate_json(
        (ROOT / "examples/specifications/login.spec.json").read_text()
    )


# --- Contract ----------------------------------------------------------------


def test_adapter_must_implement_the_required_methods() -> None:
    class Incomplete(TestAdapter):
        name = "incomplete"
        capabilities = frozenset({"x"})

        def prepare(self, context: ExecutionContext) -> None: ...

    with pytest.raises(TypeError, match="abstract"):
        Incomplete()  # type: ignore[abstract]


def test_optional_hooks_have_safe_defaults(tmp_path: Path) -> None:
    adapter = Browser()
    spec = _spec()
    case = spec.test_cases[0]

    assert adapter.get_capabilities() == frozenset({"browser"})
    assert adapter.validate(spec) == []
    adapter.prepare(_context(tmp_path))
    adapter.start_test_case(case)
    adapter.finish_test_case(case, passed=True)
    assert adapter.collect_evidence(case) == []
    adapter.cleanup()
    assert adapter.calls == ["prepare:exec-1", "cleanup"]


def test_resource_is_only_available_while_prepared(tmp_path: Path) -> None:
    adapter = Browser()
    with pytest.raises(AdapterNotPreparedError):
        _ = adapter.resource
    adapter.prepare(_context(tmp_path))
    assert adapter.resource is not None
    adapter.cleanup()
    adapter.cleanup()  # safe to call twice
    with pytest.raises(AdapterNotPreparedError):
        _ = adapter.resource


def test_evidence_reference_paths_stay_in_the_evidence_directory() -> None:
    ref = EvidenceReference(kind="screenshot", path=PurePosixPath("case-1/failure.png"))
    assert ref.path.name == "failure.png"
    for bad in ["/tmp/x.png", "../x.png"]:
        with pytest.raises(ValidationError, match="relative to the evidence directory"):
            EvidenceReference(kind="screenshot", path=PurePosixPath(bad))


# --- Registration ------------------------------------------------------------


def test_registration_and_discovery() -> None:
    registry = AdapterRegistry([Browser, Http])

    assert registry.adapters == (Browser, Http)
    assert registry.get("http") is Http
    assert registry.get("nope") is None
    assert registry.available_capabilities == frozenset({"browser", "http"})


def test_register_works_as_class_decorator() -> None:
    registry = AdapterRegistry()

    @registry.register
    class Decorated(_Resourceful):
        name = "decorated"
        capabilities = frozenset({"x"})

    assert registry.get("decorated") is Decorated


def test_duplicate_name_is_rejected() -> None:
    class SameName(_Resourceful):
        name = "http"
        capabilities = frozenset({"other"})

    registry = AdapterRegistry([Http])
    with pytest.raises(AdapterRegistrationError, match="'http' is already registered"):
        registry.register(SameName)


@pytest.mark.parametrize(
    ("name", "capabilities", "message"),
    [
        ("Bad Name", frozenset({"x"}), "invalid adapter name"),
        ("ok", frozenset(), "non-empty frozenset"),
        ("ok", {"x"}, "non-empty frozenset"),
        ("ok", frozenset({"Not Valid"}), "invalid capabilities"),
    ],
)
def test_invalid_declarations_are_rejected(name: str, capabilities: Any, message: str) -> None:
    adapter = type("Adapter", (_Resourceful,), {"name": name, "capabilities": capabilities})
    with pytest.raises(AdapterRegistrationError, match=message):
        AdapterRegistry().register(adapter)


def test_missing_declarations_are_rejected() -> None:
    class Undeclared(_Resourceful):
        pass

    with pytest.raises(AdapterRegistrationError, match="invalid adapter name None"):
        AdapterRegistry().register(Undeclared)


def test_registry_holds_classes_so_executions_get_fresh_instances() -> None:
    registry = AdapterRegistry([Browser])
    adapter_class = registry.select({"browser"}).adapters[0]
    assert adapter_class() is not adapter_class()


def test_builtin_registry_is_empty_until_adapters_are_added() -> None:
    assert builtin_adapters().adapters == ()


# --- Selection by capability -------------------------------------------------


def test_select_by_capability() -> None:
    selection = AdapterRegistry([Browser, Http]).select({"http", "browser"})

    assert selection.names == ("browser-a", "http")
    assert selection.provider_of == {"browser": Browser, "http": Http}


def test_select_nothing_required() -> None:
    assert AdapterRegistry([Browser]).select(set()).adapters == ()


def test_one_adapter_can_provide_several_capabilities() -> None:
    selection = AdapterRegistry([OtherBrowser, Http]).select({"browser", "screenshots"})
    assert selection.names == ("browser-b",)


def test_missing_capability_is_an_explicit_error() -> None:
    with pytest.raises(
        AdapterSelectionError, match="not provided by any registered adapter: database, queue"
    ):
        AdapterRegistry([Browser]).select({"browser", "queue", "database"})


def test_several_providers_are_ambiguous() -> None:
    registry = AdapterRegistry([Browser, OtherBrowser])
    with pytest.raises(
        AdapterSelectionError, match=r"several adapters.*browser \(browser-a, browser-b\)"
    ):
        registry.select({"browser"})


def test_plan_adapters_settle_ambiguity() -> None:
    registry = AdapterRegistry([Browser, OtherBrowser, Http])

    selection = registry.select({"browser", "http"}, allowed=["browser-b", "http"])

    assert selection.names == ("browser-b", "http")


def test_allowed_adapters_must_cover_all_capabilities() -> None:
    registry = AdapterRegistry([Browser, Http])
    with pytest.raises(AdapterSelectionError, match="not provided by the allowed adapters: http"):
        registry.select({"browser", "http"}, allowed=["browser-a"])


def test_unknown_allowed_adapter_is_rejected() -> None:
    with pytest.raises(AdapterSelectionError, match="unknown adapters: selenium"):
        AdapterRegistry([Browser]).select({"browser"}, allowed=["browser-a", "selenium"])


def test_selection_is_deterministic() -> None:
    registry = AdapterRegistry([Http, Browser])
    first = registry.select(["browser", "http"])
    assert first == registry.select(["http", "browser"])
    assert first.names == ("http", "browser-a")  # registration order
