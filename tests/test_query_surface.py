import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import catalog_client, tools
from app.catalog_client import CatalogError
from app.main import health
from app.runtime import RT
from app.settings import Settings

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "catalog_serving.json"


def _settings() -> Settings:
    return Settings(
        api_keys=("k",),
        robo_meta_url="http://robo-meta-api:8100",
        row_limit=200,
        api_host="0.0.0.0",
        api_port=8110,
    )


def _serving_catalog() -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["sources"][0]["tables"][0]["logical_name"]
    return payload


def test_serving_fixture_has_logical_name():
    table = _serving_catalog()["sources"][0]["tables"][0]
    assert table["logical_name"] == "일 계측 팩트"
    assert table["columns"][0]["logical_name"] == "집계일"


def test_list_tables_exposes_catalog_logical_name():
    catalog = _serving_catalog()

    async def fake_catalog(_url: str) -> dict:
        return catalog

    async def run():
        with patch("app.tools.catalog_client.fetch_catalog", fake_catalog):
            result = await tools.list_tables(_settings())
        item = result["items"][0]
        assert item["table_name"] == "fct_measure_day"
        assert item["table_logical_name"] == "일 계측 팩트"
        assert item["description"] == "태그별 일 집계값"

    asyncio.run(run())


def test_describe_table_fetches_catalog_once_and_exposes_labels():
    catalog = _serving_catalog()
    calls = {"n": 0}

    async def fake_catalog(_url: str) -> dict:
        calls["n"] += 1
        return catalog

    async def run():
        with patch("app.tools.catalog_client.fetch_catalog", fake_catalog):
            result = await tools.describe_table(
                _settings(),
                {
                    "source_name": "rwis_mart",
                    "schema_name": "rwis_mart",
                    "table_name": "fct_measure_day",
                },
            )
        assert calls["n"] == 1
        assert result["logical_name"] == "일 계측 팩트"
        assert result["description"] == "태그별 일 집계값"
        by_name = {col["column_name"]: col for col in result["columns"]}
        assert by_name["measure_date"]["logical_name"] == "집계일"
        assert by_name["measure_date"]["comment"] == "집계일"

    asyncio.run(run())


def test_catalog_http_failure_is_korean_query_error():
    async def boom(_url: str) -> dict:
        raise CatalogError("catalog HTTP 503")

    async def run():
        with patch("app.tools.catalog_client.fetch_catalog", boom):
            try:
                await tools.list_tables(_settings())
            except tools.QueryError as exc:
                assert str(exc) == tools.CATALOG_UNREACHABLE
                return
        raise AssertionError("expected QueryError")

    asyncio.run(run())


def test_fetch_catalog_reuses_ttl_cache():
    catalog_client.clear_cache()
    calls = {"n": 0}

    async def fake_http(_url: str, _timeout: float) -> dict:
        calls["n"] += 1
        return _serving_catalog()

    async def run():
        with patch("app.catalog_client._http_fetch", fake_http):
            first = await catalog_client.fetch_catalog("http://robo-meta-api:8100")
            second = await catalog_client.fetch_catalog("http://robo-meta-api:8100/")
        assert first["sources"][0]["tables"][0]["logical_name"]
        assert second is first
        assert calls["n"] == 1

    asyncio.run(run())
    catalog_client.clear_cache()


def test_health_reports_robo_catalog_unreachable():
    async def run():
        RT.settings = _settings()
        try:
            with patch("app.catalog_client.probe_catalog", AsyncMock(return_value="unreachable")):
                response = await health(None)
            body = json.loads(response.body)
            assert body["status"] == "ok"
            assert body["robo_catalog"] == "unreachable"
            assert "engines" not in body
        finally:
            RT.settings = None

    asyncio.run(run())
