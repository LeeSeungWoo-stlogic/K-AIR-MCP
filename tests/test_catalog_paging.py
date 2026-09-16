import asyncio

import httpx

from app import catalog_client
from app.intersect import catalog_tables, find_table


def test_catalog_tables_keep_name_only_rows():
    catalog = {
        "sources": [
            {
                "source_name": "RWIS",
                "engine": "postgres",
                "source_schema": "rwis",
                "tables": [
                    {"table_name": "rditag_tb", "schema_name": "rwis", "columns": []},
                    {
                        "table_name": "dim_tag",
                        "schema_name": "rwis_mart",
                        "columns": [{"column_name": "tag_id"}],
                    },
                ],
            }
        ]
    }
    allowed = catalog_tables(catalog)
    assert find_table(allowed, "RWIS", "rwis", "rditag_tb") is not None
    assert find_table(allowed, "RWIS", "rwis", "rditag_tb").columns == ()
    assert find_table(allowed, "RWIS", "rwis_mart", "dim_tag") is not None


class _PageClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None):
        body = json or {}
        if url.endswith("/meta/catalog"):
            cursor = body.get("cursor")
            if not cursor:
                payload = {
                    "serving_status": "active",
                    "truncated": True,
                    "next_cursor": "page-2",
                    "sources": [
                        {
                            "source_name": "RWIS",
                            "engine": "postgres",
                            "source_schema": "rwis",
                            "registered_at": "2026-01-01T00:00:00+09:00",
                            "tables": [{"table_name": "t001", "schema_name": "rwis", "columns": []}],
                        }
                    ],
                }
            else:
                payload = {
                    "serving_status": "active",
                    "truncated": False,
                    "next_cursor": None,
                    "sources": [
                        {
                            "source_name": "RWIS",
                            "engine": "postgres",
                            "source_schema": "rwis",
                            "registered_at": "2026-01-01T00:00:00+09:00",
                            "tables": [{"table_name": "t002", "schema_name": "rwis", "columns": []}],
                        }
                    ],
                }
            return _Json(200, payload)
        raise AssertionError(url)


class _Json:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_catalog_walks_pages(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _PageClient)
    out = asyncio.run(catalog_client.fetch_catalog("http://stone-meta-api:8096"))
    names = [t["table_name"] for s in out["sources"] for t in s["tables"]]
    assert names == ["t001", "t002"]
    assert out["serving_status"] == "active"


class _TableClient:
    seen: list[tuple[str, dict | None]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None):
        type(self).seen.append((url, json))
        if url.endswith("/meta/table"):
            return _Json(
                200,
                {
                    "table_info": {"table_name_kr": "태그", "description": "태그 정의"},
                    "columns": [
                        {
                            "column_name": "TAGSN",
                            "data_type": "varchar",
                            "is_null": False,
                            "constraints": ["PK"],
                            "column_name_kr": "태그번호",
                            "column_comment": "태그",
                        }
                    ],
                    "fk": [
                        {
                            "column_name": "TAGSN",
                            "ref_schema_name": "rwis",
                            "ref_table_name": "rdisaup_tb",
                            "ref_column_name": "tagsn",
                            "position": 1,
                        }
                    ],
                },
            )
        raise AssertionError(url)


def test_fetch_table_posts_serving_scope(monkeypatch):
    _TableClient.seen = []
    monkeypatch.setattr(httpx, "AsyncClient", _TableClient)
    out = asyncio.run(
        catalog_client.fetch_table(
            "http://stone-meta-api:8096",
            source_name="RWIS",
            schema_name="rwis",
            table_name="rditag_tb",
        )
    )
    assert out["columns"][0]["column_name"] == "TAGSN"
    assert _TableClient.seen[0][1]["scope"] == "serving"
