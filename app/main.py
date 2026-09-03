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

from . import tools
from .auth import key_ok
from .cli import parse_args
from .runtime import RT
from .settings import SettingsError, load_settings

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("kair-mcp-query")

mcp = FastMCP(
    name="kair-mcp-query",
    instructions=(
        "K-water 데이터허브 조회 MCP. robo-meta-api 카탈로그를 기반으로 테이블을 조회하고 "
        "query_execute를 통해 안전하게 데이터를 질의합니다. "
        "행은 query_table, 건수·합·평균은 aggregate_table, 컬럼 상세는 describe_table. "
        "SQL 문자열은 직접 받지 않으며, 안전한 구조화 파라미터로 실행됩니다. "
        "DB 접속 정보는 도구 결과에 노출되지 않습니다."
    ),
    host=os.environ.get("API_HOST", "0.0.0.0"),
    port=int(os.environ.get("API_PORT", "8110")),
    streamable_http_path="/mcp",
    stateless_http=True,
)


def _runtime():
    if RT.settings is None:
        raise RuntimeError("MCP runtime is not ready")
    return RT.settings


@mcp.tool()
async def list_tables(schema_name: str | None = None) -> dict:
    """카탈로그에 등록된 표 목록을 조회한다. schema_name 으로 필터링할 수 있다."""
    settings = _runtime()
    return await tools.list_tables(settings, schema_name=schema_name)


@mcp.tool()
async def describe_table(source_name: str, schema_name: str, table_name: str) -> dict:
    """카탈로그 표의 컬럼 타입·PK·한글 설명을 조회한다."""
    settings = _runtime()
    return await tools.describe_table(
        settings,
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
    """허용된 컬럼의 고유값 목록을 조회한다. 서버가 DISTINCT 쿼리를 조립하여 실행한다."""
    settings = _runtime()
    return await tools.get_distinct_values(
        settings,
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
    """허용된 표에서 서버가 조립한 SELECT만 실행한다. filters/order_by 는 구조화 객체만 허용된다."""
    settings = _runtime()
    return await tools.query_table(
        settings,
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
    """허용된 표에서 count/sum/avg/max/min 집계를 조립하여 실행한다. 전체 행 수는 func=count, column 없음."""
    settings = _runtime()
    return await tools.aggregate_table(
        settings,
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


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> Response:
    return JSONResponse(
        {
            "status": "ok",
            "server": "kair-mcp-query",
            "transport": "streamable-http",
            "backend": "robo-meta-api",
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
    log.info("mcp ready robo=%s", settings.robo_meta_url)


async def serve_http() -> None:
    await _open_runtime()
    try:
        app = mcp.streamable_http_app()
        app.add_middleware(ApiKeyMiddleware)
        config = uvicorn.Config(app, host=mcp.settings.host, port=mcp.settings.port, log_level="info")
        await uvicorn.Server(config).serve()
    finally:
        RT.settings = None


async def serve_stdio() -> None:
    await _open_runtime()
    try:
        await mcp.run_stdio_async()
    finally:
        RT.settings = None


def run(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    log.info("transport=%s", args.transport)
    if args.transport == "stdio":
        asyncio.run(serve_stdio())
        return
    asyncio.run(serve_http())


if __name__ == "__main__":
    run()
