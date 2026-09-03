import asyncio
from unittest.mock import patch

from app import tools
from app.settings import Settings


def _settings() -> Settings:
    return Settings(
        api_keys=("test-key",),
        robo_meta_url="http://robo-meta-api:8100",
        row_limit=200,
        api_host="0.0.0.0",
        api_port=8110,
    )


def test_multi_source_and_multi_db_catalog_serving():
    """Verify that multiple data sources and different databases/engines in catalog
    are all correctly served without needing direct physical DB connections."""
    catalog = {
        "sources": [
            {
                "source_name": "mart_pg",
                "engine": "postgresql",
                "source_schema": "mart_rwis",
                "tables": [
                    {
                        "table_name": "dim_tag",
                        "columns": [
                            {"column_name": "tagsn", "data_type": "integer", "primary_key": True, "comment": "태그일련번호"},
                            {"column_name": "tag_name", "data_type": "varchar", "comment": "태그명"},
                        ],
                    }
                ],
            },
            {
                "source_name": "another_pg_db",
                "engine": "postgresql",
                "source_schema": "public",
                "tables": [
                    {
                        "table_name": "external_table",
                        "columns": [
                            {"column_name": "id", "data_type": "integer", "primary_key": True, "comment": "식별자"},
                        ],
                    }
                ],
            },
            {
                "source_name": "wims_tb",
                "engine": "tibero",
                "source_schema": "WIMS",
                "tables": [
                    {
                        "table_name": "wims_raw",
                        "columns": [
                            {"column_name": "obs_cd", "data_type": "varchar", "primary_key": True, "description": "관측소코드"},
                        ],
                    }
                ],
            },
        ]
    }

    async def fake_catalog(_url: str) -> dict:
        return catalog

    async def run():
        with patch("app.tools.catalog_client.fetch_catalog", fake_catalog):
            res = await tools.list_tables(_settings())
            assert res["total"] == 3
            table_names = [item["table_name"] for item in res["items"]]
            assert "dim_tag" in table_names
            assert "external_table" in table_names
            assert "wims_raw" in table_names

            # Test describe_table on another_pg_db
            desc_another = await tools.describe_table(
                _settings(),
                {"source_name": "another_pg_db", "schema_name": "public", "table_name": "external_table"},
            )
            assert desc_another["columns"][0]["column_name"] == "id"
            assert desc_another["columns"][0]["comment"] == "식별자"

            # Test describe_table on wims_tb (Tibero)
            desc_tb = await tools.describe_table(
                _settings(),
                {"source_name": "wims_tb", "schema_name": "WIMS", "table_name": "wims_raw"},
            )
            assert desc_tb["columns"][0]["column_name"] == "obs_cd"
            assert desc_tb["columns"][0]["comment"] == "관측소코드"

    asyncio.run(run())
