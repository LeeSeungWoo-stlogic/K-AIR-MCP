from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import catalog_client, execute_client, sources_client, tools
from .auth import key_ok
from .cli import parse_args
from .runtime import RT
from .settings import SettingsError, load_settings

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("kair-mcp-analyze")

mcp = FastMCP(
    name="kair-mcp-analyze",
    instructions=(
        "K-water 데이터허브 조회 MCP. "
        "표 목록은 stone-meta-api POST /meta/catalog. "
        "query_table / aggregate_table / get_distinct_values 는 stone-meta POST /query_execute (MindsDB). "
        "query_table_pg / aggregate_table_pg 는 nk-backend 데이터소스 좌표로 원천 Postgres에 직접 실행. "
        "query_table_tibero / aggregate_table_tibero 는 같은 좌표로 원천 Tibero에 JDBC 직조회. "
        "직조회 전에 set_credentials 가 필요하다. "
        "쓰기는 없고, SELECT 집계(count/sum/avg/max/min)는 된다. "
        "SQL 문자열은 받지 않는다. 한 표 조회는 기존 도구를 쓴다. "
        "여러 표 결과는 join_tables 가 MCP에서 붙인다. MindsDB 조인을 대신하지 않는다. "
        "같은 소스라도 스키마가 다르면 표별로 schema_name 을 쓴다."
    ),
    host=os.environ.get("API_HOST", "0.0.0.0"),
    port=int(os.environ.get("API_PORT", "8111")),
    streamable_http_path="/mcp",
    stateless_http=True,
)


def _runtime():
    if RT.settings is None:
        raise RuntimeError("MCP runtime is not ready")
    return RT.settings


def _store():
    return RT.credentials


@mcp.tool()
async def list_sources() -> dict:
    """카탈로그 소스·스키마와 data-fabric 접속 좌표(host/port/db). 비밀번호는 없다."""
    return await tools.list_sources(_runtime(), _store())


@mcp.tool()
async def set_credentials(source_name: str, user: str, password: str) -> dict:
    """직조회(PG/Tibero) 계정. 재시작 후에도 쓰려면 MCP_DS_USER_<소스>/MCP_DS_PASSWORD_<소스> 에 둔다. 비밀번호는 결과에 넣지 않는다."""
    return await tools.set_credentials(_runtime(), _store(), source_name, user, password)


@mcp.tool()
async def clear_credentials(source_name: str | None = None) -> dict:
    """넣어 둔 계정을 지운다. source_name 이 없으면 전부 지운다."""
    return await tools.clear_credentials(_store(), source_name)


@mcp.tool()
async def list_tables(schema_name: str | None = None) -> dict:
    """카탈로그의 Postgres·Tibero 표 목록. schema_name 으로 걸 수 있다."""
    return await tools.list_tables(_runtime(), schema_name=schema_name)


@mcp.tool()
async def list_join_hints() -> dict:
    """카탈로그 컬럼의 references·referenced_by 만 모은다. infer-FK 는 만들지 않는다."""
    return await tools.list_join_hints(_runtime())


@mcp.tool()
async def describe_table(source_name: str, schema_name: str, table_name: str) -> dict:
    """허용된 표의 논리명·컬럼 타입·PK·코멘트를 준다."""
    return await tools.describe_table(
        _runtime(),
        {"source_name": source_name, "schema_name": schema_name, "table_name": table_name},
    )


@mcp.tool()
async def get_distinct_values(
    source_name: str,
    schema_name: str,
    table_name: str,
    column_name: str,
    limit: int = 50,
) -> dict:
    """허용된 컬럼의 고유값. stone-meta-api /query_execute 로 조회한다."""
    return await tools.get_distinct_values(
        _runtime(),
        _store(),
        {
            "source_name": source_name,
            "schema_name": schema_name,
            "table_name": table_name,
            "column_name": column_name,
            "limit": limit,
        },
    )


@mcp.tool()
async def query_table(
    source_name: str,
    schema_name: str,
    table_name: str,
    columns: list[str] | None = None,
    filters: list[dict] | None = None,
    order_by: list[dict] | None = None,
    limit: int = 50,
) -> dict:
    """허용된 한 표에서 조립한 SELECT를 stone-meta-api /query_execute (MindsDB) 로 실행한다."""
    return await tools.query_table(
        _runtime(),
        _store(),
        {
            "source_name": source_name,
            "schema_name": schema_name,
            "table_name": table_name,
            "columns": columns,
            "filters": filters,
            "order_by": order_by,
            "limit": limit,
        },
    )


@mcp.tool()
async def query_table_pg(
    source_name: str,
    schema_name: str,
    table_name: str,
    columns: list[str] | None = None,
    filters: list[dict] | None = None,
    order_by: list[dict] | None = None,
    limit: int = 50,
) -> dict:
    """허용된 한 표에서 조립한 SELECT를 원천 Postgres에 직접 실행한다. set_credentials 필요. INSERT/UPDATE/DDL 없음."""
    return await tools.query_table_pg(
        _runtime(),
        _store(),
        {
            "source_name": source_name,
            "schema_name": schema_name,
            "table_name": table_name,
            "columns": columns,
            "filters": filters,
            "order_by": order_by,
            "limit": limit,
        },
    )


@mcp.tool()
async def query_table_tibero(
    source_name: str,
    schema_name: str,
    table_name: str,
    columns: list[str] | None = None,
    filters: list[dict] | None = None,
    order_by: list[dict] | None = None,
    limit: int = 50,
) -> dict:
    """허용된 Tibero 한 표에서 조립한 SELECT를 JDBC로 직접 실행한다. set_credentials 필요. INSERT/UPDATE/DDL 없음."""
    return await tools.query_table_tibero(
        _runtime(),
        _store(),
        {
            "source_name": source_name,
            "schema_name": schema_name,
            "table_name": table_name,
            "columns": columns,
            "filters": filters,
            "order_by": order_by,
            "limit": limit,
        },
    )


@mcp.tool()
async def aggregate_table(
    source_name: str,
    schema_name: str,
    table_name: str,
    func: str,
    column: str | None = None,
    group_by: list[str] | None = None,
    filters: list[dict] | None = None,
    limit: int = 50,
) -> dict:
    """허용된 한 표에서 count/sum/avg/max/min 을 조립해 /query_execute 로 실행한다."""
    return await tools.aggregate_table(
        _runtime(),
        _store(),
        {
            "source_name": source_name,
            "schema_name": schema_name,
            "table_name": table_name,
            "func": func,
            "column": column,
            "group_by": group_by,
            "filters": filters,
            "limit": limit,
        },
    )


@mcp.tool()
async def aggregate_table_pg(
    source_name: str,
    schema_name: str,
    table_name: str,
    func: str,
    column: str | None = None,
    group_by: list[str] | None = None,
    filters: list[dict] | None = None,
    limit: int = 50,
) -> dict:
    """허용된 한 표에서 count/sum/avg/max/min 을 조립해 원천 Postgres에 직접 실행한다. set_credentials 필요. MindsDB를 거치지 않는다."""
    return await tools.aggregate_table_pg(
        _runtime(),
        _store(),
        {
            "source_name": source_name,
            "schema_name": schema_name,
            "table_name": table_name,
            "func": func,
            "column": column,
            "group_by": group_by,
            "filters": filters,
            "limit": limit,
        },
    )


@mcp.tool()
async def aggregate_table_tibero(
    source_name: str,
    schema_name: str,
    table_name: str,
    func: str,
    column: str | None = None,
    group_by: list[str] | None = None,
    filters: list[dict] | None = None,
    limit: int = 50,
) -> dict:
    """허용된 Tibero 한 표에서 count/sum/avg/max/min 을 조립해 JDBC로 직접 실행한다. set_credentials 필요."""
    return await tools.aggregate_table_tibero(
        _runtime(),
        _store(),
        {
            "source_name": source_name,
            "schema_name": schema_name,
            "table_name": table_name,
            "func": func,
            "column": column,
            "group_by": group_by,
            "filters": filters,
            "limit": limit,
        },
    )


@mcp.tool()
async def join_tables(
    left_source_name: str,
    left_schema_name: str,
    left_table_name: str,
    left_on: str | list[str],
    right_source_name: str,
    right_schema_name: str,
    right_table_name: str,
    right_on: str | list[str],
    left_via: str = "mindsdb",
    right_via: str = "mindsdb",
    left_columns: list[str] | None = None,
    right_columns: list[str] | None = None,
    left_filters: list[dict] | None = None,
    right_filters: list[dict] | None = None,
    left_limit: int = 50,
    right_limit: int = 50,
    how: str = "inner",
) -> dict:
    """두 표를 각 경로로 조회한 뒤 MCP에서 붙인다. 엔진에 JOIN SQL을 보내지 않는다. via는 mindsdb, pg, tibero."""
    return await tools.join_tables(
        _runtime(),
        _store(),
        {
            "left_source_name": left_source_name,
            "left_schema_name": left_schema_name,
            "left_table_name": left_table_name,
            "left_on": left_on,
            "left_via": left_via,
            "left_columns": left_columns,
            "left_filters": left_filters,
            "left_limit": left_limit,
            "right_source_name": right_source_name,
            "right_schema_name": right_schema_name,
            "right_table_name": right_table_name,
            "right_on": right_on,
            "right_via": right_via,
            "right_columns": right_columns,
            "right_filters": right_filters,
            "right_limit": right_limit,
            "how": how,
        },
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> Response:
    stone_catalog = "unreachable"
    stone_execute = "unreachable"
    nk_datasources = "unreachable"
    if RT.settings is not None:
        stone_catalog = await catalog_client.probe_catalog(RT.settings.stone_meta_url)
        stone_execute = await execute_client.probe_execute(RT.settings.stone_meta_url)
        nk_datasources = await sources_client.probe_sources(
            RT.settings.nk_backend_url,
            RT.settings.nk_backend_token,
        )
    return JSONResponse(
        {
            "status": "ok",
            "server": "kair-mcp-analyze",
            "transport": "streamable-http",
            "catalog": "stone-meta-api /meta/catalog",
            "query": "stone-meta-api /query_execute",
            "query_pg": "nk-backend datasources + asyncpg",
            "stone_catalog": stone_catalog,
            "stone_execute": stone_execute,
            "nk_datasources": nk_datasources,
        }
    )


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        provided = (request.headers.get("x-api-key") or "").strip()
        authorization = request.headers.get("authorization") or ""
        if not provided and authorization.lower().startswith("apikey "):
            provided = authorization[7:].strip()
        if not provided and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
        allowed = RT.settings.api_keys if RT.settings else ()
        if not provided or not key_ok(provided, allowed):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def _open_runtime() -> None:
    try:
        settings = load_settings()
    except SettingsError as exc:
        raise SystemExit(str(exc)) from exc
    RT.settings = settings
    seeded = RT.credentials.load_environ()
    log.info(
        "mcp ready stone=%s nk=%s env_credentials=%s",
        settings.stone_meta_url,
        settings.nk_backend_url,
        ",".join(seeded) or "none",
    )


async def serve_http() -> None:
    await _open_runtime()
    try:
        app = mcp.streamable_http_app()
        app.add_middleware(ApiKeyMiddleware)
        config = uvicorn.Config(app, host=mcp.settings.host, port=mcp.settings.port, log_level="info")
        await uvicorn.Server(config).serve()
    finally:
        RT.settings = None
        RT.credentials.clear()


async def serve_stdio() -> None:
    await _open_runtime()
    try:
        await mcp.run_stdio_async()
    finally:
        RT.settings = None
        RT.credentials.clear()


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    log.info("transport=%s", args.transport)
    if args.transport == "stdio":
        asyncio.run(serve_stdio())
        return
    asyncio.run(serve_http())


if __name__ == "__main__":
    run()
