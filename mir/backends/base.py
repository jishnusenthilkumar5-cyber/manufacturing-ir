from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol, runtime_checkable

from mir.core.model import Factory


@runtime_checkable
class Backend(Protocol):
    name: str
    target: str

    def emit(self, factory: Factory) -> dict[str, str]: ...


class BackendRegistry:
    def __init__(self, backends: Iterable[Backend] = ()) -> None:
        self._backends: dict[str, Backend] = {}
        for backend in backends:
            self.register(backend)

    def register(self, backend: Backend) -> None:
        if not isinstance(backend, Backend):
            raise TypeError("backend must provide name, target, and emit")
        if not isinstance(backend.name, str) or not backend.name:
            raise ValueError("backend name must be a nonempty string")
        if not isinstance(backend.target, str) or not backend.target:
            raise ValueError(f"backend {backend.name!r} target must be a nonempty string")
        if backend.name in self._backends:
            raise ValueError(f"backend {backend.name!r} is already registered")
        self._backends[backend.name] = backend

    def get(self, name: str) -> Backend:
        try:
            return self._backends[name]
        except KeyError as exc:
            raise KeyError(f"unknown backend {name!r}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._backends))

    def __contains__(self, name: object) -> bool:
        return name in self._backends

    def __iter__(self) -> Iterator[Backend]:
        for name in self.names():
            yield self._backends[name]

    def __len__(self) -> int:
        return len(self._backends)


def _validate_emitted_files(files: Mapping[str, str]) -> list[tuple[str, PurePosixPath, str]]:
    items = list(files.items())
    for relative_path, text in items:
        if not isinstance(relative_path, str):
            raise TypeError("emitted paths must be strings")
        if not isinstance(text, str):
            raise TypeError(f"emitted file {relative_path!r} must contain text")

    validated: list[tuple[str, PurePosixPath, str]] = []
    seen: dict[str, str] = {}
    for relative_path, text in sorted(items, key=lambda item: item[0]):
        if not relative_path or "\x00" in relative_path:
            raise ValueError(f"unsafe emitted path {relative_path!r}")
        windows_path = PureWindowsPath(relative_path)
        posix_path = PurePosixPath(relative_path)
        if windows_path.anchor or windows_path.drive or posix_path.is_absolute():
            raise ValueError(f"absolute emitted path is not allowed: {relative_path!r}")
        if relative_path.endswith(("/", "\\")):
            raise ValueError(f"emitted path must identify a file: {relative_path!r}")
        if ".." in windows_path.parts or ".." in posix_path.parts:
            raise ValueError(f"parent traversal is not allowed: {relative_path!r}")

        normalized = PurePosixPath(relative_path.replace("\\", "/"))
        if normalized == PurePosixPath("."):
            raise ValueError(f"unsafe emitted path {relative_path!r}")
        collision_key = normalized.as_posix().casefold()
        if collision_key in seen:
            first = seen[collision_key]
            raise ValueError(
                f"emitted paths collide after normalization: {first!r}, {relative_path!r}"
            )
        seen[collision_key] = relative_path
        validated.append((relative_path, normalized, text))

    normalized_paths = {path.as_posix().casefold(): original for original, path, _ in validated}
    for original, normalized, _ in validated:
        for parent in normalized.parents:
            if parent == PurePosixPath("."):
                break
            parent_key = parent.as_posix().casefold()
            if parent_key in normalized_paths:
                other = normalized_paths[parent_key]
                raise ValueError(f"emitted file paths conflict: {other!r}, {original!r}")

    return validated


def emit_to_directory(
    files: Mapping[str, str], path: str | Path, force: bool = False
) -> tuple[Path, ...]:
    validated = _validate_emitted_files(files)
    destination = Path(path)

    if destination.is_symlink() and not destination.exists():
        raise NotADirectoryError(f"output path is not a directory: {destination}")
    if destination.exists() and not destination.is_dir():
        raise NotADirectoryError(f"output path is not a directory: {destination}")
    if destination.exists() and any(destination.iterdir()) and not force:
        raise FileExistsError(f"output directory is not empty: {destination}")

    resolved_root = destination.resolve(strict=False)
    targets: list[tuple[Path, str]] = []
    for _, normalized, text in validated:
        target = destination.joinpath(*normalized.parts)
        resolved_target = target.resolve(strict=False)
        if not resolved_target.is_relative_to(resolved_root):
            raise ValueError(f"emitted path escapes output directory: {normalized.as_posix()!r}")
        if target.exists() and target.is_dir():
            raise IsADirectoryError(f"emitted file path is a directory: {target}")
        parent = target.parent
        while parent != destination:
            if parent.exists() and not parent.is_dir():
                raise NotADirectoryError(f"emitted file parent is not a directory: {parent}")
            parent = parent.parent
        targets.append((target, text))

    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for target, text in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        written.append(target)
    return tuple(written)
