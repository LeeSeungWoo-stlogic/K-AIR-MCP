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
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError) as exc:
        raise QueryRunError(f"원천 Postgres에 연결하지 못했습니다: {exc}") from exc
    try:
        # 조립 SELECT 만 보내지만 계정 권한과 무관하게 세션·트랜잭션을 읽기 전용으로 연다.
        await connection.execute(
            f"SET statement_timeout = {int(statement_timeout_ms)}; "
            "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
        )
        async with connection.transaction(readonly=True):
            rows = await connection.fetch(sql, *params)
    except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
        raise QueryRunError(f"쿼리 실행에 실패했습니다: {exc}") from exc
    except (asyncpg.InterfaceError, ValueError, TypeError) as exc:
        # asyncpg.DataError(값 인코딩 실패)는 PostgresError 가 아니라 InterfaceError 계열이다.
        raise QueryRunError(f"조회 값이 컬럼 형과 맞지 않습니다: {exc}") from exc
    finally:
        await connection.close()
    return [_row_dict(row) for row in rows[: max(1, int(max_rows))]]
