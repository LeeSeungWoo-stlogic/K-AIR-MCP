import asyncio
import json
import time

from app import catalog_client, main, sources_client
from app.gateway import health_path
from app.runtime import RT
from app.settings import Settings


def _settings() -> Settings:
    return Settings(
        api_keys=("x",),
        stone_meta_url="http://stone-meta-api:8096",
        robo_meta_url="http://stone-meta-api:8096",
        nk_backend_url="http://nk-backend:8000",
        nk_backend_token="",
    )


def _body(response) -> dict:
    return json.loads(response.body)


def test_liveness_does_not_touch_dependencies(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("liveness must not probe dependencies")

    monkeypatch.setattr(catalog_client, "probe_catalog", boom)
    monkeypatch.setattr(sources_client, "probe_sources", boom)
    monkeypatch.setattr(RT, "settings", _settings())
    started = time.perf_counter()
    response = asyncio.run(main.health(None))
    assert time.perf_counter() - started < 0.1
    assert response.status_code == 200
    assert _body(response)["status"] == "ok"


def test_ready_ok_and_probes_run_concurrently(monkeypatch):
    seen = {}

    async def slow_ok(*args, **kwargs):
        seen.setdefault("timeouts", []).append(kwargs.get("timeout_s"))
        await asyncio.sleep(0.3)
        return "ok"

    monkeypatch.setattr(catalog_client, "probe_catalog", slow_ok)
    monkeypatch.setattr(sources_client, "probe_sources", slow_ok)
    monkeypatch.setattr(RT, "settings", _settings())
    started = time.perf_counter()
    response = asyncio.run(main.health_ready(None))
    assert time.perf_counter() - started < 0.55
    assert response.status_code == 200
    assert _body(response)["status"] == "ok"
    assert all(t is not None and t <= 3 for t in seen["timeouts"])


def test_ready_503_when_stone_down(monkeypatch):
    async def down(*args, **kwargs):
        return "unreachable"

    async def ok(*args, **kwargs):
        return "ok"

    monkeypatch.setattr(catalog_client, "probe_catalog", down)
    monkeypatch.setattr(sources_client, "probe_sources", ok)
    monkeypatch.setattr(RT, "settings", _settings())
    response = asyncio.run(main.health_ready(None))
    body = _body(response)
    assert response.status_code == 503
    assert body["status"] == "unavailable"
    assert body["deps"]["stone_meta"]["status"] == "unreachable"
    assert body["deps"]["nk_datasources"]["status"] == "ok"


def test_ready_degraded_when_only_optional_down_and_hung_probe_times_out(monkeypatch):
    async def ok(*args, **kwargs):
        return "ok"

    async def hang(*args, **kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(main, "READY_PROBE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(catalog_client, "probe_catalog", ok)
    monkeypatch.setattr(sources_client, "probe_sources", hang)
    monkeypatch.setattr(RT, "settings", _settings())
    response = asyncio.run(main.health_ready(None))
    body = _body(response)
    assert response.status_code == 200
    assert body["status"] == "degraded"
    assert body["deps"]["nk_datasources"]["status"] == "timeout"


def test_ready_path_skips_api_key():
    assert health_path("/health/ready")
    assert not health_path("/health/ready/x")


def test_health_routes_open_without_key_but_mcp_needs_key(monkeypatch):
    from starlette.testclient import TestClient

    async def down(*args, **kwargs):
        return "unreachable"

    monkeypatch.setattr(catalog_client, "probe_catalog", down)
    monkeypatch.setattr(sources_client, "probe_sources", down)
    monkeypatch.setattr(RT, "settings", _settings())
    app = main.mcp.streamable_http_app()
    app.add_middleware(main.ApiKeyMiddleware)
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 503
    assert client.post("/mcp", content="{}").status_code == 401
