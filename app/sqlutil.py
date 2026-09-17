from __future__ import annotations

import re
from typing import Any

from .errors import IdentError
from .filters import OPS, Filter, Order

_FORBIDDEN = frozenset({'"', "`", "\x00", ";", "\\"})
AGG_FUNCS = frozenset({"count", "sum", "avg", "max", "min"})


def quote_ident(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise IdentError("identifier is required")
    if len(name) > 128:
        raise IdentError("identifier is too long")
    if any(ch in name for ch in _FORBIDDEN) or "." in name:
        raise IdentError("invalid identifier")
    return f'"{name}"'


def quote_tick(name: str) -> str:
    quote_ident(name)
    return f"`{name}`"


def quote_sql_ident(name: str, *, ticks: bool) -> str:
    """MindsDB(MySQL 방언)는 쌍따옴표를 문자열로 본다. 그 경로는 백틱만 쓴다."""
    return quote_tick(name) if ticks else quote_ident(name)


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    if "\x00" in text:
        raise IdentError("filter value 에 NUL 문자는 쓸 수 없다")
    # MindsDB 는 MySQL 방언이라 백슬래시가 이스케이프다. `\'` 가 따옴표를 닫지 못하게 백슬래시를 먼저 두 배로 만든다.
    text = text.replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


TEXT = "text"
_PG_TYPES = {
    "date": "date",
    "timestamp": "timestamp",
    "timestamp without time zone": "timestamp",
    "timestamptz": "timestamptz",
    "timestamp with time zone": "timestamptz",
    "time": "time",
    "time without time zone": "time",
    "smallint": "smallint",
    "int2": "smallint",
    "integer": "integer",
    "int": "integer",
    "int4": "integer",
    "serial": "integer",
    "bigint": "bigint",
    "int8": "bigint",
    "bigserial": "bigint",
    "numeric": "numeric",
    "decimal": "numeric",
    "real": "real",
    "float4": "real",
    "double precision": "double precision",
    "float8": "double precision",
    "float": "double precision",
    "boolean": "boolean",
    "bool": "boolean",
    "uuid": "uuid",
    "text": TEXT,
    "varchar": TEXT,
    "character varying": TEXT,
    "char": TEXT,
    "character": TEXT,
    "bpchar": TEXT,
    "name": TEXT,
    "citext": TEXT,
}


def pg_bind_type(data_type: object) -> str | None:
    """원천 data_type 을 CAST 에 쓸 수 있는 고정 이름으로 줄인다. 모르면 None(형 맞춤 없이 그대로 바인드)."""
    raw = re.sub(r"\(.*?\)", "", str(data_type or "")).strip().lower()
    raw = " ".join(raw.split())
    return _PG_TYPES.get(raw)


def _text_param(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _pg_placeholder(bind_type: str | None, op: str) -> str:
    """JSON 값은 문자열·숫자뿐이라 asyncpg 가 date/timestamp 칸에 str 을 받으면 DataError 를 낸다.

    형을 알면 text 로 바인드하고 서버에서 CAST 한다. 파싱 규칙은 PG 가 정하니 MindsDB 경로 리터럴과 같다.
    """
    if bind_type is None or bind_type == TEXT or op == "like":
        return "%s"
    return f"CAST(%s::text AS {bind_type})"


def _pg_value(bind_type: str | None, value: Any) -> Any:
    if bind_type is None:
        return value
    return _text_param(value)


def from_sql(schema: str, table: str, source: str | None = None) -> str:
    if source:
        return f"{quote_tick(source)}.{quote_tick(schema)}.{quote_tick(table)}"
    return f"{quote_ident(schema)}.{quote_ident(table)}"


def _filter_sql(
    item: Filter,
    *,
    inline: bool,
    ticks: bool,
    params: list[Any],
    column_types: dict[str, str] | None = None,
) -> str:
    col = quote_sql_ident(item.column, ticks=ticks)
    bind_type = None
    if column_types and not inline:
        bind_type = pg_bind_type(column_types.get(item.column))
    if item.op == "is_null":
        return f"{col} IS NULL"
    if item.op == "is_not_null":
        return f"{col} IS NOT NULL"
    if item.op == "in":
        values = list(item.value)
        if inline:
            return f"{col} IN ({', '.join(sql_literal(v) for v in values)})"
        params.extend(_pg_value(bind_type, v) for v in values)
        holder = _pg_placeholder(bind_type, item.op)
        return f"{col} IN ({', '.join([holder] * len(values))})"
    if inline:
        return f"{col} {OPS[item.op]} {sql_literal(item.value)}"
    params.append(_pg_value(bind_type, item.value))
    return f"{col} {OPS[item.op]} {_pg_placeholder(bind_type, item.op)}"


def clamp_limit(value: object, default: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))


def _to_asyncpg(sql: str) -> str:
    parts: list[str] = []
    index = 0
    remaining = sql
    while "%s" in remaining:
        before, remaining = remaining.split("%s", 1)
        index += 1
        parts.append(before)
        parts.append(f"${index}")
    parts.append(remaining)
    return "".join(parts)


def _finish_sql(sql: str, params: list[Any], *, dialect: str, limit: int) -> tuple[str, tuple[Any, ...]]:
    if dialect == "tibero":
        wrapped = f"SELECT * FROM ({sql}) q WHERE ROWNUM <= {int(limit)}"
        return wrapped.replace("%s", "?"), tuple(params)
    sql += f" LIMIT {int(limit)}"
    return _to_asyncpg(sql), tuple(params)


def assemble_select_bound(
    schema: str,
    table: str,
    columns: list[str],
    filters: list[Filter],
    order_by: list[Order],
    limit: int,
    *,
    source: str | None = None,
    inline: bool = False,
    dialect: str = "postgres",
    column_types: dict[str, str] | None = None,
) -> tuple[str, tuple[Any, ...]]:
    if not columns:
        raise IdentError("columns are required")
    ticks = bool(source) or inline
    col_sql = ", ".join(quote_sql_ident(col, ticks=ticks) for col in columns)
    sql = f"SELECT {col_sql} FROM {from_sql(schema, table, source)}"
    params: list[Any] = []
    clauses: list[str] = []
    for item in filters:
        clauses.append(_filter_sql(
            item,
            inline=inline,
            ticks=ticks,
            params=params,
            column_types=column_types if dialect == "postgres" else None,
        ))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if order_by:
        parts = [
            f"{quote_sql_ident(item.column, ticks=ticks)} {'DESC' if item.direction == 'desc' else 'ASC'}"
            for item in order_by
        ]
        sql += " ORDER BY " + ", ".join(parts)
    return _finish_sql(sql, params, dialect=dialect, limit=limit)


def assemble_distinct(
    schema: str, table: str, column: str, limit: int, *, source: str | None = None,
) -> str:
    ticks = bool(source)
    col = quote_sql_ident(column, ticks=ticks)
    return (
        f"SELECT DISTINCT {col} AS distinct_value "
        f"FROM {from_sql(schema, table, source)} "
        f"LIMIT {int(limit)}"
    )


def assemble_aggregate(
    schema: str,
    table: str,
    func: str,
    column: str | None,
    group_by: list[str],
    limit: int,
    filters: list[Filter] | None = None,
    *,
    source: str | None = None,
    inline: bool = False,
    dialect: str = "postgres",
    column_types: dict[str, str] | None = None,
) -> tuple[str, tuple[Any, ...]]:
    name = (func or "").strip().lower()
    if name not in AGG_FUNCS:
        raise IdentError("unsupported aggregate")
    ticks = bool(source) or inline
    if name == "count" and not column:
        expr = "COUNT(*) AS row_count"
    elif name == "count":
        expr = f"COUNT({quote_sql_ident(column, ticks=ticks)}) AS row_count"
    else:
        if not column:
            raise IdentError("column is required")
        expr = f"{name.upper()}({quote_sql_ident(column, ticks=ticks)}) AS value"
    groups = [quote_sql_ident(item, ticks=ticks) for item in group_by]
    select_list = ", ".join([*groups, expr]) if groups else expr
    sql = f"SELECT {select_list} FROM {from_sql(schema, table, source)}"
    params: list[Any] = []
    clauses: list[str] = []
    for item in filters or []:
        clauses.append(_filter_sql(
            item,
            inline=inline,
            ticks=ticks,
            params=params,
            column_types=column_types if dialect == "postgres" else None,
        ))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if groups:
        sql += " GROUP BY " + ", ".join(groups)
    return _finish_sql(sql, params, dialect=dialect, limit=limit)
