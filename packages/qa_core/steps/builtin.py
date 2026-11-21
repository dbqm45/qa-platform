"""The platform's built-in step definitions.

Empty until the first step implementations are added (TASK-031); until then
every step is unresolved and every specification compiles as BLOCKED.
"""

from qa_core.steps.registry import StepRegistry


def builtin_registry() -> StepRegistry:
    """A new registry containing all built-in step definitions."""
    return StepRegistry()
