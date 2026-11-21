"""Step resolution: link specification steps to registered implementations (TASK-025).

Resolution is deterministic and never guesses: a step is resolved only when
exactly one definition of a compatible kind matches its whole text.
"""

from dataclasses import dataclass

from qa_core.steps.registry import (
    NO_ARGUMENTS,
    StepArguments,
    StepDefinition,
    StepParameterError,
    StepRegistry,
    kinds_compatible,
)
from qa_schemas.base import SchemaModel
from qa_schemas.compilation import UnresolvedStep
from qa_schemas.enums import StepKind
from qa_schemas.specification import StepParameter, TestSpecification


@dataclass(frozen=True)
class StepResolution:
    definition: StepDefinition | None
    parameters: dict[str, StepParameter]
    problem: str | None
    """Why the step is not resolved; None when it is."""


class SpecificationResolution(SchemaModel):
    specification: TestSpecification
    """With ``action``/``parameters`` filled in for resolved steps and
    ``required_capabilities`` derived from them."""
    unresolved: tuple[UnresolvedStep, ...] = ()

    @property
    def fully_resolved(self) -> bool:
        return not self.unresolved


def resolve_step(
    registry: StepRegistry,
    text: str,
    kind: StepKind,
    arguments: StepArguments = NO_ARGUMENTS,
) -> StepResolution:
    """Find the definition for a step and check its parameters (TASK-032)."""
    matches = [(d, params) for d in registry.definitions if (params := d.match(text)) is not None]
    compatible = [(d, params) for d, params in matches if kinds_compatible(d.kind, kind)]

    if len(compatible) == 1:
        definition, parameters = compatible[0]
        try:
            definition.bind(parameters, arguments)
        except StepParameterError as error:
            return StepResolution(None, {}, f"{definition.id}: {error}")
        return StepResolution(definition, parameters, None)
    if compatible:
        ids = ", ".join(sorted(d.id for d, _ in compatible))
        return StepResolution(None, {}, f"ambiguous: matches several steps ({ids})")
    if matches:
        other = ", ".join(sorted(f"{d.id} ({d.kind.value})" for d, _ in matches))
        return StepResolution(
            None, {}, f"matches {other}, which cannot be used as a {kind.value} step"
        )
    return StepResolution(None, {}, "no step definition matches this text")


def resolve_specification(
    specification: TestSpecification, registry: StepRegistry
) -> SpecificationResolution:
    unresolved: list[UnresolvedStep] = []
    capabilities: set[str] = set(specification.required_capabilities)
    cases = []
    for case in specification.test_cases:
        steps = []
        for index, step in enumerate(case.steps):
            arguments = StepArguments(
                data_table=step.data_table,
                doc_string=step.doc_string.content if step.doc_string else None,
            )
            result = resolve_step(registry, step.text, step.kind, arguments)
            if result.definition is None:
                unresolved.append(
                    UnresolvedStep(
                        test_case_id=case.id,
                        step_index=index,
                        line=step.line,
                        kind=step.kind,
                        text=step.text,
                        reason=result.problem or "not resolved",
                    )
                )
                steps.append(step.model_copy(update={"action": None, "parameters": {}}))
            else:
                capabilities.add(result.definition.capability)
                steps.append(
                    step.model_copy(
                        update={"action": result.definition.id, "parameters": result.parameters}
                    )
                )
        cases.append(case.model_copy(update={"steps": tuple(steps)}))

    resolved = specification.model_copy(
        update={"test_cases": tuple(cases), "required_capabilities": tuple(sorted(capabilities))}
    )
    # model_copy does not validate; make sure the result is still a valid specification.
    resolved = TestSpecification.model_validate(resolved.model_dump())
    return SpecificationResolution(specification=resolved, unresolved=tuple(unresolved))
