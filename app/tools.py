from __future__ import annotations

import logging
from typing import Any

from psycopg_pool import AsyncConnectionPool

from . import catalog_client, execute_client, filters, intersect, pg_store, sqlutil, tb_store
from .engine import POSTGRES, TIBERO
from .settings import Settings
from .tb_store import TiberoError

log = logging.getLogger("kair-mcp-query")


class QueryError(ValueError):
    pass


async def load_allowed(
    settings: Settings,
    pool: AsyncConnectionPool | None,
) -> list[intersect.AllowedTable]:
    catalog = await catalog_client.fetch_catalog(settings.robo_meta_url)
    needed = intersect.catalog_engines(catalog)
    inventories: dict[str, intersect.EngineInventory] = {}
    if POSTGRES in needed:
        if pool is None:
            log.warning("카탈로그에 postgres 소스가 있으나 분석 Postgres 원천이 없습니다")
            inventories[POSTGRES] = intersect.EngineInventory(tables=set(), columns={})
        else:
            pg_tables, pg_columns = await pg_store.list_pg_inventory(pool)
            inventories[POSTGRES] = intersect.EngineInventory(tables=pg_tables, columns=pg_columns)
    if TIBERO in needed:
        owners = intersect.catalog_schemas(catalog, TIBERO)
        try:
            inventories[TIBERO] = await tb_store.list_tb_inventory(settings, owners)
        except TiberoError as exc:
            raise QueryError(str(exc)) from exc
    return intersect.intersect_catalog(catalog, inventories)


def _table_ref(item: intersect.AllowedTable) -> dict[str, str]:
    return {
        "source_name": item.source_name,
        "schema_name": item.schema_name,
        "table_name": item.table_name,
        "engine": item.engine,
    }


async def list_tables(
    settings: Settings,
    pool: AsyncConnectionPool | None,
    schema_name: str | None = None,
) -> dict:
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
    pool: AsyncConnectionPool | None,
    args: dict[str, Any],
) -> intersect.AllowedTable:
    source_name = str(args.get("source_name") or "").strip()
    schema_name = str(args.get("schema_name") or "").strip()
    table_name = str(args.get("table_name") or "").strip()
    if not source_name or not schema_name or not table_name:
        raise QueryError("source_name, schema_name, table_name 이 필요합니다.")
    allowed = await load_allowed(settings, pool)
    if not allowed:
        raise QueryError("조회 가능한 표가 없습니다. 카탈로그가 비었거나 해당 엔진 원천에 표가 없습니다.")
    table = intersect.find_table(allowed, source_name, schema_name, table_name)
    if table is None:
        raise QueryError("허용된 표가 아닙니다.")
    return table


async def _column_comments(
    settings: Settings,
    pool: AsyncConnectionPool | None,
    table: intersect.AllowedTable,
) -> dict[str, str]:
    if table.engine == POSTGRES:
        if pool is None:
            raise QueryError("분석 Postgres 원천이 없습니다")
        return await pg_store.column_comments(pool, table.physical_schema, table.physical_table)
    if table.engine == TIBERO:
        try:
            return await tb_store.column_comments(settings, table.physical_schema, table.physical_table)
        except TiberoError as exc:
            raise QueryError(str(exc)) from exc
    raise QueryError(f"지원하지 않는 engine 입니다: {table.engine}")


async def _execute_sql(settings: Settings, sql: str, max_rows: int) -> list[dict]:
    try:
        return await execute_client.execute_query(
            settings.robo_meta_url,
            sql,
            max_rows=max_rows,
        )
    except execute_client.ExecuteError as exc:
        raise QueryError(str(exc)) from exc


async def describe_table(settings: Settings, pool: AsyncConnectionPool | None, args: dict[str, Any]) -> dict:
    table = await _allowed_table(settings, pool, args)
    catalog = await catalog_client.fetch_catalog(settings.robo_meta_url)
    catalog_table = intersect.find_catalog_table(
        catalog, table.source_name, table.schema_name, table.table_name
    )
    comments = await _column_comments(settings, pool, table)
    physical_by_key = {name.lower(): name for name in table.physical_columns}
    columns: list[dict] = []
    raw_cols = (catalog_table or {}).get("columns") or []
    for col in raw_cols:
        if not isinstance(col, dict) or not col.get("column_name"):
            continue
        name = str(col["column_name"])
        physical = physical_by_key.get(name.lower())
        if physical is None:
            continue
        columns.append(
            {
                "column_name": physical,
                "data_type": col.get("data_type"),
                "nullable": col.get("nullable"),
                "primary_key": bool(col.get("primary_key")),
                "comment": comments.get(physical),
            }
        )
    return {**_table_ref(table), "columns": columns}


async def get_distinct_values(settings: Settings, pool: AsyncConnectionPool | None, args: dict[str, Any]) -> dict:
    table = await _allowed_table(settings, pool, args)
    column = str(args.get("column_name") or args.get("column") or "").strip()
    if not column:
        raise QueryError("column_name 이 필요합니다.")
    try:
        physical_column = intersect.resolve_columns(table, [column])[0]
        limit = sqlutil.clamp_limit(args.get("limit"), 50, settings.row_limit)
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


async def query_table(settings: Settings, pool: AsyncConnectionPool | None, args: dict[str, Any]) -> dict:
    table = await _allowed_table(settings, pool, args)
    requested = args.get("columns")
    if requested is None:
        columns = None
    elif not isinstance(requested, list):
        raise QueryError("columns 는 배열이어야 합니다.")
    else:
        columns = [str(col) for col in requested]

    try:
        physical_columns = intersect.resolve_columns(table, columns)
        parsed_filters = filters.parse_filters(args.get("filters"))
        parsed_order = filters.parse_order(args.get("order_by"))
        bound_filters = []
        for item in parsed_filters:
            col = intersect.resolve_columns(table, [item.column])[0]
            bound_filters.append(filters.Filter(column=col, op=item.op, value=item.value))
        bound_order = []
        for item in parsed_order:
            col = intersect.resolve_columns(table, [item.column])[0]
            bound_order.append(filters.Order(column=col, direction=item.direction))
        limit = sqlutil.clamp_limit(args.get("limit"), 50, settings.row_limit)
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


async def aggregate_table(settings: Settings, pool: AsyncConnectionPool | None, args: dict[str, Any]) -> dict:
    table = await _allowed_table(settings, pool, args)
    func = str(args.get("func") or "").strip().lower()
    raw_column = args.get("column")
    column = str(raw_column).strip() if raw_column not in (None, "") else None
    raw_groups = args.get("group_by")
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
        parsed_filters = filters.parse_filters(args.get("filters"))
        bound_filters = []
        for item in parsed_filters:
            col = intersect.resolve_columns(table, [item.column])[0]
            bound_filters.append(filters.Filter(column=col, op=item.op, value=item.value))
        limit = sqlutil.clamp_limit(args.get("limit"), 1 if not group_by else 50, settings.row_limit)
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
