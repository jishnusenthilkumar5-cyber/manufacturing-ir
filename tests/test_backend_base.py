from __future__ import annotations

from pathlib import Path

import pytest

from mir.backends import (
    Backend,
    BackendRegistry,
    StructuredTextBackend,
    emit_to_directory,
    registry,
)
from mir.core.model import Factory, FactoryMeta, Provenance, ProvenanceKind


class ExampleBackend:
    def __init__(self, name: str = "example") -> None:
        self.name = name
        self.target = "test target"

    def emit(self, factory: Factory) -> dict[str, str]:
        return {"example.txt": factory.meta.id + "\n"}


def factory() -> Factory:
    return Factory(
        meta=FactoryMeta(
            id="line-01",
            name="Line 01",
            provenance=Provenance(kind=ProvenanceKind.SYNTHETIC),
        )
    )


def test_backend_protocol_and_registry_contract() -> None:
    beta = ExampleBackend("beta")
    alpha = ExampleBackend("alpha")
    backends = BackendRegistry([beta, alpha])

    assert isinstance(alpha, Backend)
    assert backends.names() == ("alpha", "beta")
    assert [backend.name for backend in backends] == ["alpha", "beta"]
    assert backends.get("alpha") is alpha
    assert "beta" in backends
    assert len(backends) == 2
    assert alpha.emit(factory()) == {"example.txt": "line-01\n"}


def test_registry_rejects_duplicate_and_unknown_names() -> None:
    backends = BackendRegistry([ExampleBackend()])

    with pytest.raises(ValueError, match="already registered"):
        backends.register(ExampleBackend())
    with pytest.raises(KeyError, match="unknown backend 'missing'"):
        backends.get("missing")


def test_registry_rejects_incomplete_backend() -> None:
    class IncompleteBackend:
        name = "incomplete"
        target = "test"

    with pytest.raises(TypeError, match="name, target, and emit"):
        BackendRegistry([IncompleteBackend()])


@pytest.mark.parametrize(("name", "target"), [("", "target"), ("valid", "")])
def test_registry_rejects_empty_metadata(name: str, target: str) -> None:
    backend = ExampleBackend(name)
    backend.target = target

    with pytest.raises(ValueError, match="nonempty string"):
        BackendRegistry([backend])


def test_package_registry_contains_builtin_st_backend() -> None:
    assert registry.names() == ("st",)
    assert isinstance(registry.get("st"), StructuredTextBackend)
    assert registry.get("st").target.startswith("IEC 61131-3")


def test_emit_to_directory_writes_safe_nested_paths_in_order(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    written = emit_to_directory(
        {"zeta.st": "zeta\n", "nested/alpha.st": "alpha\n"},
        output,
    )

    assert written == (output / "nested" / "alpha.st", output / "zeta.st")
    assert (output / "nested" / "alpha.st").read_bytes() == b"alpha\n"
    assert (output / "zeta.st").read_bytes() == b"zeta\n"


@pytest.mark.parametrize(
    "relative_path",
    [
        "",
        ".",
        "../escape.st",
        "nested/../../escape.st",
        r"..\escape.st",
        r"nested\..\escape.st",
        "/absolute/file.st",
        r"\rooted\file.st",
        r"C:\absolute\file.st",
        r"\\server\share\file.st",
        "directory/",
        "directory\\",
    ],
)
def test_emit_to_directory_rejects_unsafe_paths_before_writing(
    tmp_path: Path, relative_path: str
) -> None:
    output = tmp_path / "generated"

    with pytest.raises(ValueError):
        emit_to_directory({relative_path: "unsafe\n"}, output)

    assert not output.exists()


@pytest.mark.parametrize(
    "files",
    [
        {"machine/file.st": "one", "machine//file.st": "two"},
        {"machine/file.st": "one", r"machine\file.st": "two"},
        {"Machine.st": "one", "machine.st": "two"},
        {"machine": "one", "machine/file.st": "two"},
    ],
)
def test_emit_to_directory_rejects_normalized_path_collisions(
    tmp_path: Path, files: dict[str, str]
) -> None:
    output = tmp_path / "generated"

    with pytest.raises(ValueError, match="collide|conflict"):
        emit_to_directory(files, output)

    assert not output.exists()


def test_emit_to_directory_rejects_non_string_content(tmp_path: Path) -> None:
    output = tmp_path / "generated"

    with pytest.raises(TypeError, match="must contain text"):
        emit_to_directory({"machine.st": b"bytes"}, output)

    assert not output.exists()


def test_emit_to_directory_rejects_output_file(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    output.write_text("occupied\n", encoding="utf-8")

    with pytest.raises(NotADirectoryError, match="not a directory"):
        emit_to_directory({"machine.st": "new\n"}, output)

    assert output.read_text(encoding="utf-8") == "occupied\n"


def test_emit_to_directory_protects_nonempty_directory_and_force_overwrites(
    tmp_path: Path,
) -> None:
    output = tmp_path / "generated"
    output.mkdir()
    generated = output / "machine.st"
    unrelated = output / "keep.txt"
    generated.write_text("old\n", encoding="utf-8")
    unrelated.write_text("keep\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        emit_to_directory({"machine.st": "new\n"}, output)

    assert generated.read_text(encoding="utf-8") == "old\n"
    emit_to_directory({"machine.st": "new\n"}, output, force=True)
    assert generated.read_text(encoding="utf-8") == "new\n"
    assert unrelated.read_text(encoding="utf-8") == "keep\n"


def test_emit_to_directory_rejects_symlink_escape(tmp_path: Path) -> None:
    output = tmp_path / "generated"
    outside = tmp_path / "outside"
    output.mkdir()
    outside.mkdir()
    (output / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes output directory"):
        emit_to_directory({"linked/escape.st": "unsafe\n"}, output, force=True)

    assert not (outside / "escape.st").exists()
