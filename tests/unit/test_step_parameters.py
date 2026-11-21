"""Step parameter validation (TASK-032)."""

from enum import StrEnum
from typing import Annotated, Any, Literal

import pytest
from pydantic import AfterValidator, Field

from qa_core.steps.registry import (
    StepArguments,
    StepParameterError,
    StepRegistrationError,
    StepRegistry,
)
from qa_core.steps.resolution import resolve_step
from qa_schemas.enums import StepKind

A, E = StepKind.ACTION, StepKind.EXPECTATION


class Method(StrEnum):
    GET = "GET"
    POST = "POST"


def status_is(context: Any, code: Annotated[int, Field(ge=100, le=599)]) -> None: ...


def send(context: Any, method: Method, path: str) -> None: ...


def wait(context: Any, seconds: float) -> None: ...


def choose(context: Any, size: Literal["small", "large"]) -> None: ...


def fill_form(context: Any, *, data_table: tuple[tuple[str, ...], ...]) -> None: ...


def post_body(context: Any, path: str, *, doc_string: str) -> None: ...


@pytest.fixture
def registry() -> StepRegistry:
    registry = StepRegistry()
    registry.register("api.status", "the status is {int}", status_is, kind=E, capability="http")
    registry.register(
        "api.send", "the client sends {word} {string}", send, kind=A, capability="http"
    )
    registry.register("time.wait", "wait {float} seconds", wait, kind=A, capability="clock")
    registry.register("ui.size", "the user picks {word}", choose, kind=A, capability="browser")
    registry.register(
        "ui.fill", "the user fills the form:", fill_form, kind=A, capability="browser"
    )
    registry.register(
        "api.post", "the client posts to {string}:", post_body, kind=A, capability="http"
    )
    return registry


def _definition(registry: StepRegistry, step_id: str) -> Any:
    definition = registry.get(step_id)
    assert definition is not None
    return definition


# --- Valid parameters --------------------------------------------------------


def test_valid_parameters_are_bound_with_their_types(registry: StepRegistry) -> None:
    send_def = _definition(registry, "api.send")
    bound = send_def.bind({"method": "POST", "path": "/orders"})
    assert bound == {"method": Method.POST, "path": "/orders"}
    assert isinstance(bound["method"], Method)


def test_int_is_accepted_for_float(registry: StepRegistry) -> None:
    assert _definition(registry, "time.wait").bind({"seconds": 2}) == {"seconds": 2.0}


def test_step_arguments_are_passed_by_name(registry: StepRegistry) -> None:
    table = (("field", "value"), ("email", "a@b.c"))
    assert _definition(registry, "ui.fill").bind({}, StepArguments(data_table=table)) == {
        "data_table": table
    }
    bound = _definition(registry, "api.post").bind(
        {"path": "/x"}, StepArguments(doc_string='{"a": 1}')
    )
    assert bound == {"path": "/x", "doc_string": '{"a": 1}'}


def test_definitions_record_accepted_arguments(registry: StepRegistry) -> None:
    fill = _definition(registry, "ui.fill")
    assert (fill.accepts_data_table, fill.accepts_doc_string) == (True, False)
    assert fill.parameter_names == ()


# --- Invalid parameters ------------------------------------------------------


@pytest.mark.parametrize(
    ("step_id", "parameters", "message"),
    [
        (
            "api.status",
            {"code": 999},
            r"invalid value 999 for parameter 'code': .*less than or equal to 599",
        ),
        ("api.status", {"code": 42}, r"greater than or equal to 100"),
        (
            "api.send",
            {"method": "FETCH", "path": "/"},
            r"parameter 'method': Input should be 'GET' or 'POST'",
        ),
        ("ui.size", {"size": "huge"}, r"parameter 'size': Input should be 'small' or 'large'"),
        ("time.wait", {"seconds": "soon"}, r"parameter 'seconds'"),
        ("api.status", {}, r"expected parameters \(code\), got \(none\)"),
        (
            "api.status",
            {"code": 200, "extra": 1},
            r"expected parameters \(code\), got \(code, extra\)",
        ),
    ],
)
def test_invalid_parameters_are_rejected(
    registry: StepRegistry, step_id: str, parameters: dict[str, Any], message: str
) -> None:
    with pytest.raises(StepParameterError, match=message):
        _definition(registry, step_id).bind(parameters)


def test_missing_data_table_is_rejected(registry: StepRegistry) -> None:
    with pytest.raises(StepParameterError, match=r"'ui\.fill' requires a data table"):
        _definition(registry, "ui.fill").bind({})


def test_unexpected_doc_string_is_rejected(registry: StepRegistry) -> None:
    with pytest.raises(
        StepParameterError, match=r"has a doc string, but 'api\.status' does not accept"
    ):
        _definition(registry, "api.status").bind({"code": 200}, StepArguments(doc_string="x"))


def test_invalid_data_table_shape_is_rejected(registry: StepRegistry) -> None:
    with pytest.raises(StepParameterError, match="does not accept one"):
        _definition(registry, "api.status").bind({"code": 200}, StepArguments(data_table=(("a",),)))


# --- Rejected before execution: resolution reports them ----------------------


def test_invalid_value_makes_the_step_unresolved(registry: StepRegistry) -> None:
    result = resolve_step(registry, "the status is 999", E)

    assert result.definition is None
    assert result.problem is not None
    assert result.problem.startswith("api.status: invalid value 999 for parameter 'code'")


def test_valid_value_resolves(registry: StepRegistry) -> None:
    result = resolve_step(registry, "the status is 201", E)
    assert result.definition is not None
    assert result.parameters == {"code": 201}


def test_missing_table_makes_the_step_unresolved(registry: StepRegistry) -> None:
    result = resolve_step(registry, "the user fills the form:", A)
    assert result.problem == "ui.fill: step 'ui.fill' requires a data table"

    table = StepArguments(data_table=(("a", "b"),))
    assert resolve_step(registry, "the user fills the form:", A, table).definition is not None


# --- Registration-time checks ------------------------------------------------


def test_parameters_need_type_annotations() -> None:
    def untyped(context, value):  # type: ignore[no-untyped-def]
        ...

    with pytest.raises(StepRegistrationError, match="parameter 'value' has no type annotation"):
        StepRegistry().register("x.y", "v {int}", untyped, kind=A, capability="c")


def test_context_needs_no_annotation() -> None:
    def handler(context, value: int) -> None:  # type: ignore[no-untyped-def]
        ...

    StepRegistry().register("x.y", "v {int}", handler, kind=A, capability="c")


def test_unknown_keyword_only_parameter_is_rejected() -> None:
    def handler(context: Any, *, table: str) -> None: ...

    with pytest.raises(StepRegistrationError, match=r"unknown keyword-only parameters \['table'\]"):
        StepRegistry().register("x.y", "v", handler, kind=A, capability="c")


def test_unsupported_annotation_is_rejected() -> None:
    class Opaque:
        pass

    def handler(context: Any, value: Opaque) -> None: ...

    with pytest.raises(StepRegistrationError, match="unsupported annotation for 'value'"):
        StepRegistry().register("x.y", "v {}", handler, kind=A, capability="c")


def test_any_disables_validation() -> None:
    def handler(context: Any, value: Any) -> None: ...

    definition = StepRegistry().register("x.y", "v {}", handler, kind=A, capability="c")
    assert definition.bind({"value": "anything"}) == {"value": "anything"}


def test_step_arguments_are_validated_by_their_annotations() -> None:
    """Regression: data_table / doc_string were passed through without validation."""

    def only_json(value: str) -> str:
        if not value.startswith("{"):
            raise ValueError("must be a JSON object")
        return value

    def handler(context: Any, *, doc_string: Annotated[str, AfterValidator(only_json)]) -> None: ...

    definition = StepRegistry().register("x.body", "body:", handler, kind=A, capability="c")

    assert definition.bind({}, StepArguments(doc_string='{"a": 1}')) == {"doc_string": '{"a": 1}'}
    with pytest.raises(StepParameterError, match="invalid doc_string: must be a JSON object"):
        definition.bind({}, StepArguments(doc_string="[1]"))
