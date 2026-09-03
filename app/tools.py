from __future__ import annotations

import logging
from typing import Any

from . import catalog_client, execute_client, filters, intersect, sqlutil
from .settings import Settings

log = logging.getLogger("kair-mcp-query")


class QueryError(ValueError):
    pass


def _normalize_args(pool_or_args: Any, args: dict[str, Any] | None) -> tuple[Any, dict[str, Any]]:
    if args is None and isinstance(pool_or_args, dict):
        return None, pool_or_args
    return pool_or_args, args or {}


async def load_allowed(
    settings: Settings,
    pool: Any = None,
) -> list[intersect.AllowedTable]:
    catalog = await catalog_client.fetch_catalog(settings.robo_meta_url)
    return intersect.catalog_tables(catalog)


def _table_ref(item: intersect.AllowedTable) -> dict[str, str]:
    return {
        "source_name": item.source_name,
        "schema_name": item.schema_name,
        "table_name": item.table_name,
        "engine": item.engine,
    }


async def list_tables(
    settings: Settings,
    pool: Any = None,
    schema_name: str | None = None,
) -> dict:
    if isinstance(pool, str) and schema_name is None:
        schema_name = pool
        pool = None
    allowed = await load_allowed(settings, pool)
    schema_key = (schema_name or "").strip().lower()
    items = [
        {
            **_table_ref(item),
            "columns": list(item.columns),
        }
        for item in allowed
        if not schema_key or item.schema_name.lower() == schema_key
    ]
    return {"total": len(items), "items": items}


async def _allowed_table(
    settings: Settings,
    pool_or_args: Any,
    args: dict[str, Any] | None = None,
) -> intersect.AllowedTable:
    pool, actual_args = _normalize_args(pool_or_args, args)
    source_name = str(actual_args.get("source_name") or "").strip()
    schema_name = str(actual_args.get("schema_name") or "").strip()
    table_name = str(actual_args.get("table_name") or "").strip()
    if not source_name or not schema_name or not table_name:
        raise QueryError("source_name, schema_name, table_name 이 필요합니다.")
    allowed = await load_allowed(settings, pool)
    if not allowed:
        raise QueryError("조회 가능한 표가 없습니다. 카탈로그가 비었거나 표가 없습니다.")
    table = intersect.find_table(allowed, source_name, schema_name, table_name)
    if table is None:
        raise QueryError("허용된 표가 아닙니다.")
    return table


async def _execute_sql(settings: Settings, sql: str, max_rows: int) -> list[dict]:
    try:
        return await execute_client.execute_query(
            settings.robo_meta_url,
            sql,
            max_rows=max_rows,
        )
    except execute_client.ExecuteError as exc:
        raise QueryError(str(exc)) from exc


async def describe_table(
    settings: Settings,
    pool_or_args: Any,
    args: dict[str, Any] | None = None,
) -> dict:
    pool, actual_args = _normalize_args(pool_or_args, args)
    table = await _allowed_table(settings, pool, actual_args)
    catalog = await catalog_client.fetch_catalog(settings.robo_meta_url)
    catalog_table = intersect.find_catalog_table(
        catalog, table.source_name, table.schema_name, table.table_name
    )
    raw_cols = (catalog_table or {}).get("columns") or []
    columns: list[dict] = []
    for col in raw_cols:
        if not isinstance(col, dict) or not col.get("column_name"):
            continue
        name = str(col["column_name"])
        columns.append(
            {
                "column_name": name,
                "data_type": col.get("data_type"),
                "nullable": col.get("nullable"),
                "primary_key": bool(col.get("primary_key")),
                "comment": col.get("comment") or col.get("description"),
            }
        )
    return {**_table_ref(table), "columns": columns}


async def get_distinct_values(
    settings: Settings,
    pool_or_args: Any,
    args: dict[str, Any] | None = None,
) -> dict:
    pool, actual_args = _normalize_args(pool_or_args, args)
    table = await _allowed_table(settings, pool, actual_args)
    column = str(actual_args.get("column_name") or actual_args.get("column") or "").strip()
    if not column:
        raise QueryError("column_name 이 필요합니다.")
    try:
        physical_column = intersect.resolve_columns(table, [column])[0]
        limit = sqlutil.clamp_limit(actual_args.get("limit"), 50, settings.row_limit)
        sql = sqlutil.assemble_exec_distinct(
            table.source_name,
            table.schema_name,
            table.table_name,
            physical_column,
            limit,
        )
    except KeyError as exc:
        raise QueryError(f"허용된 컬럼이 아닙니다: {exc.args[0]}") from exc
    except sqlutil.IdentError as exc:
        raise QueryError(str(exc)) from exc
    rows = await _execute_sql(settings, sql, limit)
    values = [row.get("value") for row in rows]
    log.info("get_distinct_values %s.%s.%s n=%s", table.schema_name, table.table_name, physical_column, len(values))
    return {
        **_table_ref(table),
        "column_name": physical_column,
        "items": values,
    }


async def query_table(
    settings: Settings,
    pool_or_args: Any,
    args: dict[str, Any] | None = None,
) -> dict:
    pool, actual_args = _normalize_args(pool_or_args, args)
    table = await _allowed_table(settings, pool, actual_args)
    requested = actual_args.get("columns")
    if requested is None:
        columns = None
    elif not isinstance(requested, list):
        raise QueryError("columns 는 배열이어야 합니다.")
    else:
        columns = [str(col) for col in requested]

    try:
        physical_columns = intersect.resolve_columns(table, columns)
        parsed_filters = filters.parse_filters(actual_args.get("filters"))
        parsed_order = filters.parse_order(actual_args.get("order_by"))
        bound_filters = []
        for item in parsed_filters:
            col = intersect.resolve_columns(table, [item.column])[0]
            bound_filters.append(filters.Filter(column=col, op=item.op, value=item.value))
        bound_order = []
        for item in parsed_order:
            col = intersect.resolve_columns(table, [item.column])[0]
            bound_order.append(filters.Order(column=col, direction=item.direction))
        limit = sqlutil.clamp_limit(actual_args.get("limit"), 50, settings.row_limit)
        sql = sqlutil.assemble_exec_select(
            table.source_name,
            table.schema_name,
            table.table_name,
            physical_columns,
            bound_filters,
            bound_order,
            limit,
        )
    except KeyError as exc:
        raise QueryError(f"허용된 컬럼이 아닙니다: {exc.args[0]}") from exc
    except sqlutil.IdentError as exc:
        raise QueryError(str(exc)) from exc

    rows = await _execute_sql(settings, sql, limit)
    log.info("query_table %s.%s rows=%s", table.schema_name, table.table_name, len(rows))
    return {
        **_table_ref(table),
        "columns": physical_columns,
        "items": rows,
    }


async def aggregate_table(
    settings: Settings,
    pool_or_args: Any,
    args: dict[str, Any] | None = None,
) -> dict:
    pool, actual_args = _normalize_args(pool_or_args, args)
    table = await _allowed_table(settings, pool, actual_args)
    func = str(actual_args.get("func") or "").strip().lower()
    raw_column = actual_args.get("column")
    column = str(raw_column).strip() if raw_column not in (None, "") else None
    raw_groups = actual_args.get("group_by")
    if raw_groups is None:
        group_names: list[str] = []
    elif not isinstance(raw_groups, list):
        raise QueryError("group_by 는 배열이어야 합니다.")
    else:
        group_names = [str(item) for item in raw_groups]

    try:
        physical_column = None
        if column:
            resolved = intersect.resolve_columns(table, [column])
            physical_column = resolved[0]
        group_by = intersect.resolve_columns(table, group_names) if group_names else []
        parsed_filters = filters.parse_filters(actual_args.get("filters"))
        bound_filters = []
        for item in parsed_filters:
            col = intersect.resolve_columns(table, [item.column])[0]
            bound_filters.append(filters.Filter(column=col, op=item.op, value=item.value))
        limit = sqlutil.clamp_limit(actual_args.get("limit"), 1 if not group_by else 50, settings.row_limit)
        sql = sqlutil.assemble_exec_aggregate(
            table.source_name,
            table.schema_name,
            table.table_name,
            func,
            physical_column,
            group_by,
            limit,
            bound_filters,
        )
    except KeyError as exc:
        raise QueryError(f"허용된 컬럼이 아닙니다: {exc.args[0]}") from exc
    except sqlutil.IdentError as exc:
        raise QueryError(str(exc)) from exc

    rows = await _execute_sql(settings, sql, limit)
    log.info("aggregate_table %s.%s func=%s rows=%s", table.schema_name, table.table_name, func, len(rows))
    return {
        **_table_ref(table),
        "func": func,
        "column": physical_column,
        "group_by": group_by,
        "items": rows,
    }
