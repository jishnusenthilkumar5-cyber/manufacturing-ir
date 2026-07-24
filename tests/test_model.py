from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from mir import (
    ConstantDistribution,
    ExponentialDistribution,
    Factory,
    FactoryMeta,
    Machine,
    NormalDistribution,
    Operation,
    Provenance,
    ProvenanceKind,
    UniformDistribution,
)


def test_distribution_tagged_union_parses() -> None:
    operation = Operation.model_validate(
        {
            "id": "cut",
            "name": "Cut",
            "kind": "cut",
            "machines": ["saw-01"],
            "cycle_time": {"kind": "uniform", "low_s": 4, "high_s": 6},
        }
    )
    assert isinstance(operation.cycle_time, UniformDistribution)
    assert operation.cycle_time.mean_seconds() == 5


@pytest.mark.parametrize(
    ("distribution", "expected"),
    [
        (ConstantDistribution(value_s=8), 8),
        (UniformDistribution(low_s=6, high_s=10), 8),
        (NormalDistribution(mean_s=8, std_s=0), 8),
        (ExponentialDistribution(mean_s=8), 8),
    ],
)
def test_distribution_mean(distribution, expected: float) -> None:
    assert distribution.mean_seconds() == expected
    assert distribution.sample(random.Random(1)) > 0


def test_invalid_entity_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Machine(
            id="Saw 01",
            name="Saw",
            machine_class="saw",
            capabilities=["cut"],
        )


def test_invalid_operation_yield_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Operation(
            id="cut",
            name="Cut",
            kind="cut",
            machines=["saw-01"],
            cycle_time=ConstantDistribution(value_s=1),
            yield_fraction=0,
        )


def test_factory_defaults_to_current_schema() -> None:
    factory = Factory(
        meta=FactoryMeta(
            id="test-factory",
            name="Test Factory",
            provenance=Provenance(kind=ProvenanceKind.AUTHORED),
        )
    )
    assert factory.schema_version == "0.1.0"
