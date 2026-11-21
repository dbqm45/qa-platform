"""Adapter Registry: which adapters exist and which ones an execution needs (TASK-030).

Adapter *classes* are registered; every execution creates fresh instances,
because adapters hold per-execution state (a browser, a client).
"""

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from qa_execution.adapters import TestAdapter
from qa_schemas.base import IDENTIFIER_PATTERN

_IDENTIFIER = re.compile(IDENTIFIER_PATTERN)


class AdapterRegistrationError(Exception):
    """An adapter class is invalid or conflicts with one already registered."""


class AdapterSelectionError(Exception):
    """The requested capabilities cannot be provided unambiguously."""


@dataclass(frozen=True)
class AdapterSelection:
    adapters: tuple[type[TestAdapter], ...]
    """Selected adapter classes, in registration order."""
    provider_of: dict[str, type[TestAdapter]]
    """Capability -> the adapter class that provides it."""

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(adapter.name for adapter in self.adapters)


class AdapterRegistry:
    def __init__(self, adapters: Iterable[type[TestAdapter]] = ()) -> None:
        self._adapters: dict[str, type[TestAdapter]] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: type[TestAdapter]) -> type[TestAdapter]:
        """Register an adapter class; usable as a class decorator."""
        name = getattr(adapter, "name", None)
        capabilities = getattr(adapter, "capabilities", None)
        if not isinstance(name, str) or not _IDENTIFIER.match(name):
            raise AdapterRegistrationError(f"{adapter.__qualname__}: invalid adapter name {name!r}")
        if not isinstance(capabilities, frozenset) or not capabilities:
            raise AdapterRegistrationError(
                f"adapter {name!r}: capabilities must be a non-empty frozenset"
            )
        if bad := sorted(c for c in capabilities if not _IDENTIFIER.match(str(c))):
            raise AdapterRegistrationError(f"adapter {name!r}: invalid capabilities {bad}")
        if name in self._adapters:
            raise AdapterRegistrationError(f"adapter {name!r} is already registered")
        self._adapters[name] = adapter
        return adapter

    @property
    def adapters(self) -> tuple[type[TestAdapter], ...]:
        """All registered adapter classes, in registration order."""
        return tuple(self._adapters.values())

    def get(self, name: str) -> type[TestAdapter] | None:
        return self._adapters.get(name)

    @property
    def available_capabilities(self) -> frozenset[str]:
        return frozenset(c for adapter in self._adapters.values() for c in adapter.capabilities)

    def select(
        self, required: Collection[str], *, allowed: Collection[str] | None = None
    ) -> AdapterSelection:
        """Choose one adapter for every required capability.

        ``allowed`` restricts the choice to named adapters (an Execution Plan's
        ``adapters``). Raises ``AdapterSelectionError`` when a capability has no
        provider, or several providers and ``allowed`` does not settle it.
        """
        candidates = self._candidates(allowed)

        provider_of: dict[str, type[TestAdapter]] = {}
        missing: list[str] = []
        ambiguous: list[str] = []
        for capability in sorted(set(required)):
            providers = [a for a in candidates if capability in a.capabilities]
            if not providers:
                missing.append(capability)
            elif len(providers) > 1:
                names = ", ".join(a.name for a in providers)
                ambiguous.append(f"{capability} ({names})")
            else:
                provider_of[capability] = providers[0]

        problems = []
        if missing:
            scope = "the allowed adapters" if allowed is not None else "any registered adapter"
            problems.append(f"not provided by {scope}: {', '.join(missing)}")
        if ambiguous:
            problems.append(
                f"provided by several adapters, choose one in the plan: {'; '.join(ambiguous)}"
            )
        if problems:
            raise AdapterSelectionError("cannot select adapters: " + "; ".join(problems))

        chosen = set(provider_of.values())
        return AdapterSelection(
            adapters=tuple(a for a in candidates if a in chosen), provider_of=provider_of
        )

    def _candidates(self, allowed: Collection[str] | None) -> list[type[TestAdapter]]:
        if allowed is None:
            return list(self._adapters.values())
        if unknown := sorted(set(allowed) - set(self._adapters)):
            raise AdapterSelectionError(f"unknown adapters: {', '.join(unknown)}")
        return [a for name, a in self._adapters.items() if name in set(allowed)]


def builtin_adapters() -> AdapterRegistry:
    """Registry of the platform's built-in adapters (empty until TASK-039)."""
    return AdapterRegistry()
