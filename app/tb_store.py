from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .engine import TIBERO
from .intersect import EngineInventory
from .settings import Settings
from . import sqlutil

log = logging.getLogger("kair-mcp-query")

_DRIVER = "com.tmax.tibero.jdbc.TbDriver"
_LOCK = threading.Lock()
_CONN = None


class TiberoError(RuntimeError):
    pass


def is_configured(settings: Settings) -> bool:
    return settings.tb_configured


def _jdbc_url(settings: Settings) -> str:
    return f"jdbc:tibero:thin:@{settings.tb_host}:{settings.tb_port}:{settings.tb_sid}"


def _cell(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "toPlainString"):
        try:
            return str(value.toPlainString())
        except Exception:
            pass
    return str(value)


def _connect(settings: Settings):
    global _CONN
    jar = Path(settings.tb_jdbc_jar)
    if not jar.is_file():
        raise TiberoError("Tibero JDBC JAR가 없습니다")
    import jaydebeapi

    with _LOCK:
        if _CONN is not None:
            try:
                if not _CONN.jconn.isClosed():
                    return _CONN
            except Exception:
                _CONN = None
        _CONN = jaydebeapi.connect(
            _DRIVER,
            _jdbc_url(settings),
            [settings.tb_user, settings.tb_password],
            str(jar),
        )
        return _CONN


def _execute(settings: Settings, sql: str, params: tuple = ()) -> list[dict]:
    if not is_configured(settings):
        raise TiberoError("Tibero 원천이 설정되지 않았습니다")
    jdbc_sql = sql.replace("%s", "?")
    conn = _connect(settings)
    ps = conn.jconn.prepareStatement(jdbc_sql)
    try:
        ps.setQueryTimeout(15)
        for index, value in enumerate(params, start=1):
            if value is None:
                ps.setObject(index, None)
            else:
                ps.setObject(index, value)
        has_result = ps.execute()
        if not has_result:
            return []
        result = ps.getResultSet()
        meta = result.getMetaData()
        columns = [
            str(meta.getColumnLabel(i) or meta.getColumnName(i))
            for i in range(1, meta.getColumnCount() + 1)
        ]
        rows: list[dict] = []
        while result.next():
            row = {}
            for index, name in enumerate(columns, start=1):
                row[name] = _cell(result.getObject(index))
            rows.append(row)
        return rows
    except TiberoError:
        raise
    except Exception as exc:
        raise TiberoError("Tibero 조회에 실패했습니다") from exc
    finally:
        ps.close()


async def list_tb_inventory(settings: Settings, owners: set[str] | None = None) -> EngineInventory:
    if not is_configured(settings):
        return EngineInventory(tables=set(), columns={})
    if not owners:
        return EngineInventory(tables=set(), columns={})

    def _load() -> EngineInventory:
        for owner in owners:
            sqlutil.quote_ident(owner)
        marks = ", ".join("?" for _ in owners)
        column_sql = (
            "SELECT owner AS schema_name, table_name, column_name "
            "FROM all_tab_columns "
            f"WHERE owner IN ({marks}) "
            "ORDER BY owner, table_name, column_id"
        )
        params = tuple(owners)
        rows = _execute(settings, column_sql, params)
        tables: set[tuple[str, str]] = set()
        columns: dict[tuple[str, str], list[str]] = {}
        for row in rows:
            schema = str(row.get("SCHEMA_NAME") or row.get("schema_name") or "")
            table = str(row.get("TABLE_NAME") or row.get("table_name") or "")
            column = str(row.get("COLUMN_NAME") or row.get("column_name") or "")
            if not schema or not table or not column:
                continue
            key = (schema, table)
            tables.add(key)
            bucket = columns.setdefault(key, [])
            if column not in bucket:
                bucket.append(column)
        return EngineInventory(tables=tables, columns={key: tuple(vals) for key, vals in columns.items()})

    inventory = await asyncio.to_thread(_load)
    log.info("tibero inventory tables=%s", len(inventory.tables))
    return inventory


async def fetch_rows(settings: Settings, sql: str, params: tuple = ()) -> list[dict]:
    return await asyncio.to_thread(_execute, settings, sql, params)


async def column_comments(settings: Settings, schema: str, table: str) -> dict[str, str]:
    sqlutil.quote_ident(schema)
    sqlutil.quote_ident(table)

    def _load() -> dict[str, str]:
        rows = _execute(
            settings,
            "SELECT column_name, comments FROM all_col_comments "
            "WHERE owner = ? AND table_name = ?",
            (schema, table),
        )
        out: dict[str, str] = {}
        for row in rows:
            name = str(row.get("COLUMN_NAME") or row.get("column_name") or "")
            comment = row.get("COMMENTS") or row.get("comments")
            if name and comment:
                out[name] = str(comment)
        return out

    return await asyncio.to_thread(_load)


def dialect() -> str:
    return TIBERO
