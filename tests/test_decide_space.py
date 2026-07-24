from __future__ import annotations

import json

import pytest

from mir import (
    Availability,
    ExponentialDistribution,
    NormalDistribution,
    UniformDistribution,
    dumps_canonical,
)
from mir.decide import (
    DesignPoint,
    DesignSpace,
    DesignSpaceError,
    DesignSpaceLimitError,
    DesignSpaceParseError,
    ParameterKind,
    ParameterPath,
    ParameterPathError,
    ParameterValueError,
    apply_design_point,
)
from mir.synth import serial_line


def test_cartesian_order_and_serialization_are_canonical() -> None:
    payload = {
        "operations.operation-01.cycle_time_scale": [1.0, 0.5],
        "flows.buffer-01.buffer_capacity": [1, 2],
    }
    space = DesignSpace.from_dict(payload)
    points = space.points()

    assert space.paths == (
        "flows.buffer-01.buffer_capacity",
        "operations.operation-01.cycle_time_scale",
    )
    assert [point.to_dict() for point in points] == [
        {
            "index": 0,
            "parameters": {
                "flows.buffer-01.buffer_capacity": 1,
                "operations.operation-01.cycle_time_scale": 1.0,
            },
        },
        {
            "index": 1,
            "parameters": {
                "flows.buffer-01.buffer_capacity": 1,
                "operations.operation-01.cycle_time_scale": 0.5,
            },
        },
        {
            "index": 2,
            "parameters": {
                "flows.buffer-01.buffer_capacity": 2,
                "operations.operation-01.cycle_time_scale": 1.0,
            },
        },
        {
            "index": 3,
            "parameters": {
                "flows.buffer-01.buffer_capacity": 2,
                "operations.operation-01.cycle_time_scale": 0.5,
            },
        },
    ]
    parsed = DesignSpace.from_json(json.dumps(payload))
    first = json.dumps(space.to_dict(), separators=(",", ":"), allow_nan=False)
    second = json.dumps(parsed.to_dict(), separators=(",", ":"), allow_nan=False)
    assert first == second


def test_json_path_and_bytes_sources_match_dict(tmp_path) -> None:
    payload = {"machines.machine-01.num_stations": [1, 2]}
    path = tmp_path / "space.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    expected = DesignSpace.from_dict(payload).to_dict()
    assert DesignSpace.from_json(path).to_dict() == expected
    assert DesignSpace.from_json(json.dumps(payload).encode()).to_dict() == expected


def test_exactly_500_points_are_allowed_and_more_fail_clearly() -> None:
    allowed = DesignSpace.from_dict(
        {
            "flows.buffer-01.buffer_capacity": list(range(20)),
            "machines.machine-01.num_stations": list(range(1, 26)),
        }
    )
    assert len(allowed) == 500
    with pytest.raises(DesignSpaceLimitError, match=r"520 points; maximum is 500"):
        DesignSpace.from_dict(
            {
                "flows.buffer-01.buffer_capacity": list(range(20)),
                "machines.machine-01.num_stations": list(range(1, 27)),
            }
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("unknown.x.value", 1),
        ("flows.buffer-01.buffer_capacity", True),
        ("flows.buffer-01.buffer_capacity", -1),
        ("machines.machine-01.num_stations", False),
        ("machines.machine-01.num_stations", 0),
        ("operations.operation-01.cycle_time_scale", 0),
        ("operations.operation-01.cycle_time_scale", float("nan")),
        ("operations.operation-01.cycle_time_scale", float("inf")),
        ("machines.machine-01.availability", True),
        ("machines.machine-01.availability", {"mtbf_s": 900}),
        (
            "machines.machine-01.availability",
            {"mtbf_s": 900, "mttr_s": 0},
        ),
        ("machines.machine-01.availability.mtbf_s", -1),
        ("machines.machine-01.availability.mttr_s", "100"),
    ],
)
def test_invalid_paths_and_values_fail_clearly(path: str, value: object) -> None:
    with pytest.raises(
        (ParameterPathError, ParameterValueError),
        match="parameter|path|must|availability|unsupported|invalid",
    ):
        DesignSpace.from_dict({path: [value]})


def test_availability_parent_and_leaf_paths_are_rejected_together() -> None:
    with pytest.raises(DesignSpaceParseError, match="parent and leaf paths conflict"):
        DesignSpace.from_dict(
            {
                "machines.machine-01.availability": [
                    None,
                    {"mtbf_s": 900, "mttr_s": 100},
                ],
                "machines.machine-01.availability.mtbf_s": [1200],
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"machines.machine-01.num_stations": []},
        {"machines.machine-01.num_stations": "not-a-list"},
    ],
)
def test_invalid_design_space_shapes_fail(payload: dict) -> None:
    with pytest.raises(DesignSpaceParseError):
        DesignSpace.from_dict(payload)


def test_invalid_json_and_duplicate_keys_fail_clearly() -> None:
    with pytest.raises(DesignSpaceParseError, match="invalid JSON at line"):
        DesignSpace.from_json("{bad-json")
    with pytest.raises(DesignSpaceParseError, match="root must be a JSON object"):
        DesignSpace.from_json("[]")
    with pytest.raises(DesignSpaceParseError, match="duplicate JSON key"):
        DesignSpace.from_json(
            '{"machines.machine-01.num_stations":[1],'
            '"machines.machine-01.num_stations":[2]}'
        )


def test_apply_deep_copies_and_mutates_every_supported_leaf_type() -> None:
    factory = serial_line(stations=2, cycle_times_s=[10, 20], buffer_capacity=2)
    factory.machines[0].availability = Availability(mtbf_s=900, mttr_s=100)
    before = dumps_canonical(factory)
    space = DesignSpace.from_dict(
        {
            "flows.buffer-01.buffer_capacity": [5],
            "machines.machine-01.availability.mtbf_s": [1200],
            "machines.machine-01.num_stations": [2],
            "operations.operation-01.cycle_time_scale": [0.5],
        }
    )

    variant = space.apply(factory, space.points()[0])

    assert dumps_canonical(factory) == before
    assert variant is not factory
    assert variant.flow_map()["buffer-01"].buffer_capacity == 5
    assert variant.machines[0].num_stations == 2
    assert variant.machines[0].availability is not factory.machines[0].availability
    assert variant.machines[0].availability.mtbf_s == 1200
    assert variant.operations[0].cycle_time.mean_seconds() == 5


def test_availability_parent_accepts_null_and_complete_objects_without_aliasing() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    availability = {"mtbf_s": 900, "mttr_s": 100}
    space = DesignSpace.from_dict(
        {"machines.machine-01.availability": [None, availability]}
    )
    availability["mtbf_s"] = 1

    disabled = space.apply(factory, space.points()[0])
    enabled = space.apply(factory, space.points()[1])

    assert factory.machines[0].availability is None
    assert disabled.machines[0].availability is None
    assert enabled.machines[0].availability == Availability(mtbf_s=900, mttr_s=100)


def test_availability_leaf_requires_existing_parent() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    space = DesignSpace.from_dict(
        {"machines.machine-01.availability.mtbf_s": [900]}
    )
    with pytest.raises(ParameterPathError, match="set 'machines.machine-01.availability' first"):
        space.validate_against(factory)


def test_missing_entity_fails_with_path_and_count() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    space = DesignSpace.from_dict({"machines.missing.num_stations": [2]})
    with pytest.raises(ParameterPathError, match=r"missing.*found 0"):
        space.validate_against(factory)


@pytest.mark.parametrize(
    ("distribution", "expected"),
    [
        (UniformDistribution(low_s=4, high_s=8), (2.0, 4.0)),
        (NormalDistribution(mean_s=8, std_s=2), (4.0, 1.0)),
        (ExponentialDistribution(mean_s=8), (4.0,)),
    ],
)
def test_cycle_scaling_preserves_distribution_shape(distribution, expected) -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    factory.operations[0].cycle_time = distribution
    space = DesignSpace.from_dict(
        {"operations.operation-01.cycle_time_scale": [0.5]}
    )

    scaled = space.apply(factory, space.points()[0]).operations[0].cycle_time

    if isinstance(scaled, UniformDistribution):
        actual = (scaled.low_s, scaled.high_s)
    elif isinstance(scaled, NormalDistribution):
        actual = (scaled.mean_s, scaled.std_s)
    else:
        actual = (scaled.mean_s,)
    assert actual == expected
    assert factory.operations[0].cycle_time == distribution


def test_limit_error_reports_complete_cartesian_size() -> None:
    with pytest.raises(DesignSpaceLimitError, match=r"1002 points; maximum is 500"):
        DesignSpace.from_dict(
            {
                "flows.buffer-01.buffer_capacity": list(range(501)),
                "machines.machine-01.num_stations": [1, 2],
            }
        )


def test_invalid_entity_id_and_non_utf8_json_file_fail_clearly(tmp_path) -> None:
    with pytest.raises(ParameterPathError, match="invalid entity id"):
        DesignSpace.from_dict({"machines.Invalid.num_stations": [1]})
    path = tmp_path / "invalid.json"
    path.write_bytes(b"\xff")
    with pytest.raises(DesignSpaceParseError, match="not valid UTF-8"):
        DesignSpace.from_json(path)


def test_space_rejects_forged_point_from_same_paths() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    space = DesignSpace.from_dict(
        {"operations.operation-01.cycle_time_scale": [1.0]}
    )
    parameter = ParameterPath.parse(
        "operations.operation-01.cycle_time_scale"
    )
    forged = DesignPoint(index=0, assignments=((parameter, 0.5),))

    with pytest.raises(DesignSpaceError, match="does not belong"):
        space.apply(factory, forged)


def test_manual_point_application_revalidates_metadata_values_and_conflicts() -> None:
    factory = serial_line(stations=1, cycle_times_s=[10])
    before = dumps_canonical(factory)
    valid = ParameterPath.parse("machines.machine-01.num_stations")
    forged = ParameterPath(
        path=valid.path,
        kind=ParameterKind.FLOW_BUFFER_CAPACITY,
        entity_id=valid.entity_id,
    )
    invalid_metadata = DesignPoint(index=0, assignments=((forged, 2),))
    invalid_value = DesignPoint(index=0, assignments=((valid, True),))
    parent = ParameterPath.parse("machines.machine-01.availability")
    leaf = ParameterPath.parse("machines.machine-01.availability.mtbf_s")
    conflict = DesignPoint(
        index=0,
        assignments=(
            (parent, {"mtbf_s": 900, "mttr_s": 100}),
            (leaf, 1200),
        ),
    )

    with pytest.raises(ParameterPathError, match="metadata does not match"):
        apply_design_point(factory, invalid_metadata)
    with pytest.raises(ParameterValueError, match="integer"):
        apply_design_point(factory, invalid_value)
    with pytest.raises(DesignSpaceError, match="parent and leaf paths conflict"):
        apply_design_point(factory, conflict)
    assert dumps_canonical(factory) == before


def test_parameter_path_has_json_safe_contract() -> None:
    parameter = ParameterPath.parse("machines.machine-01.num_stations")
    assert parameter.to_dict() == {
        "path": "machines.machine-01.num_stations",
        "kind": "machine_num_stations",
        "entity_id": "machine-01",
    }
