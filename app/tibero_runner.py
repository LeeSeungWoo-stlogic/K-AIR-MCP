from __future__ import annotations

import asyncio
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from .sources_client import SourceEndpoint

TIBERO_DRIVER_CLASS = "com.tmax.tibero.jdbc.TbDriver"
DEFAULT_JAR = "/opt/tibero/jdbc/tibero-jdbc.jar"
_SAFE_HOST = re.compile(r"^[A-Za-z0-9._:-]+$")
_SAFE_SID = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")


class QueryRunError(RuntimeError):
    pass


def jdbc_url(endpoint: SourceEndpoint) -> str:
    host = (endpoint.host or "").strip()
    if not _SAFE_HOST.fullmatch(host) or any(ch in host for ch in "@/;"):
        raise QueryRunError(f"Tibero host 가 올바르지 않습니다: {host!r}")
    if endpoint.port < 1 or endpoint.port > 65535:
        raise QueryRunError("Tibero port 가 올바르지 않습니다.")
    sid = (endpoint.database or "").strip()
    if not _SAFE_SID.fullmatch(sid):
        raise QueryRunError(f"Tibero SID 가 올바르지 않습니다: {sid!r}")
    return f"jdbc:tibero:thin:@{host}:{int(endpoint.port)}:{sid}"


def jdbc_jar_path(explicit: str | None = None) -> str:
    candidate = (explicit or os.environ.get("TIBERO_JDBC_JAR") or DEFAULT_JAR).strip()
    path = Path(candidate)
    if not path.is_file():
        raise QueryRunError(
            f"Tibero JDBC JAR 이 없습니다: {path}. TIBERO_JDBC_JAR 로 마운트 경로를 지정하세요."
        )
    return str(path)


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


def _fetch_sync(
    endpoint: SourceEndpoint,
    *,
    user: str,
    password: str,
    sql: str,
    params: tuple[Any, ...],
    max_rows: int,
    jar_path: str,
) -> list[dict[str, Any]]:
    try:
        import jaydebeapi
    except ImportError as exc:
        raise QueryRunError("JayDeBeApi 가 필요합니다. Tibero JDBC 직조회용입니다.") from exc
    connection = None
    cursor = None
    try:
        connection = jaydebeapi.connect(
            TIBERO_DRIVER_CLASS,
            jdbc_url(endpoint),
            [user, password],
            jar_path,
        )
        cursor = connection.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        description = cursor.description or []
        names = [str(col[0]) for col in description]
        rows: list[dict[str, Any]] = []
        cap = max(1, int(max_rows))
        for raw in cursor.fetchmany(cap) or []:
            if isinstance(raw, dict):
                rows.append({str(key): _jsonable(value) for key, value in raw.items()})
                continue
            values = list(raw)
            rows.append({names[i]: _jsonable(values[i]) for i in range(min(len(names), len(values)))})
        return rows
    except QueryRunError:
        raise
    except Exception as exc:  # noqa: BLE001 - JDBC 예외 종류가 드라이버마다 다름
        raise QueryRunError(f"원천 Tibero 조회에 실패했습니다: {exc}") from exc
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


async def fetch_all(
    endpoint: SourceEndpoint,
    *,
    user: str,
    password: str,
    sql: str,
    params: tuple[Any, ...] = (),
    max_rows: int,
    jar_path: str | None = None,
) -> list[dict[str, Any]]:
    resolved = jdbc_jar_path(jar_path)
    return await asyncio.to_thread(
        _fetch_sync,
        endpoint,
        user=user,
        password=password,
        sql=sql,
        params=params,
        max_rows=max_rows,
        jar_path=resolved,
    )
