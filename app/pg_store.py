from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


def _cell(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, memoryview):
        return bytes(value).hex()
    if isinstance(value, bytes):
        return value.hex()
    return value

_TABLES_SQL = """
SELECT n.nspname AS schema_name, c.relname AS table_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'v', 'm', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
"""

_COLUMNS_SQL = """
SELECT n.nspname AS schema_name, c.relname AS table_name, a.attname AS column_name
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'v', 'm', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp%'
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY n.nspname, c.relname, a.attnum
"""


async def list_pg_inventory(
    pool: AsyncConnectionPool,
) -> tuple[set[tuple[str, str]], dict[tuple[str, str], tuple[str, ...]]]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        tables = await conn.execute(_TABLES_SQL)
        table_rows = await tables.fetchall()
        columns = await conn.execute(_COLUMNS_SQL)
        column_rows = await columns.fetchall()

    pg_tables = {(row["schema_name"], row["table_name"]) for row in table_rows}
    pg_columns: dict[tuple[str, str], list[str]] = {}
    for row in column_rows:
        pg_columns.setdefault((row["schema_name"], row["table_name"]), []).append(row["column_name"])
    return pg_tables, {key: tuple(vals) for key, vals in pg_columns.items()}


_COMMENTS_SQL = """
SELECT a.attname AS column_name, col_description(c.oid, a.attnum) AS comment
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relname = %s
  AND a.attnum > 0 AND NOT a.attisdropped
"""


async def fetch_rows(
    pool: AsyncConnectionPool,
    sql: str,
    params: tuple = (),
) -> list[dict]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        result = await conn.execute(sql, params)
        rows = await result.fetchall()
    return [{key: _cell(val) for key, val in dict(row).items()} for row in rows]


async def column_comments(
    pool: AsyncConnectionPool,
    schema: str,
    table: str,
) -> dict[str, str]:
    async with pool.connection() as conn:
        conn.row_factory = dict_row
        result = await conn.execute(_COMMENTS_SQL, (schema, table))
        rows = await result.fetchall()
    return {
        str(row["column_name"]): str(row["comment"])
        for row in rows
        if row.get("comment")
    }
