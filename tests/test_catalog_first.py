import asyncio
from unittest.mock import patch

from app import intersect, tools
from app.engine import TIBERO
from app.settings import Settings


def _settings() -> Settings:
    return Settings(
        api_keys=("k",),
        pg_host="host.docker.internal",
        pg_port=5434,
        pg_db="",
        pg_user="",
        pg_password="",
        robo_meta_url="http://robo-meta-api:8100",
        row_limit=200,
        api_host="0.0.0.0",
        api_port=8110,
        tb_host="192.168.0.68",
        tb_port=28629,
        tb_sid="tibero",
        tb_user="sys",
        tb_password="x",
        tb_jdbc_jar="/opt/tibero/jdbc/tibero7-jdbc.jar",
    )


def test_load_allowed_reads_catalog_then_only_needed_engine():
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

    async def fake_pg(_pool):
        order.append("postgres")
        return set(), {}

    async def fake_tb(_settings, owners=None):
        order.append("tibero")
        assert owners == {"RWIS"}
        return intersect.EngineInventory(tables={("RWIS", "T")}, columns={("RWIS", "T"): ("A",)})

    async def run():
        with (
            patch("app.tools.catalog_client.fetch_catalog", fake_catalog),
            patch("app.tools.pg_store.list_pg_inventory", fake_pg),
            patch("app.tools.tb_store.list_tb_inventory", fake_tb),
        ):
            allowed = await tools.load_allowed(_settings(), None)
        assert order == ["catalog", "tibero"]
        assert len(allowed) == 1
        assert allowed[0].engine == TIBERO

    asyncio.run(run())
