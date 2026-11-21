"""The platform's built-in step definitions and adapters."""

from qa_core.steps.registry import StepRegistry
from qa_execution.browser.adapter import PlaywrightAdapter
from qa_execution.browser.steps import register_navigation_steps
from qa_execution.registry import AdapterRegistry


def builtin_registry() -> StepRegistry:
    """A new registry with all built-in step definitions."""
    registry = StepRegistry()
    register_navigation_steps(registry)
    return registry


def builtin_adapters() -> AdapterRegistry:
    """A new registry with all built-in adapters."""
    return AdapterRegistry([PlaywrightAdapter])
