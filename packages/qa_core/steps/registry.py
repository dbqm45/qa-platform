"""Step Registry: maps step text to registered step implementations (TASK-025).

A step definition has a stable id (the *normalized action*), a pattern, a kind
and the adapter capability it needs::

    registry = StepRegistry()

    @registry.step(
        "auth.sign-in",
        "the user signs in as {string} with password {string}",
        kind=StepKind.ACTION,
        capability="browser",
    )
    def sign_in(context, username: str, password: str) -> None: ...

Patterns are Cucumber Expressions (``{string}``, ``{int}``, ``{float}``,
``{word}``, ``{}``) or anchored regular expressions. Parameter names come from
the implementation's signature; the first argument is the execution context.
Everything is checked at registration time, so mistakes fail early.
"""

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cucumber_expressions.errors import CucumberExpressionError
from cucumber_expressions.expression import CucumberExpression
from cucumber_expressions.parameter_type_registry import ParameterTypeRegistry
from cucumber_expressions.regular_expression import RegularExpression

from qa_schemas.base import IDENTIFIER_PATTERN, STABLE_ID_PATTERN
from qa_schemas.enums import StepKind
from qa_schemas.specification import StepParameter

StepHandler = Callable[..., Any]

ALLOWED_PARAMETER_TYPES = frozenset({"int", "float", "word", "string", ""})
"""Cucumber parameter types whose values are plain JSON (no Decimal/bytes)."""

_STABLE_ID = re.compile(STABLE_ID_PATTERN)
_IDENTIFIER = re.compile(IDENTIFIER_PATTERN)


class StepRegistrationError(Exception):
    """A step definition is invalid or conflicts with an existing one."""


def kinds_compatible(definition: StepKind, step: StepKind) -> bool:
    """Expectations only match expectations; preconditions and actions are interchangeable.

    This keeps an action from silently standing in for an assertion.
    """
    return (definition is StepKind.EXPECTATION) == (step is StepKind.EXPECTATION)


@dataclass(frozen=True)
class StepDefinition:
    id: str
    pattern: str
    """Source of the pattern, as registered."""
    kind: StepKind
    capability: str
    handler: StepHandler
    parameter_names: tuple[str, ...]
    _expression: CucumberExpression | RegularExpression

    def match(self, text: str) -> dict[str, StepParameter] | None:
        """Named parameter values if ``text`` matches the whole pattern, else None."""
        arguments = self._expression.match(text)
        if arguments is None:
            return None
        values = [argument.value for argument in arguments]
        return dict(zip(self.parameter_names, values, strict=True))


class StepRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, StepDefinition] = {}
        self._parameter_types = ParameterTypeRegistry()

    def __len__(self) -> int:
        return len(self._definitions)

    @property
    def definitions(self) -> tuple[StepDefinition, ...]:
        """In registration order."""
        return tuple(self._definitions.values())

    def get(self, step_id: str) -> StepDefinition | None:
        return self._definitions.get(step_id)

    def step(
        self,
        step_id: str,
        pattern: str | re.Pattern[str],
        *,
        kind: StepKind,
        capability: str,
    ) -> Callable[[StepHandler], StepHandler]:
        """Decorator form of :meth:`register`; returns the handler unchanged."""

        def decorator(handler: StepHandler) -> StepHandler:
            self.register(step_id, pattern, handler, kind=kind, capability=capability)
            return handler

        return decorator

    def register(
        self,
        step_id: str,
        pattern: str | re.Pattern[str],
        handler: StepHandler,
        *,
        kind: StepKind,
        capability: str,
    ) -> StepDefinition:
        if not _STABLE_ID.match(step_id):
            raise StepRegistrationError(f"invalid step id {step_id!r}")
        if not _IDENTIFIER.match(capability):
            raise StepRegistrationError(f"step {step_id!r}: invalid capability {capability!r}")
        if step_id in self._definitions:
            raise StepRegistrationError(f"step id {step_id!r} is already registered")

        expression, source, group_count = self._compile(step_id, pattern)
        for other in self._definitions.values():
            if other.pattern == source and kinds_compatible(other.kind, kind):
                raise StepRegistrationError(
                    f"step {step_id!r} has the same pattern as {other.id!r}: {source!r}"
                )

        definition = StepDefinition(
            id=step_id,
            pattern=source,
            kind=kind,
            capability=capability,
            handler=handler,
            parameter_names=_parameter_names(step_id, handler, group_count),
            _expression=expression,
        )
        self._definitions[step_id] = definition
        return definition

    def _compile(
        self, step_id: str, pattern: str | re.Pattern[str]
    ) -> tuple[CucumberExpression | RegularExpression, str, int]:
        if isinstance(pattern, re.Pattern):
            if not (pattern.pattern.startswith("^") and pattern.pattern.endswith("$")):
                raise StepRegistrationError(
                    f"step {step_id!r}: regular expressions must be anchored with ^...$"
                )
            regex = RegularExpression(pattern, self._parameter_types)
            return regex, pattern.pattern, pattern.groups

        try:
            expression = CucumberExpression(pattern, self._parameter_types)
        except CucumberExpressionError as exc:
            raise StepRegistrationError(f"step {step_id!r}: {exc}") from None
        types = [p.name for p in expression.parameter_types]
        if unsupported := sorted(set(types) - ALLOWED_PARAMETER_TYPES):
            raise StepRegistrationError(
                f"step {step_id!r}: unsupported parameter types {unsupported}; "
                f"use {{int}}, {{float}}, {{word}}, {{string}} or {{}}"
            )
        return expression, pattern, len(types)


def _parameter_names(step_id: str, handler: StepHandler, expected: int) -> tuple[str, ...]:
    """Names of the handler's parameters after ``context``; must match the pattern."""
    parameters = list(inspect.signature(handler).parameters.values())
    positional = [p for p in parameters if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if not positional:
        raise StepRegistrationError(
            f"step {step_id!r}: the handler must take the execution context as first argument"
        )
    names = tuple(p.name for p in positional[1:])
    if len(names) != expected:
        raise StepRegistrationError(
            f"step {step_id!r}: the pattern has {expected} parameter(s) but the handler "
            f"takes {len(names)} after the context ({', '.join(names) or 'none'})"
        )
    return names
