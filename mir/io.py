from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mir.core.model import Factory, SCHEMA_VERSION


class IRLoadError(ValueError):
    pass


class UnsupportedSchemaVersion(IRLoadError):
    pass


def _canonical_payload(factory: Factory) -> dict[str, Any]:
    payload = factory.model_dump(mode="json", exclude_none=True)
    for collection in ("machines", "operations", "flows", "signals"):
        payload[collection] = sorted(payload[collection], key=lambda item: item["id"])
    return payload


def dumps_canonical(factory: Factory) -> str:
    return json.dumps(
        _canonical_payload(factory),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def _read_source(source: str | bytes | Path) -> str:
    if isinstance(source, bytes):
        return source.decode("utf-8")
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    if source.lstrip().startswith(("{", "[")):
        return source
    path = Path(source)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return source


def loads_factory(source: str | bytes | Path) -> Factory:
    raw = _read_source(source)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IRLoadError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise IRLoadError("Manufacturing IR root must be a JSON object")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(
            f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION!r}"
        )
    try:
        return Factory.model_validate(payload)
    except ValidationError as exc:
        raise IRLoadError(str(exc)) from exc


def write_factory(factory: Factory, path: str | Path) -> Path:
    destination = Path(path)
    destination.write_text(dumps_canonical(factory), encoding="utf-8")
    return destination


def factory_json_schema() -> dict[str, Any]:
    return Factory.model_json_schema()
