from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from .sources_client import SourceEndpoint


class QueryRunError(RuntimeError):
    pass


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def _row_dict(row: asyncpg.Record) -> dict[str, Any]:
    return {key: _jsonable(row[key]) for key in row.keys()}


async def fetch_all(
    endpoint: SourceEndpoint,
    *,
    user: str,
    password: str,
    sql: str,
    params: tuple[Any, ...] = (),
    max_rows: int,
    statement_timeout_ms: int,
) -> list[dict[str, Any]]:
    try:
        connection = await asyncpg.connect(
            host=endpoint.host,
            port=endpoint.port,
            database=endpoint.database,
            user=user,
            password=password,
            timeout=10,
            statement_cache_size=0,
        )
    except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
        raise QueryRunError(f"원천 Postgres에 연결하지 못했습니다: {exc}") from exc
    try:
        await connection.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
        rows = await connection.fetch(sql, *params)
    except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
        raise QueryRunError(f"쿼리 실행에 실패했습니다: {exc}") from exc
    finally:
        await connection.close()
    return [_row_dict(row) for row in rows[: max(1, int(max_rows))]]
