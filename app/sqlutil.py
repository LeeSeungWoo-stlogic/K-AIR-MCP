from __future__ import annotations

from typing import Any

from .engine import POSTGRES, TIBERO
from .errors import IdentError
from .filters import OPS, Filter, Order

_FORBIDDEN = frozenset({'"', "\x00", ";", "\\"})


def quote_ident(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise IdentError("identifier is required")
    if len(name) > 128:
        raise IdentError("identifier is too long")
    if any(ch in name for ch in _FORBIDDEN) or "." in name:
        raise IdentError("invalid identifier")
    return f'"{name}"'


def clamp_limit(value: object, default: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))


AGG_FUNCS = frozenset({"count", "sum", "avg", "max", "min"})


def limit_clause(limit: int, dialect: str = POSTGRES) -> str:
    n = int(limit)
    if dialect == TIBERO:
        return f" FETCH FIRST {n} ROWS ONLY"
    if dialect != POSTGRES:
        raise IdentError("unsupported dialect")
    return f" LIMIT {n}"


def assemble_select(schema: str, table: str, columns: list[str], limit: int, dialect: str = POSTGRES) -> str:
    sql, _params = assemble_select_bound(schema, table, columns, [], [], limit, dialect)
    return sql


def assemble_select_bound(
    schema: str,
    table: str,
    columns: list[str],
    filters: list[Filter],
    order_by: list[Order],
    limit: int,
    dialect: str = POSTGRES,
) -> tuple[str, tuple[Any, ...]]:
    if not columns:
        raise IdentError("columns are required")
    col_sql = ", ".join(quote_ident(col) for col in columns)
    sql = f"SELECT {col_sql} FROM {quote_ident(schema)}.{quote_ident(table)}"
    params: list[Any] = []
    clauses: list[str] = []
    ph = "?" if dialect == TIBERO else "%s"
    for item in filters:
        col = quote_ident(item.column)
        if item.op == "is_null":
            clauses.append(f"{col} IS NULL")
        elif item.op == "is_not_null":
            clauses.append(f"{col} IS NOT NULL")
        elif item.op == "in":
            values = list(item.value)
            clauses.append(f"{col} IN ({', '.join([ph] * len(values))})")
            params.extend(values)
        else:
            clauses.append(f"{col} {OPS[item.op]} {ph}")
            params.append(item.value)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    if order_by:
        parts = [
            f"{quote_ident(item.column)} {'DESC' if item.direction == 'desc' else 'ASC'}"
            for item in order_by
        ]
        sql += " ORDER BY " + ", ".join(parts)
    return sql + limit_clause(limit, dialect), tuple(params)


def assemble_distinct(
    schema: str, table: str, column: str, limit: int, dialect: str = POSTGRES
) -> str:
    col = quote_ident(column)
    value_alias = quote_ident("value") if dialect == TIBERO else "value"
    return (
        f"SELECT DISTINCT {col} AS {value_alias} "
        f"FROM {quote_ident(schema)}.{quote_ident(table)} "
        f"WHERE {col} IS NOT NULL "
        f"ORDER BY 1{limit_clause(limit, dialect)}"
    )


def assemble_aggregate(
    schema: str,
    table: str,
    func: str,
    column: str | None,
    group_by: list[str],
    limit: int,
    dialect: str = POSTGRES,
) -> str:
    name = (func or "").strip().lower()
    if name not in AGG_FUNCS:
        raise IdentError("unsupported aggregate")
    count_alias = quote_ident("row_count") if dialect == TIBERO else "row_count"
    value_alias = quote_ident("value") if dialect == TIBERO else "value"
    if name == "count" and not column:
        expr = f"COUNT(*) AS {count_alias}"
    elif name == "count":
        expr = f"COUNT({quote_ident(column)}) AS {count_alias}"
    else:
        if not column:
            raise IdentError("column is required")
        expr = f"{name.upper()}({quote_ident(column)}) AS {value_alias}"
    groups = [quote_ident(item) for item in group_by]
    select_list = ", ".join([*groups, expr]) if groups else expr
    sql = f"SELECT {select_list} FROM {quote_ident(schema)}.{quote_ident(table)}"
    if groups:
        sql += " GROUP BY " + ", ".join(groups)
    return sql + limit_clause(limit, dialect)
