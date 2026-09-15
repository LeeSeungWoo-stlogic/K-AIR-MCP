from __future__ import annotations

from typing import Any

from .errors import IdentError
from .filters import OPS, Filter, Order

_FORBIDDEN = frozenset({'"', "\x00", ";", "\\"})
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


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def from_sql(schema: str, table: str, source: str | None = None) -> str:
    if source:
        return f"{quote_tick(source)}.{quote_tick(schema)}.{quote_tick(table)}"
    return f"{quote_ident(schema)}.{quote_ident(table)}"


def _filter_sql(item: Filter, *, inline: bool, params: list[Any]) -> str:
    col = quote_ident(item.column)
    if item.op == "is_null":
        return f"{col} IS NULL"
    if item.op == "is_not_null":
        return f"{col} IS NOT NULL"
    if item.op == "in":
        values = list(item.value)
        if inline:
            return f"{col} IN ({', '.join(sql_literal(v) for v in values)})"
        params.extend(values)
        return f"{col} IN ({', '.join(['%s'] * len(values))})"
    if inline:
        return f"{col} {OPS[item.op]} {sql_literal(item.value)}"
    params.append(item.value)
    return f"{col} {OPS[item.op]} %s"


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
) -> tuple[str, tuple[Any, ...]]:
    if not columns:
        raise IdentError("columns are required")
    col_sql = ", ".join(quote_ident(col) for col in columns)
    sql = f"SELECT {col_sql} FROM {from_sql(schema, table, source)}"
    params: list[Any] = []
    clauses: list[str] = []
    for item in filters:
        clauses.append(_filter_sql(item, inline=inline, params=params))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if order_by:
        parts = [
            f"{quote_ident(item.column)} {'DESC' if item.direction == 'desc' else 'ASC'}"
            for item in order_by
        ]
        sql += " ORDER BY " + ", ".join(parts)
    sql += f" LIMIT {int(limit)}"
    return _to_asyncpg(sql), tuple(params)


def assemble_distinct(
    schema: str, table: str, column: str, limit: int, *, source: str | None = None,
) -> str:
    col = quote_ident(column)
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
) -> tuple[str, tuple[Any, ...]]:
    name = (func or "").strip().lower()
    if name not in AGG_FUNCS:
        raise IdentError("unsupported aggregate")
    if name == "count" and not column:
        expr = "COUNT(*) AS row_count"
    elif name == "count":
        expr = f"COUNT({quote_ident(column)}) AS row_count"
    else:
        if not column:
            raise IdentError("column is required")
        expr = f"{name.upper()}({quote_ident(column)}) AS value"
    groups = [quote_ident(item) for item in group_by]
    select_list = ", ".join([*groups, expr]) if groups else expr
    sql = f"SELECT {select_list} FROM {from_sql(schema, table, source)}"
    params: list[Any] = []
    clauses: list[str] = []
    for item in filters or []:
        clauses.append(_filter_sql(item, inline=inline, params=params))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if groups:
        sql += " GROUP BY " + ", ".join(groups)
    sql += f" LIMIT {int(limit)}"
    return _to_asyncpg(sql), tuple(params)
