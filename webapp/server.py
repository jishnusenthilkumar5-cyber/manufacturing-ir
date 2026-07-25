from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from mir.backends import registry
from mir.compare import compare_factories
from mir.core.model import Factory
from mir.decide import DesignSpace, DesignSpaceError, Objective, recommend, sensitivity, sweep
from mir.dsl import DSLParseError, DSLValidationError, dumps_mir, loads_mir
from mir.io import IRLoadError, dumps_canonical, factory_json_schema, loads_factory
from mir.passes import analyze_factory, validate_factory
from mir.report import render_comparison_report, render_factory_report
from mir.sim import DispatchPolicy, Scenario, SimulationError, simulate
from mir.synth import CATALOG

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
EXAMPLES_DIR = REPO_ROOT / "examples"
VERSION = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()


class ApiError(Exception):
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("error", ""))
        self.status_code = status_code
        self.payload = payload


def _parse_error(message: str) -> ApiError:
    return ApiError(400, {"error": message, "kind": "parse"})


def _invocation_error(message: str) -> ApiError:
    return ApiError(400, {"error": message, "kind": "invocation"})


def _semantic_error(diagnostics: list[dict[str, Any]]) -> ApiError:
    return ApiError(
        422,
        {"error": "invalid factory", "kind": "semantic", "diagnostics": diagnostics},
    )


def _require_object(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise _invocation_error("request body must be a JSON object")
    return body


def _load_source(raw: Any) -> Factory:
    if not isinstance(raw, dict):
        raise _invocation_error("'source' must be an object with 'format' and 'text'")
    fmt = raw.get("format")
    text = raw.get("text")
    if fmt not in ("mir", "json"):
        raise _invocation_error("source format must be 'mir' or 'json'")
    if not isinstance(text, str):
        raise _invocation_error("source text must be a string")
    if fmt == "mir":
        try:
            return loads_mir(text)
        except (DSLParseError, DSLValidationError) as exc:
            raise _parse_error(str(exc)) from exc
    try:
        return loads_factory(text)
    except IRLoadError as exc:
        raise _parse_error(str(exc)) from exc


def _validated(factory: Factory) -> Factory:
    result = validate_factory(factory)
    if result.has_errors:
        raise _semantic_error([item.to_dict() for item in result.diagnostics])
    return factory


def _load_validated_source(raw: Any) -> Factory:
    return _validated(_load_source(raw))


def _scenario(raw: Any) -> Scenario:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise _invocation_error("'scenario' must be an object")
    horizon_h = raw.get("horizon_h", 24.0)
    warmup_h = raw.get("warmup_h", 1.0)
    seed = raw.get("seed", 1)
    replications = raw.get("replications", 10)
    dispatch = raw.get("dispatch", "fifo-fair")
    if not isinstance(horizon_h, (int, float)) or isinstance(horizon_h, bool):
        raise _invocation_error("scenario horizon_h must be a number")
    if not isinstance(warmup_h, (int, float)) or isinstance(warmup_h, bool):
        raise _invocation_error("scenario warmup_h must be a number")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise _invocation_error("scenario seed must be an integer")
    if not isinstance(replications, int) or isinstance(replications, bool):
        raise _invocation_error("scenario replications must be an integer")
    if warmup_h >= horizon_h:
        raise _invocation_error("warmup_h must be less than horizon_h")
    try:
        policy = DispatchPolicy(dispatch)
    except ValueError as exc:
        choices = ", ".join(item.value for item in DispatchPolicy)
        raise _invocation_error(
            f"unknown dispatch policy {dispatch!r}; choose {choices}"
        ) from exc
    try:
        return Scenario(
            horizon_s=horizon_h * 3600.0,
            warmup_s=warmup_h * 3600.0,
            seed=seed,
            replications=replications,
            dispatch=policy,
        )
    except ValueError as exc:
        raise _invocation_error(str(exc)) from exc


def _design_space(raw: Any) -> DesignSpace:
    if not isinstance(raw, dict):
        raise _invocation_error("'space' must be a JSON object")
    try:
        return DesignSpace.from_dict(raw)
    except DesignSpaceError as exc:
        raise _parse_error(str(exc)) from exc
    except ValueError as exc:
        raise _invocation_error(str(exc)) from exc


def _workers(raw: Any) -> int | None:
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        raise _invocation_error("'workers' must be a positive integer or null")
    return raw


app = FastAPI(title="MIR Workbench", version=VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.payload)


@app.exception_handler(Exception)
async def _unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    return {
        "version": VERSION,
        "generators": sorted(CATALOG),
        "dispatch_policies": [item.value for item in DispatchPolicy],
        "backends": list(registry.names()),
        "objectives": [item.value for item in Objective],
    }


@app.get("/api/examples")
def examples() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for path in sorted(EXAMPLES_DIR.iterdir()):
        if not path.is_file():
            continue
        if path.name == "sweep-space.json":
            fmt = "space"
        elif path.suffix == ".mir":
            fmt = "mir"
        elif path.suffix == ".json":
            fmt = "json"
        else:
            continue
        items.append(
            {"name": path.name, "format": fmt, "text": path.read_text(encoding="utf-8")}
        )
    return items


@app.get("/api/schema")
def schema() -> JSONResponse:
    return JSONResponse(content=factory_json_schema())


@app.post("/api/synth")
async def synth(request: Request) -> dict[str, str]:
    body = _require_object(await request.json())
    generator = body.get("generator")
    options = body.get("options") or {}
    if not isinstance(generator, str) or generator not in CATALOG:
        choices = ", ".join(sorted(CATALOG))
        raise _invocation_error(f"unknown generator {generator!r}; choose {choices}")
    if not isinstance(options, dict):
        raise _invocation_error("'options' must be an object")
    try:
        factory = CATALOG[generator](**options)
    except (TypeError, ValueError) as exc:
        raise _invocation_error(str(exc)) from exc
    return {"json_text": dumps_canonical(factory), "mir_text": dumps_mir(factory)}


@app.post("/api/validate")
async def validate(request: Request) -> dict[str, Any]:
    body = _require_object(await request.json())
    factory = _load_source(body.get("source"))
    result = validate_factory(factory)
    return {
        "valid": not result.has_errors,
        "diagnostics": [item.to_dict() for item in result.diagnostics],
    }


@app.post("/api/fmt")
async def fmt(request: Request) -> dict[str, Any]:
    body = _require_object(await request.json())
    raw = body.get("source")
    factory = _load_source(raw)
    text = raw["text"]
    canonical = dumps_canonical(factory) if raw["format"] == "json" else dumps_mir(factory)
    return {"canonical": canonical, "changed": canonical != text}


@app.post("/api/compile")
async def compile_endpoint(request: Request) -> dict[str, str]:
    body = _require_object(await request.json())
    text = body.get("text")
    if not isinstance(text, str):
        raise _invocation_error("'text' must be a string")
    try:
        factory = loads_mir(text)
    except (DSLParseError, DSLValidationError) as exc:
        raise _parse_error(str(exc)) from exc
    return {"json_text": dumps_canonical(factory)}


@app.post("/api/decompile")
async def decompile_endpoint(request: Request) -> dict[str, str]:
    body = _require_object(await request.json())
    text = body.get("text")
    if not isinstance(text, str):
        raise _invocation_error("'text' must be a string")
    try:
        factory = loads_factory(text)
    except IRLoadError as exc:
        raise _parse_error(str(exc)) from exc
    return {"mir_text": dumps_mir(factory)}


@app.post("/api/analyze")
async def analyze(request: Request) -> dict[str, Any]:
    body = _require_object(await request.json())
    factory = _load_source(body.get("source"))
    result = analyze_factory(factory)
    topology = result.artifacts["topology"]["analysis"]
    capacity = result.artifacts["capacity"]["analysis"]
    return {
        "diagnostics": [item.to_dict() for item in result.diagnostics],
        "analysis": {
            "topology": topology.to_dict(),
            "capacity": capacity.to_dict(),
        },
    }


@app.post("/api/simulate")
async def simulate_endpoint(request: Request) -> dict[str, Any]:
    body = _require_object(await request.json())
    factory = _load_validated_source(body.get("source"))
    scenario = _scenario(body.get("scenario"))
    try:
        result = simulate(factory, scenario)
    except (SimulationError, ValueError) as exc:
        raise _invocation_error(str(exc)) from exc
    return result.to_dict()


@app.post("/api/sweep")
async def sweep_endpoint(request: Request) -> dict[str, Any]:
    body = _require_object(await request.json())
    factory = _load_validated_source(body.get("source"))
    space = _design_space(body.get("space"))
    scenario = _scenario(body.get("scenario"))
    workers = _workers(body.get("workers"))
    try:
        result = sweep(factory, space, scenario, max_workers=workers)
    except (SimulationError, ValueError) as exc:
        raise _invocation_error(str(exc)) from exc
    return result.to_dict()


@app.post("/api/recommend")
async def recommend_endpoint(request: Request) -> dict[str, Any]:
    body = _require_object(await request.json())
    factory = _load_validated_source(body.get("source"))
    space = _design_space(body.get("space"))
    scenario = _scenario(body.get("scenario"))
    workers = _workers(body.get("workers"))
    objective_raw = body.get("objective", "throughput")
    top_k = body.get("top_k", 3)
    try:
        objective = Objective(objective_raw)
    except ValueError as exc:
        choices = ", ".join(item.value for item in Objective)
        raise _invocation_error(
            f"unknown objective {objective_raw!r}; choose {choices}"
        ) from exc
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise _invocation_error("'top_k' must be a positive integer")
    try:
        result = recommend(
            factory,
            space,
            scenario,
            objective=objective,
            top_k=top_k,
            max_workers=workers,
        )
    except (SimulationError, ValueError) as exc:
        raise _invocation_error(str(exc)) from exc
    return result.to_dict()


@app.post("/api/sensitivity")
async def sensitivity_endpoint(request: Request) -> dict[str, Any]:
    body = _require_object(await request.json())
    factory = _load_validated_source(body.get("source"))
    scenario = _scenario(body.get("scenario"))
    percent = body.get("percent", 10.0)
    if not isinstance(percent, (int, float)) or isinstance(percent, bool) or percent <= 0:
        raise _invocation_error("'percent' must be a positive number")
    try:
        result = sensitivity(factory, scenario, percent=float(percent))
    except (SimulationError, ValueError) as exc:
        raise _invocation_error(str(exc)) from exc
    return result.to_dict()


@app.post("/api/report")
async def report(request: Request) -> HTMLResponse:
    body = _require_object(await request.json())
    factory = _load_validated_source(body.get("source"))
    scenario = _scenario(body.get("scenario"))
    try:
        html = render_factory_report(factory, scenario)
    except (SimulationError, ValueError) as exc:
        raise _invocation_error(str(exc)) from exc
    return HTMLResponse(content=html)


@app.post("/api/report/compare")
async def report_compare(request: Request) -> HTMLResponse:
    body = _require_object(await request.json())
    baseline = _load_validated_source(body.get("baseline"))
    variant = _load_validated_source(body.get("variant"))
    scenario = _scenario(body.get("scenario"))
    try:
        html = render_comparison_report(baseline, variant, scenario)
    except (SimulationError, ValueError) as exc:
        raise _invocation_error(str(exc)) from exc
    return HTMLResponse(content=html)


@app.post("/api/compare")
async def compare(request: Request) -> dict[str, Any]:
    body = _require_object(await request.json())
    baseline = _load_validated_source(body.get("baseline"))
    variant = _load_validated_source(body.get("variant"))
    scenario = _scenario(body.get("scenario"))
    try:
        result = compare_factories(baseline, variant, scenario)
    except (SimulationError, ValueError) as exc:
        raise _invocation_error(str(exc)) from exc
    return result.to_dict()


def _emit_files(body: dict[str, Any]) -> dict[str, str]:
    factory = _load_validated_source(body.get("source"))
    backend_name = body.get("backend", "st")
    if not isinstance(backend_name, str):
        raise _invocation_error("'backend' must be a string")
    try:
        backend = registry.get(backend_name)
    except KeyError as exc:
        choices = ", ".join(registry.names())
        raise _invocation_error(
            f"unknown backend {backend_name!r}; choose {choices}"
        ) from exc
    try:
        return backend.emit(factory)
    except (TypeError, ValueError) as exc:
        raise _invocation_error(str(exc)) from exc


@app.post("/api/emit")
async def emit(request: Request) -> dict[str, Any]:
    body = _require_object(await request.json())
    files = _emit_files(body)
    manifest = json.loads(files["manifest.json"]) if "manifest.json" in files else None
    return {"files": files, "manifest": manifest}


@app.post("/api/emit/zip")
async def emit_zip(request: Request) -> Response:
    body = _require_object(await request.json())
    files = _emit_files(body)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name])
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="emitted.zip"'},
    )


@app.get("/{full_path:path}")
async def static_frontend(full_path: str) -> Response:
    if full_path.startswith("api/") or full_path == "api":
        return JSONResponse(status_code=404, content={"error": "not found"})
    if STATIC_DIR.is_dir():
        candidate = (STATIC_DIR / full_path).resolve() if full_path else None
        if (
            candidate is not None
            and candidate.is_file()
            and candidate.is_relative_to(STATIC_DIR.resolve())
        ):
            return FileResponse(candidate)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
    return JSONResponse(status_code=404, content={"error": "not found"})
