import asyncio
from unittest.mock import patch

from app import tools
from app.engine import TIBERO
from app.settings import Settings


def _settings() -> Settings:
    return Settings(
        api_keys=("k",),
        robo_meta_url="http://robo-meta-api:8100",
        row_limit=200,
        api_host="0.0.0.0",
        api_port=8110,
    )


def test_load_allowed_reads_catalog_directly():
    order: list[str] = []
    catalog = {
        "sources": [
            {
                "source_name": "rwis",
                "engine": "tibero",
                "source_schema": "RWIS",
                "tables": [{"table_name": "T", "columns": [{"column_name": "A"}]}],
            }
        ]
    }

    async def fake_catalog(_url: str) -> dict:
        order.append("catalog")
        return catalog

    async def run():
        with patch("app.tools.catalog_client.fetch_catalog", fake_catalog):
            allowed = await tools.load_allowed(_settings())
        assert order == ["catalog"]
        assert len(allowed) == 1
        assert allowed[0].engine == TIBERO
        assert allowed[0].table_name == "T"
        assert allowed[0].columns == ("A",)

    asyncio.run(run())
