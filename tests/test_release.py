from __future__ import annotations

import tomllib
from pathlib import Path

from mir import SCHEMA_VERSION, __version__
from mir.decide import DesignSpace
from mir.dsl import dumps_mir, read_mir
from mir.io import loads_factory


ROOT = Path(__file__).parents[1]


def test_release_versions_are_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert project["project"]["version"] == version_file == SCHEMA_VERSION == __version__
    assert project["project"]["dependencies"] == [
        "pydantic>=2.7,<3",
        "typer>=0.12,<1",
    ]


def test_committed_dsl_and_design_space_examples_are_canonical_and_compatible() -> None:
    source = ROOT / "examples" / "line.mir"
    text = source.read_text(encoding="utf-8")
    factory = read_mir(source)
    assert dumps_mir(factory) == text
    assert factory == loads_factory(ROOT / "examples" / "assembly-2to1.json")

    space = DesignSpace.from_json(ROOT / "examples" / "sweep-space.json")
    space.validate_against(factory)
    assert space.point_count == 4
