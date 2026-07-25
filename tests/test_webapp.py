from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp.server import app

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

LINE_MIR = (EXAMPLES / "line.mir").read_text(encoding="utf-8")
UNBALANCED_JSON = (EXAMPLES / "unbalanced-line.json").read_text(encoding="utf-8")
SWEEP_SPACE = json.loads((EXAMPLES / "sweep-space.json").read_text(encoding="utf-8"))

MIR_SOURCE = {"format": "mir", "text": LINE_MIR}
JSON_SOURCE = {"format": "json", "text": UNBALANCED_JSON}
FAST_SCENARIO = {"horizon_h": 2.0, "warmup_h": 0.0, "seed": 1, "replications": 2}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app, raise_server_exceptions=False) as instance:
        yield instance


def invalid_json_source() -> dict[str, str]:
    payload = json.loads(UNBALANCED_JSON)
    payload["operations"][0]["machines"] = ["missing-machine"]
    return {"format": "json", "text": json.dumps(payload)}


def test_meta(client: TestClient) -> None:
    response = client.get("/api/meta")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert "serial-line" in body["generators"]
    assert body["dispatch_policies"] == ["fifo-fair", "priority", "shortest-cycle"]
    assert "st" in body["backends"]
    assert body["objectives"] == ["throughput", "throughput_per_wip"]


def test_examples(client: TestClient) -> None:
    response = client.get("/api/examples")
    assert response.status_code == 200
    items = {item["name"]: item for item in response.json()}
    expected = {path.name for path in EXAMPLES.iterdir() if path.is_file()}
    assert set(items) == expected
    assert items["line.mir"]["format"] == "mir"
    assert items["line.mir"]["text"] == LINE_MIR
    assert items["unbalanced-line.json"]["format"] == "json"
    assert items["sweep-space.json"]["format"] == "space"


def test_schema(client: TestClient) -> None:
    response = client.get("/api/schema")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["title"] == "Factory"


def test_synth(client: TestClient) -> None:
    response = client.post(
        "/api/synth",
        json={"generator": "serial-line", "options": {"stations": 3}},
    )
    assert response.status_code == 200
    body = response.json()
    assert json.loads(body["json_text"])["meta"]["id"] == "serial-line"
    assert "factory" in body["mir_text"]


def test_synth_unknown_generator(client: TestClient) -> None:
    response = client.post("/api/synth", json={"generator": "nope"})
    assert response.status_code == 400
    assert response.json()["kind"] == "invocation"


def test_validate_valid(client: TestClient) -> None:
    response = client.post("/api/validate", json={"source": MIR_SOURCE})
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_validate_semantic_invalid_returns_200(client: TestClient) -> None:
    response = client.post("/api/validate", json={"source": invalid_json_source()})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["diagnostics"]


def test_validate_parse_error(client: TestClient) -> None:
    response = client.post(
        "/api/validate", json={"source": {"format": "mir", "text": "factory {{{"}}
    )
    assert response.status_code == 400
    assert response.json()["kind"] == "parse"


def test_fmt_json(client: TestClient) -> None:
    response = client.post("/api/fmt", json={"source": JSON_SOURCE})
    assert response.status_code == 200
    body = response.json()
    assert body["changed"] == (body["canonical"] != UNBALANCED_JSON)
    again = client.post(
        "/api/fmt", json={"source": {"format": "json", "text": body["canonical"]}}
    )
    assert again.json() == {"canonical": body["canonical"], "changed": False}


def test_fmt_mir(client: TestClient) -> None:
    response = client.post("/api/fmt", json={"source": MIR_SOURCE})
    assert response.status_code == 200
    body = response.json()
    assert "factory" in body["canonical"]


def test_compile_and_decompile(client: TestClient) -> None:
    compiled = client.post("/api/compile", json={"text": LINE_MIR})
    assert compiled.status_code == 200
    json_text = compiled.json()["json_text"]
    assert json.loads(json_text)["schema_version"]
    decompiled = client.post("/api/decompile", json={"text": json_text})
    assert decompiled.status_code == 200
    assert "factory" in decompiled.json()["mir_text"]


def test_compile_parse_error(client: TestClient) -> None:
    response = client.post("/api/compile", json={"text": "not a mir document"})
    assert response.status_code == 400
    assert response.json()["kind"] == "parse"


def test_decompile_parse_error(client: TestClient) -> None:
    response = client.post("/api/decompile", json={"text": "{not json"})
    assert response.status_code == 400
    assert response.json()["kind"] == "parse"


def test_analyze(client: TestClient) -> None:
    response = client.post("/api/analyze", json={"source": JSON_SOURCE})
    assert response.status_code == 200
    body = response.json()
    assert "diagnostics" in body
    assert "topology" in body["analysis"]
    assert "capacity" in body["analysis"]


def test_simulate(client: TestClient) -> None:
    response = client.post(
        "/api/simulate", json={"source": MIR_SOURCE, "scenario": FAST_SCENARIO}
    )
    assert response.status_code == 200
    body = response.json()
    assert "summary" in body
    repeat = client.post(
        "/api/simulate", json={"source": MIR_SOURCE, "scenario": FAST_SCENARIO}
    )
    assert repeat.json() == body


def test_simulate_semantic_invalid_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/simulate", json={"source": invalid_json_source(), "scenario": FAST_SCENARIO}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["kind"] == "semantic"
    assert body["error"] == "invalid factory"
    assert body["diagnostics"]


def test_simulate_warmup_ge_horizon(client: TestClient) -> None:
    response = client.post(
        "/api/simulate",
        json={"source": MIR_SOURCE, "scenario": {"horizon_h": 1.0, "warmup_h": 1.0}},
    )
    assert response.status_code == 400
    assert response.json()["kind"] == "invocation"


def test_sweep(client: TestClient) -> None:
    response = client.post(
        "/api/sweep",
        json={
            "source": MIR_SOURCE,
            "space": SWEEP_SPACE,
            "scenario": FAST_SCENARIO,
            "workers": 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["points"]


def test_recommend(client: TestClient) -> None:
    response = client.post(
        "/api/recommend",
        json={
            "source": MIR_SOURCE,
            "space": SWEEP_SPACE,
            "scenario": FAST_SCENARIO,
            "workers": 1,
            "objective": "throughput",
            "top_k": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"]
    assert body["recommendations"][0]["rank"] == 1


def test_sensitivity(client: TestClient) -> None:
    response = client.post(
        "/api/sensitivity",
        json={"source": MIR_SOURCE, "scenario": FAST_SCENARIO, "percent": 10.0},
    )
    assert response.status_code == 200
    assert "entries" in response.json()


def test_report(client: TestClient) -> None:
    response = client.post(
        "/api/report", json={"source": MIR_SOURCE, "scenario": FAST_SCENARIO}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.lower().startswith("<!doctype html>")


def test_report_compare(client: TestClient) -> None:
    response = client.post(
        "/api/report/compare",
        json={"baseline": MIR_SOURCE, "variant": JSON_SOURCE, "scenario": FAST_SCENARIO},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.lower().startswith("<!doctype html>")


def test_compare(client: TestClient) -> None:
    response = client.post(
        "/api/compare",
        json={"baseline": MIR_SOURCE, "variant": JSON_SOURCE, "scenario": FAST_SCENARIO},
    )
    assert response.status_code == 200
    body = response.json()
    assert "baseline_id" in body
    assert "variant_id" in body


def test_emit(client: TestClient) -> None:
    response = client.post("/api/emit", json={"source": MIR_SOURCE, "backend": "st"})
    assert response.status_code == 200
    body = response.json()
    assert "manifest.json" in body["files"]
    assert body["manifest"] == json.loads(body["files"]["manifest.json"])


def test_emit_unknown_backend(client: TestClient) -> None:
    response = client.post("/api/emit", json={"source": MIR_SOURCE, "backend": "nope"})
    assert response.status_code == 400
    assert response.json()["kind"] == "invocation"


def test_emit_zip(client: TestClient) -> None:
    response = client.post("/api/emit/zip", json={"source": MIR_SOURCE, "backend": "st"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "manifest.json" in names
        json.loads(archive.read("manifest.json"))


def test_static_index_fallback(client: TestClient) -> None:
    for path in ("/", "/some/spa/route"):
        response = client.get(path)
        assert response.status_code == 200
        assert "MIR Workbench UI goes here" in response.text


def test_unmatched_api_returns_404(client: TestClient) -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404
