from mir.core.model import Factory
from mir.passes.base import (
    Diagnostic,
    PassContext,
    PassManager,
    PassResult,
    PipelineResult,
    Severity,
)
from mir.passes.capacity import CapacityPass
from mir.passes.semantic import SemanticValidationPass
from mir.passes.structural import StructuralValidationPass
from mir.passes.topology import TopologyPass


def validation_manager() -> PassManager:
    return PassManager([StructuralValidationPass(), SemanticValidationPass()])


def validate_factory(factory: Factory) -> PipelineResult:
    return validation_manager().run(factory)


def analysis_manager() -> PassManager:
    return PassManager(
        [
            StructuralValidationPass(),
            SemanticValidationPass(),
            TopologyPass(),
            CapacityPass(),
        ]
    )


def analyze_factory(factory: Factory) -> PipelineResult:
    return analysis_manager().run(factory, targets=["semantic", "capacity"])


__all__ = [
    "CapacityPass",
    "Diagnostic",
    "PassContext",
    "PassManager",
    "PassResult",
    "PipelineResult",
    "SemanticValidationPass",
    "Severity",
    "StructuralValidationPass",
    "TopologyPass",
    "analysis_manager",
    "analyze_factory",
    "validate_factory",
    "validation_manager",
]
