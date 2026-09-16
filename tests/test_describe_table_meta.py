import asyncio

from app import tools
from app.settings import Settings


def _settings() -> Settings:
    return Settings(
        api_keys=("x",),
        stone_meta_url="http://stone-meta-api:8096",
        robo_meta_url="http://stone-meta-api:8096",
        nk_backend_url="http://nk-backend:8000",
        nk_backend_token="",
    )


def test_describe_table_uses_meta_table(monkeypatch):
    async def fake_catalog(_url):
        return {
            "sources": [
                {
                    "source_name": "RWIS",
                    "engine": "postgres",
                    "tables": [
                        {"schema_name": "rwis", "table_name": "rditag_tb", "columns": []}
                    ],
                }
            ]
        }

    async def fake_table(_url, **kwargs):
        assert kwargs["table_name"] == "rditag_tb"
        return {
            "table_info": {"table_name_kr": "태그정의", "description": "태그"},
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
            "fk": [],
        }

    monkeypatch.setattr(tools.catalog_client, "fetch_catalog", fake_catalog)
    monkeypatch.setattr(tools.catalog_client, "fetch_table", fake_table)
    out = asyncio.run(
        tools.describe_table(
            _settings(),
            {"source_name": "RWIS", "schema_name": "rwis", "table_name": "rditag_tb"},
        )
    )
    assert out["columns"][0]["column_name"] == "TAGSN"
    assert out["columns"][0]["primary_key"] is True
    assert out["logical_name"] == "태그정의"


def test_list_join_hints_uses_one_table_ref(monkeypatch):
    async def fake_catalog(_url):
        return {
            "sources": [
                {
                    "source_name": "RWIS",
                    "engine": "postgres",
                    "tables": [
                        {"schema_name": "rwis", "table_name": "rditag_tb", "columns": []}
                    ],
                }
            ]
        }

    async def fake_refs(_url, **kwargs):
        assert kwargs["table_name"] == "rditag_tb"
        return [
            {
                "column_name": "TAGSN",
                "ref_schema_name": "rwis",
                "ref_table_name": "rdisaup_tb",
                "ref_column_name": "tagsn",
                "position": 1,
            }
        ]

    monkeypatch.setattr(tools.catalog_client, "fetch_catalog", fake_catalog)
    monkeypatch.setattr(tools.catalog_client, "fetch_refs", fake_refs)
    out = asyncio.run(
        tools.list_join_hints(
            _settings(),
            {"source_name": "RWIS", "schema_name": "rwis", "table_name": "rditag_tb"},
        )
    )
    assert out["total"] == 1
    assert out["items"][0]["via"] == "meta-ref"
    assert out["items"][0]["to"]["table_name"] == "rdisaup_tb"
