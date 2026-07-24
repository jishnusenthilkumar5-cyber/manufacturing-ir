from __future__ import annotations

import json
import re

import pytest

from mir.backends import SAFETY_NOTICE, StructuredTextBackend
from mir.core.distributions import ConstantDistribution
from mir.core.model import (
    Factory,
    FactoryMeta,
    Machine,
    Operation,
    Provenance,
    ProvenanceKind,
    Signal,
    SignalDataType,
    SignalSemantic,
)


def make_factory(
    *,
    machines: list[Machine] | None = None,
    operations: list[Operation] | None = None,
    signals: list[Signal] | None = None,
) -> Factory:
    return Factory(
        meta=FactoryMeta(
            id="line-01",
            name="Line 01",
            provenance=Provenance(kind=ProvenanceKind.SYNTHETIC, source="test"),
        ),
        machines=machines or [],
        operations=operations or [],
        signals=signals or [],
    )


def machine(machine_id: str) -> Machine:
    return Machine(
        id=machine_id,
        name=machine_id,
        machine_class="processor",
        capabilities=["process"],
    )


def operation(operation_id: str, machine_ids: list[str]) -> Operation:
    return Operation(
        id=operation_id,
        name=operation_id,
        kind="process",
        machines=machine_ids,
        cycle_time=ConstantDistribution(value_s=10),
    )


def signal(
    signal_id: str,
    tag: str,
    machine_id: str,
    dtype: SignalDataType,
    semantic: SignalSemantic = SignalSemantic.CUSTOM,
    enum_states: dict[str, int] | None = None,
) -> Signal:
    return Signal(
        id=signal_id,
        tag=tag,
        machine=machine_id,
        dtype=dtype,
        semantic=semantic,
        enum_states=enum_states,
    )


def populated_factory() -> Factory:
    return make_factory(
        machines=[machine("machine-02"), machine("machine-01"), machine("machine-03")],
        operations=[
            operation("op-shared", ["machine-02", "machine-01"]),
            operation("op-three", ["machine-03"]),
            operation("op-one", ["machine-01"]),
        ],
        signals=[
            signal(
                "m2-state",
                "M2.STATE",
                "machine-02",
                SignalDataType.ENUM,
                SignalSemantic.MACHINE_STATE,
                {"idle": 0, "running": 1},
            ),
            signal(
                "m1-count",
                "M1-COUNT",
                "machine-01",
                SignalDataType.INT,
                SignalSemantic.CYCLE_COUNT,
            ),
            signal("m3-alarm", "M3 ALARM", "machine-03", SignalDataType.BOOL),
        ],
    )


def test_n_machines_emit_n_st_files_and_manifest() -> None:
    files = StructuredTextBackend().emit(populated_factory())

    assert tuple(files) == (
        "machine_01.st",
        "machine_02.st",
        "machine_03.st",
        "manifest.json",
    )
    assert len([path for path in files if path.endswith(".st")]) == 3
    assert len(files) == 4


def test_empty_factory_emits_manifest_only() -> None:
    files = StructuredTextBackend().emit(make_factory())
    manifest = json.loads(files["manifest.json"])

    assert tuple(files) == ("manifest.json",)
    assert manifest["machines"] == []


def test_emission_is_byte_deterministic_for_reordered_model() -> None:
    original = populated_factory()
    reordered = original.model_copy(deep=True)
    reordered.machines.reverse()
    reordered.operations.reverse()
    reordered.signals.reverse()
    state_signal = next(
        item for item in reordered.signals if item.semantic is SignalSemantic.MACHINE_STATE
    )
    state_signal.enum_states = dict(reversed(tuple(state_signal.enum_states.items())))

    backend = StructuredTextBackend()
    first = backend.emit(original)
    second = backend.emit(reordered)

    assert second == first
    assert backend.emit(original) == first
    assert all(text.endswith("\n") for text in first.values())


def test_all_signal_dtype_mappings_and_state_type() -> None:
    factory = make_factory(
        machines=[machine("machine-01")],
        signals=[
            signal("bool", "BOOL-TAG", "machine-01", SignalDataType.BOOL),
            signal("int", "INT-TAG", "machine-01", SignalDataType.INT),
            signal("float", "FLOAT-TAG", "machine-01", SignalDataType.FLOAT),
            signal("enum", "ENUM-TAG", "machine-01", SignalDataType.ENUM),
            signal(
                "state",
                "STATE-TAG",
                "machine-01",
                SignalDataType.ENUM,
                SignalSemantic.MACHINE_STATE,
                {"idle": 0, "running": 1},
            ),
        ],
    )

    text = StructuredTextBackend().emit(factory)["machine_01.st"]

    assert "BOOL_TAG : BOOL;" in text
    assert "INT_TAG : DINT;" in text
    assert "FLOAT_TAG : LREAL;" in text
    assert "ENUM_TAG : INT;" in text
    assert "STATE_TAG : T_MACHINE_01_STATE;" in text


def test_custom_states_are_numeric_then_name_sorted() -> None:
    factory = make_factory(
        machines=[machine("machine-01")],
        signals=[
            signal(
                "state",
                "STATE",
                "machine-01",
                SignalDataType.ENUM,
                SignalSemantic.MACHINE_STATE,
                {"stopped": 10, "running": 2, "idle": 0},
            )
        ],
    )

    text = StructuredTextBackend().emit(factory)["machine_01.st"]

    assert text.index("STATE_IDLE := 0") < text.index("STATE_RUNNING := 2")
    assert text.index("STATE_RUNNING := 2") < text.index("STATE_STOPPED := 10")
    assert "STATE_BLOCKED" not in text


@pytest.mark.parametrize("enum_states", [None, {}])
def test_missing_state_vocabulary_uses_known_fallback(
    enum_states: dict[str, int] | None,
) -> None:
    signals = []
    if enum_states is not None:
        signals.append(
            signal(
                "state",
                "STATE",
                "machine-01",
                SignalDataType.ENUM,
                SignalSemantic.MACHINE_STATE,
                enum_states,
            )
        )
    factory = make_factory(machines=[machine("machine-01")], signals=signals)

    text = StructuredTextBackend().emit(factory)["machine_01.st"]

    assert "STATE_IDLE := 0" in text
    assert "STATE_RUNNING := 1" in text
    assert "STATE_BLOCKED := 2" in text
    assert "STATE_STARVED := 3" in text
    assert "STATE_SETUP := 4" in text
    assert "STATE_DOWN := 5" in text


def test_identifiers_are_sanitized_and_iec_keywords_are_escaped() -> None:
    factory = make_factory(
        machines=[machine("9-cell")],
        operations=[operation("if", ["9-cell"])],
        signals=[
            signal("speed", "9-speed", "9-cell", SignalDataType.FLOAT),
            signal("keyword", "VAR", "9-cell", SignalDataType.BOOL),
            signal(
                "state",
                "CELL.STATE",
                "9-cell",
                SignalDataType.ENUM,
                SignalSemantic.MACHINE_STATE,
                {"manual mode": 0, "auto-mode": 1},
            ),
        ],
    )

    files = StructuredTextBackend().emit(factory)
    text = files["9_cell.st"]

    assert "T_9_CELL_STATE" in text
    assert "ID_9_SPEED : LREAL;" in text
    assert "ID_VAR : BOOL;" in text
    assert "STATE_MANUAL_MODE := 0" in text
    assert "STATE_AUTO_MODE := 1" in text
    assert "FUNCTION_BLOCK FB_9_CELL_IF" in text

    identifiers = [
        "T_9_CELL_STATE",
        "ID_9_SPEED",
        "ID_VAR",
        "STATE_MANUAL_MODE",
        "STATE_AUTO_MODE",
        "FB_9_CELL_IF",
    ]
    assert all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", item) for item in identifiers)


def test_machine_filename_collision_is_rejected_deterministically() -> None:
    first = make_factory(machines=[machine("cell-a"), machine("cell_a")])
    second = make_factory(machines=list(reversed(first.machines)))

    with pytest.raises(ValueError, match="machine output paths") as first_error:
        StructuredTextBackend().emit(first)
    with pytest.raises(ValueError) as second_error:
        StructuredTextBackend().emit(second)

    assert str(second_error.value) == str(first_error.value)
    assert "'cell-a'" in str(first_error.value)
    assert "'cell_a'" in str(first_error.value)


def test_signal_identifier_collision_is_rejected() -> None:
    factory = make_factory(
        machines=[machine("cell")],
        signals=[
            signal("first", "rate-a", "cell", SignalDataType.FLOAT),
            signal("second", "rate_a", "cell", SignalDataType.FLOAT),
        ],
    )

    with pytest.raises(ValueError, match="signal identifiers.*RATE_A"):
        StructuredTextBackend().emit(factory)


def test_operation_identifier_collision_is_rejected() -> None:
    factory = make_factory(
        machines=[machine("cell")],
        operations=[operation("op-a", ["cell"]), operation("op_a", ["cell"])],
    )

    with pytest.raises(ValueError, match="operation identifiers.*FB_CELL_OP_A"):
        StructuredTextBackend().emit(factory)


def test_state_identifier_collision_is_rejected() -> None:
    factory = make_factory(
        machines=[machine("cell")],
        signals=[
            signal(
                "state",
                "STATE",
                "cell",
                SignalDataType.ENUM,
                SignalSemantic.MACHINE_STATE,
                {"run-fast": 1, "run_fast": 2},
            )
        ],
    )

    with pytest.raises(ValueError, match="state identifiers.*STATE_RUN_FAST"):
        StructuredTextBackend().emit(factory)


def test_multiple_machine_state_signals_are_rejected() -> None:
    factory = make_factory(
        machines=[machine("cell")],
        signals=[
            signal(
                "state-a",
                "STATE_A",
                "cell",
                SignalDataType.ENUM,
                SignalSemantic.MACHINE_STATE,
                {"idle": 0},
            ),
            signal(
                "state-b",
                "STATE_B",
                "cell",
                SignalDataType.ENUM,
                SignalSemantic.MACHINE_STATE,
                {"running": 1},
            ),
        ],
    )

    with pytest.raises(ValueError, match="multiple machine_state signals.*state-a.*state-b"):
        StructuredTextBackend().emit(factory)


def test_manifest_is_complete_and_sorted() -> None:
    files = StructuredTextBackend().emit(populated_factory())
    manifest = json.loads(files["manifest.json"])

    assert manifest == {
        "backend": "st",
        "factory": {"id": "line-01", "schema_version": "0.1.0"},
        "machines": [
            {
                "machine_id": "machine-01",
                "operations": ["op-one", "op-shared"],
                "path": "machine_01.st",
                "signals": ["m1-count"],
                "state_type": "T_MACHINE_01_STATE",
            },
            {
                "machine_id": "machine-02",
                "operations": ["op-shared"],
                "path": "machine_02.st",
                "signals": ["m2-state"],
                "state_type": "T_MACHINE_02_STATE",
            },
            {
                "machine_id": "machine-03",
                "operations": ["op-three"],
                "path": "machine_03.st",
                "signals": ["m3-alarm"],
                "state_type": "T_MACHINE_03_STATE",
            },
        ],
        "safety_notice": SAFETY_NOTICE,
        "target": "IEC 61131-3 Structured Text (vendor-neutral skeleton)",
    }
    assert {item["path"] for item in manifest["machines"]} == set(files) - {
        "manifest.json"
    }
    assert files["manifest.json"].endswith("\n")


def test_generated_files_warn_that_skeletons_are_not_deployable() -> None:
    files = StructuredTextBackend().emit(populated_factory())

    for path, text in files.items():
        lowered = text.lower()
        assert "vendor-neutral" in lowered, path
        assert "safety review" in lowered, path
        assert "not deployable control logic" in lowered, path


def test_iec_blocks_are_balanced_per_machine() -> None:
    files = StructuredTextBackend().emit(populated_factory())
    manifest = json.loads(files["manifest.json"])

    for entry in manifest["machines"]:
        text = files[entry["path"]]
        tokens = [line.strip().split(maxsplit=1)[0] for line in text.splitlines() if line.strip()]
        operation_count = len(entry["operations"])
        signal_section_count = int(bool(entry["signals"]))

        assert tokens.count("TYPE") == tokens.count("END_TYPE") == 1
        assert tokens.count("FUNCTION_BLOCK") == tokens.count("END_FUNCTION_BLOCK")
        assert tokens.count("FUNCTION_BLOCK") == operation_count
        assert tokens.count("VAR_INPUT") == operation_count
        assert tokens.count("VAR_OUTPUT") == operation_count
        assert tokens.count("VAR_GLOBAL") == signal_section_count
        assert tokens.count("END_VAR") == operation_count * 2 + signal_section_count
