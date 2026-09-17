import asyncio

import asyncpg
import pytest
from asyncpg.exceptions import _base as asyncpg_base

from app import pg_runner, tools
from app.filters import Filter
from app.settings import Settings
from app.sources_client import SourceEndpoint
from app.sqlutil import assemble_aggregate, assemble_select_bound, pg_bind_type


def test_pg_bind_type_normalizes_meta_types():
    assert pg_bind_type("timestamp(6) without time zone") == "timestamp"
    assert pg_bind_type("TIMESTAMPTZ") == "timestamptz"
    assert pg_bind_type("numeric(10,2)") == "numeric"
    assert pg_bind_type("character varying(20)") == "text"
    assert pg_bind_type("int4") == "integer"
    assert pg_bind_type("geometry") is None
    assert pg_bind_type("date; DROP TABLE x") is None


def test_pg_select_casts_date_and_timestamp_filters():
    sql, params = assemble_select_bound(
        "rwis",
        "obs",
        ["obs_dt", "val"],
        [
            Filter(column="obs_dt", op="gte", value="2026-09-01 00:00:00"),
            Filter(column="obs_day", op="in", value=["2026-09-01", "2026-09-02"]),
            Filter(column="val", op="gt", value=3),
            Filter(column="tag", op="eq", value=1234),
        ],
        [],
        10,
        column_types={
            "obs_dt": "timestamp without time zone",
            "obs_day": "date",
            "val": "numeric",
            "tag": "varchar",
        },
    )
    assert '"obs_dt" >= CAST($1::text AS timestamp)' in sql
    assert '"obs_day" IN (CAST($2::text AS date), CAST($3::text AS date))' in sql
    assert '"val" > CAST($4::text AS numeric)' in sql
    assert '"tag" = $5' in sql
    assert params == ("2026-09-01 00:00:00", "2026-09-01", "2026-09-02", "3", "1234")


def test_unknown_type_binds_value_unchanged_and_tibero_ignores_types():
    sql, params = assemble_aggregate(
        "s", "t", "count", None, [], 1, [Filter(column="g", op="eq", value=5)], column_types={"g": "geometry"}
    )
    assert '"g" = $1' in sql and params == (5,)
    sql, params = assemble_select_bound(
        "S", "T", ["D"], [Filter(column="D", op="eq", value="2026-01-01")], [], 5,
        dialect="tibero", column_types={"D": "date"},
    )
    assert "CAST" not in sql and params == ("2026-01-01",)


@pytest.mark.parametrize(
    "error",
    [
        # 0.31 은 인자 인코딩 실패를 exceptions.DataError(PostgresError 계열)로 낸다.
        asyncpg.exceptions.DataError("invalid input for query argument $1: '2026-09-01'"),
        # 클라이언트 쪽 _base.DataError 는 InterfaceError 계열이라 PostgresError 로 안 잡힌다.
        asyncpg_base.DataError("invalid input for query argument $1"),
        asyncpg.InterfaceError("connection is closed"),
    ],
)
def test_pg_runner_turns_client_errors_into_query_error(monkeypatch, error):
    class _Conn:
        async def execute(self, sql):
            return None

        def transaction(self, **kwargs):
            class _Tx:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return False

            return _Tx()

        async def fetch(self, sql, *params):
            raise error

        async def close(self):
            return None

    async def connect(**kwargs):
        return _Conn()

    monkeypatch.setattr(pg_runner.asyncpg, "connect", connect)
    endpoint = SourceEndpoint("S", "S", "postgres", "10.0.0.1", 5432, "db", "s", ("s",), True)
    with pytest.raises(pg_runner.QueryRunError):
        asyncio.run(
            pg_runner.fetch_all(endpoint, user="u", password="p", sql="SELECT 1", max_rows=1, statement_timeout_ms=1000)
        )


def test_query_table_pg_fetches_types_when_catalog_has_columns_only(monkeypatch):
    settings = Settings(
        api_keys=("x",),
        stone_meta_url="http://stone-meta-api:8096",
        robo_meta_url="http://stone-meta-api:8096",
        nk_backend_url="http://nk-backend:8000",
        nk_backend_token="",
    )

    async def fake_catalog(_url):
        return {
            "sources": [
                {
                    "source_name": "RWIS",
                    "engine": "postgres",
                    "tables": [
                        {"schema_name": "rwis", "table_name": "obs", "columns": [{"column_name": "obs_dt"}]}
                    ],
                }
            ]
        }

    async def fake_table(_url, **kwargs):
        return {"columns": [{"column_name": "obs_dt", "data_type": "timestamp"}]}

    seen = {}

    async def fake_execute_pg(_settings, _store, table, sql, params=(), *, max_rows):
        seen["sql"], seen["params"] = sql, params
        return []

    monkeypatch.setattr(tools.catalog_client, "fetch_catalog", fake_catalog)
    monkeypatch.setattr(tools.catalog_client, "fetch_table", fake_table)
    monkeypatch.setattr(tools, "_execute_pg", fake_execute_pg)
    asyncio.run(
        tools.query_table_pg(
            settings,
            None,
            {
                "source_name": "RWIS",
                "schema_name": "rwis",
                "table_name": "obs",
                "filters": [{"column": "obs_dt", "op": "gte", "value": "2026-09-01"}],
            },
        )
    )
    assert "CAST($1::text AS timestamp)" in seen["sql"]
    assert seen["params"] == ("2026-09-01",)
