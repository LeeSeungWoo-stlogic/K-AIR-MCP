from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import Context, FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import catalog_client, sources_client, tools
from .auth import api_key_from_headers, key_ok
from .cli import parse_args
from .gateway import health_path
from .credentials import LOCAL_SCOPE, ScopedCredentials, scope_for_api_key
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


def _caller_scope(ctx: Context | None) -> str:
    """계정 범위. HTTP 는 인증된 API Key 의 해시, stdio 는 로컬 한 사용자."""
    request = None
    if ctx is not None:
        try:
            request = ctx.request_context.request
        except ValueError:
            request = None
    if request is None:
        if RT.transport == "http":
            raise tools.QueryError("호출자 API Key 를 확인할 수 없어 계정 범위를 열지 않습니다.")
        return LOCAL_SCOPE
    provided = api_key_from_headers(request.headers)
    if not provided:
        raise tools.QueryError("호출자 API Key 를 확인할 수 없어 계정 범위를 열지 않습니다.")
    return scope_for_api_key(provided)


def _store(ctx: Context | None = None) -> ScopedCredentials:
    return RT.credentials.scoped(_caller_scope(ctx))


@mcp.tool()
async def list_sources(ctx: Context) -> dict:
    """카탈로그 소스·스키마와 data-fabric 접속 좌표(host/port/db). 비밀번호는 없다."""
    return await tools.list_sources(_runtime(), _store(ctx))


@mcp.tool()
async def set_credentials(source_name: str, user: str, password: str, ctx: Context) -> dict:
    """직조회(PG/Tibero) 계정. 이 API Key 범위에만 두고 MCP_CREDENTIALS_TTL_S 뒤 만료된다. 서버 공통 계정은 운영자가 MCP_DS_USER_<소스>/MCP_DS_PASSWORD_<소스> 에 둔다. 비밀번호는 결과에 넣지 않는다."""
    return await tools.set_credentials(_runtime(), _store(ctx), source_name, user, password)


@mcp.tool()
async def clear_credentials(ctx: Context, source_name: str | None = None) -> dict:
    """이 API Key 범위에 넣어 둔 계정을 지운다. source_name 이 없으면 이 범위 전부. env 기본값은 남는다."""
    return await tools.clear_credentials(_store(ctx), source_name)


@mcp.tool()
async def list_tables(schema_name: str | None = None) -> dict:
    """카탈로그의 Postgres·Tibero 표 이름 목록. 컬럼은 describe_table. schema_name 으로 걸 수 있다."""
    return await tools.list_tables(_runtime(), schema_name=schema_name)


@mcp.tool()
async def list_join_hints(source_name: str, schema_name: str, table_name: str) -> dict:
    """한 표의 /meta/ref FK만 모은다. infer-FK 는 만들지 않는다. 표 키가 필요하다."""
    return await tools.list_join_hints(
        _runtime(),
        {"source_name": source_name, "schema_name": schema_name, "table_name": table_name},
    )


@mcp.tool()
async def describe_table(source_name: str, schema_name: str, table_name: str) -> dict:
    """허용된 표의 논리명·컬럼 타입·PK·코멘트. 컬럼은 POST /meta/table."""
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
    ctx: Context | None = None,
) -> dict:
    """허용된 컬럼의 고유값. stone-meta-api /query_execute 로 조회한다."""
    return await tools.get_distinct_values(
        _runtime(),
        _store(ctx),
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
    ctx: Context | None = None,
) -> dict:
    """허용된 한 표에서 조립한 SELECT를 stone-meta-api /query_execute (MindsDB) 로 실행한다."""
    return await tools.query_table(
        _runtime(),
        _store(ctx),
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
    ctx: Context | None = None,
) -> dict:
    """허용된 한 표에서 조립한 SELECT를 원천 Postgres에 직접 실행한다. set_credentials 필요. INSERT/UPDATE/DDL 없음."""
    return await tools.query_table_pg(
        _runtime(),
        _store(ctx),
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
    ctx: Context | None = None,
) -> dict:
    """허용된 Tibero 한 표에서 조립한 SELECT를 JDBC로 직접 실행한다. set_credentials 필요. INSERT/UPDATE/DDL 없음."""
    return await tools.query_table_tibero(
        _runtime(),
        _store(ctx),
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
    ctx: Context | None = None,
) -> dict:
    """허용된 한 표에서 count/sum/avg/max/min 을 조립해 /query_execute 로 실행한다."""
    return await tools.aggregate_table(
        _runtime(),
        _store(ctx),
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
    ctx: Context | None = None,
) -> dict:
    """허용된 한 표에서 count/sum/avg/max/min 을 조립해 원천 Postgres에 직접 실행한다. set_credentials 필요. MindsDB를 거치지 않는다."""
    return await tools.aggregate_table_pg(
        _runtime(),
        _store(ctx),
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
    ctx: Context | None = None,
) -> dict:
    """허용된 Tibero 한 표에서 count/sum/avg/max/min 을 조립해 JDBC로 직접 실행한다. set_credentials 필요."""
    return await tools.aggregate_table_tibero(
        _runtime(),
        _store(ctx),
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
    ctx: Context | None = None,
) -> dict:
    """두 표를 각 경로로 조회한 뒤 MCP에서 붙인다. 엔진에 JOIN SQL을 보내지 않는다. via는 mindsdb, pg, tibero."""
    return await tools.join_tables(
        _runtime(),
        _store(ctx),
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


READY_PROBE_TIMEOUT_S = 3.0


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> Response:
    """생존 확인. 의존 서비스를 부르지 않는다. Docker healthcheck 가 이 경로를 친다."""
    return JSONResponse(
        {
            "status": "ok",
            "server": "kair-mcp-analyze",
            "transport": "streamable-http",
            "ready": "/health/ready",
        }
    )


async def _probe(coro) -> str:
    try:
        return await asyncio.wait_for(coro, timeout=READY_PROBE_TIMEOUT_S + 0.5)
    except (asyncio.TimeoutError, TimeoutError):
        return "timeout"
    except Exception:  # noqa: BLE001 - 준비 확인은 어떤 실패든 상태 문자열로만 알린다
        return "unreachable"


@mcp.custom_route("/health/ready", methods=["GET"])
async def health_ready(_request: Request) -> Response:
    """준비 확인. 의존 서비스를 동시에 짧게(각 3초 이하) 본다.

    필수(stone-meta /health)가 안 되면 503. 선택(nk-backend datasources, 직조회용)만 안 되면 200 degraded.
    """
    settings = RT.settings
    if settings is None:
        return JSONResponse({"status": "unavailable", "server": "kair-mcp-analyze", "deps": {}}, status_code=503)
    stone_meta, nk_datasources = await asyncio.gather(
        _probe(catalog_client.probe_catalog(settings.stone_meta_url, timeout_s=READY_PROBE_TIMEOUT_S)),
        _probe(
            sources_client.probe_sources(
                settings.nk_backend_url,
                settings.nk_backend_token,
                timeout_s=READY_PROBE_TIMEOUT_S,
            )
        ),
    )
    deps = {
        "stone_meta": {"status": stone_meta, "required": True, "used_by": "/meta/catalog, /query_execute"},
        "nk_datasources": {"status": nk_datasources, "required": False, "used_by": "PG/Tibero 직조회"},
    }
    required_down = any(d["required"] and d["status"] != "ok" for d in deps.values())
    optional_down = any(not d["required"] and d["status"] != "ok" for d in deps.values())
    status = "unavailable" if required_down else ("degraded" if optional_down else "ok")
    return JSONResponse(
        {"status": status, "server": "kair-mcp-analyze", "deps": deps},
        status_code=503 if required_down else 200,
    )


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if health_path(request.url.path):
            return await call_next(request)
        provided = api_key_from_headers(request.headers)
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
    RT.credentials.set_ttl(settings.credentials_ttl_s)
    seeded = RT.credentials.load_environ()
    log.info(
        "mcp ready stone=%s nk=%s env_credentials=%s",
        settings.stone_meta_url,
        settings.nk_backend_url,
        ",".join(seeded) or "none",
    )


async def serve_http() -> None:
    RT.transport = "http"
    await _open_runtime()
    try:
        app = mcp.streamable_http_app()
        app.add_middleware(ApiKeyMiddleware)
        config = uvicorn.Config(app, host=mcp.settings.host, port=mcp.settings.port, log_level="info")
        await uvicorn.Server(config).serve()
    finally:
        RT.settings = None
        RT.credentials.clear_all()


async def serve_stdio() -> None:
    RT.transport = "stdio"
    await _open_runtime()
    try:
        await mcp.run_stdio_async()
    finally:
        RT.settings = None
        RT.credentials.clear_all()


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    log.info("transport=%s", args.transport)
    if args.transport == "stdio":
        asyncio.run(serve_stdio())
        return
    asyncio.run(serve_http())


if __name__ == "__main__":
    run()
