"""Step Registry and step resolution (TASK-024, TASK-025)."""

import re
from pathlib import Path
from typing import Any

import pytest

from qa_core.steps.registry import StepRegistrationError, StepRegistry
from qa_core.steps.resolution import resolve_specification, resolve_step
from qa_schemas.enums import StepKind
from qa_schemas.specification import TestSpecification

ROOT = Path(__file__).parents[2]
P, A, E = StepKind.PRECONDITION, StepKind.ACTION, StepKind.EXPECTATION


def _noop(context: Any, *args: Any) -> None:
    """Placeholder implementation; behaviour is irrelevant for resolution."""


@pytest.fixture
def registry() -> StepRegistry:
    registry = StepRegistry()

    @registry.step("browser.open-login", "the login page is open", kind=A, capability="browser")
    def open_login(context: Any) -> None: ...

    @registry.step(
        "auth.sign-in",
        "the user signs in as {string} with password {string}",
        kind=A,
        capability="browser",
    )
    def sign_in(context: Any, username: str, password: str) -> None: ...

    @registry.step("ui.dashboard-visible", "the dashboard is shown", kind=E, capability="browser")
    def dashboard(context: Any) -> None: ...

    @registry.step(
        "ui.greeting-contains", "the greeting contains {string}", kind=E, capability="browser"
    )
    def greeting(context: Any, text: str) -> None: ...

    @registry.step("api.total", "the total is {int}", kind=E, capability="http")
    def total(context: Any, amount: int) -> None: ...

    @registry.step("ui.click", "the user clicks {string}", kind=A, capability="browser")
    def click(context: Any, label: str) -> None: ...

    return registry


# --- Registration ------------------------------------------------------------


def test_definitions_are_registered_in_order(registry: StepRegistry) -> None:
    assert len(registry) == 6
    assert registry.definitions[0].id == "browser.open-login"
    sign_in = registry.get("auth.sign-in")
    assert sign_in is not None
    assert sign_in.parameter_names == ("username", "password")
    assert (sign_in.kind, sign_in.capability) == (A, "browser")


def test_decorator_returns_the_handler_unchanged() -> None:
    registry = StepRegistry()

    def handler(context: Any) -> str:
        return "ran"

    assert registry.step("x.y", "x", kind=A, capability="c")(handler) is handler


def test_duplicate_id_is_rejected(registry: StepRegistry) -> None:
    with pytest.raises(StepRegistrationError, match=r"'auth\.sign-in' is already registered"):
        registry.register("auth.sign-in", "something else", _noop, kind=A, capability="browser")


def test_duplicate_pattern_is_rejected(registry: StepRegistry) -> None:
    with pytest.raises(StepRegistrationError, match=r"same pattern as 'ui\.dashboard-visible'"):
        registry.register("ui.other", "the dashboard is shown", _noop, kind=E, capability="b")


def test_same_pattern_as_action_and_expectation_is_allowed(registry: StepRegistry) -> None:
    """``Given the dashboard is shown`` (set up) vs ``Then ...`` (check) may differ."""
    registry.register("nav.dashboard", "the dashboard is shown", _noop, kind=P, capability="b")


def test_parameter_types_are_converted() -> None:
    registry = StepRegistry()

    def handler(
        context: Any, count: int, price: float, word: str, text: str, anything: str
    ) -> None: ...

    registry.register(
        "x.all", "{int} items at {float} {word} {string} and {}", handler, kind=A, capability="c"
    )
    definition = registry.definitions[0]

    assert definition.match('3 items at 1.5 EUR "nice deal" and more stuff') == {
        "count": 3,
        "price": 1.5,
        "word": "EUR",
        "text": "nice deal",
        "anything": "more stuff",
    }
    assert definition.match("three items at 1.5 EUR 'x' and y") is None


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("a {biginteger}", "unsupported parameter types \\['biginteger'\\]"),
        ("a {nope}", "Undefined parameter type 'nope'"),
        ("a {int", "has a problem"),
    ],
)
def test_invalid_expressions_are_rejected(pattern: str, message: str) -> None:
    def handler(context: Any, value: Any) -> None: ...

    with pytest.raises(StepRegistrationError, match=message):
        StepRegistry().register("x.y", pattern, handler, kind=A, capability="c")


def test_regular_expressions_must_be_anchored() -> None:
    def handler(context: Any, n: str) -> None: ...

    registry = StepRegistry()
    with pytest.raises(StepRegistrationError, match="anchored"):
        registry.register("x.y", re.compile(r"amount (\d+)"), handler, kind=A, capability="c")

    definition = registry.register(
        "x.z", re.compile(r"^amount (\d+)$"), handler, kind=A, capability="c"
    )
    assert definition.match("amount 42") == {"n": 42}  # \d+ is recognized as {int}
    assert definition.match("amount 42 euros") is None


def _no_args() -> None: ...


def _context_only(context: Any) -> None: ...


def _two_values(context: Any, a: Any, b: Any) -> None: ...


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (_no_args, "must take the execution context"),
        (_context_only, r"pattern has 1 parameter\(s\) but the handler takes 0"),
        (_two_values, r"takes 2 after the context \(a, b\)"),
    ],
)
def test_handler_signature_must_match_pattern(handler: Any, message: str) -> None:
    with pytest.raises(StepRegistrationError, match=message):
        StepRegistry().register("x.y", "value {int}", handler, kind=A, capability="c")


@pytest.mark.parametrize(
    ("step_id", "capability", "message"),
    [("Bad Id", "browser", "invalid step id"), ("x.y", "Browser!", "invalid capability")],
)
def test_ids_and_capabilities_are_validated(step_id: str, capability: str, message: str) -> None:
    with pytest.raises(StepRegistrationError, match=message):
        StepRegistry().register(step_id, "x", _noop, kind=A, capability=capability)


# --- Resolving single steps --------------------------------------------------


def test_matching_step_resolves_with_parameters(registry: StepRegistry) -> None:
    result = resolve_step(registry, 'the user signs in as "alice" with password "s3cret"', A)
    assert result.definition is not None
    assert result.definition.id == "auth.sign-in"
    assert result.parameters == {"username": "alice", "password": "s3cret"}
    assert result.problem is None


def test_preconditions_can_use_action_steps(registry: StepRegistry) -> None:
    result = resolve_step(registry, "the login page is open", P)
    assert result.definition is not None


def test_unknown_step_is_reported_not_guessed(registry: StepRegistry) -> None:
    result = resolve_step(registry, "the user signs in as alice", A)
    assert result.definition is None
    assert result.parameters == {}
    assert result.problem == "no step definition matches this text"


def test_action_cannot_stand_in_for_an_expectation(registry: StepRegistry) -> None:
    result = resolve_step(registry, 'the user clicks "Save"', E)
    assert result.definition is None
    assert result.problem == "matches ui.click (action), which cannot be used as a expectation step"


def test_expectation_cannot_be_used_as_an_action(registry: StepRegistry) -> None:
    result = resolve_step(registry, "the dashboard is shown", A)
    assert result.definition is None
    assert "ui.dashboard-visible (expectation)" in (result.problem or "")


def test_ambiguous_match_is_not_resolved(registry: StepRegistry) -> None:
    def handler(context: Any, value: str) -> None: ...

    registry.register(
        "ui.any-greeting", "the greeting contains {}", handler, kind=E, capability="b"
    )

    result = resolve_step(registry, 'the greeting contains "Alice"', E)

    assert result.definition is None
    assert (
        result.problem == "ambiguous: matches several steps (ui.any-greeting, ui.greeting-contains)"
    )


def test_resolution_is_deterministic(registry: StepRegistry) -> None:
    text = 'the greeting contains "Alice"'
    assert resolve_step(registry, text, E) == resolve_step(registry, text, E)


# --- Resolving specifications ------------------------------------------------


def _sample() -> TestSpecification:
    return TestSpecification.model_validate_json(
        (ROOT / "examples/specifications/login.spec.json").read_text()
    )


def test_sample_specification_resolves_fully(registry: StepRegistry) -> None:
    result = resolve_specification(_sample(), registry)

    assert result.fully_resolved
    steps = result.specification.test_cases[0].steps
    assert [s.action for s in steps] == [
        "browser.open-login", "auth.sign-in", "ui.dashboard-visible", "ui.greeting-contains",
    ]  # fmt: skip
    assert steps[1].parameters == {"username": "alice", "password": "correct-password"}
    assert steps[3].parameters == {"text": "Alice"}
    assert result.specification.required_capabilities == ("browser",)


def test_unresolved_steps_are_listed_and_left_without_action(registry: StepRegistry) -> None:
    spec = _sample()
    case = spec.test_cases[0]
    changed = list(case.steps)
    changed[2] = changed[2].model_copy(update={"text": "the user sees a party"})
    spec = spec.model_copy(
        update={"test_cases": (case.model_copy(update={"steps": tuple(changed)}),)}
    )

    result = resolve_specification(spec, registry)

    [unresolved] = result.unresolved
    assert (unresolved.test_case_id, unresolved.step_index, unresolved.line) == (
        "login.successful-login", 2, 9,
    )  # fmt: skip
    assert unresolved.kind is E
    assert unresolved.reason == "no step definition matches this text"
    resolved_steps = result.specification.test_cases[0].steps
    assert resolved_steps[2].action is None
    assert resolved_steps[3].action == "ui.greeting-contains"


def test_capabilities_are_collected_from_resolved_steps(registry: StepRegistry) -> None:
    spec = _sample()
    case = spec.test_cases[0]
    steps = (*case.steps, case.steps[-1].model_copy(update={"text": "the total is 90"}))
    spec = spec.model_copy(update={"test_cases": (case.model_copy(update={"steps": steps}),)})

    result = resolve_specification(spec, registry)

    assert result.specification.required_capabilities == ("browser", "http")
    assert result.specification.test_cases[0].steps[-1].parameters == {"amount": 90}


def test_empty_registry_resolves_nothing() -> None:
    result = resolve_specification(_sample(), StepRegistry())
    assert len(result.unresolved) == 4
    assert result.specification.required_capabilities == ()


def test_resolved_specification_survives_json_round_trip(registry: StepRegistry) -> None:
    resolved = resolve_specification(_sample(), registry).specification
    restored = TestSpecification.model_validate_json(resolved.model_dump_json())
    assert restored == resolved
    assert restored.test_cases[0].steps[1].parameters["username"] == "alice"
