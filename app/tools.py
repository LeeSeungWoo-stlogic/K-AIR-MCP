from __future__ import annotations

import logging
from typing import Any

from . import catalog_client, execute_client, filters, intersect, pg_runner, sources_client, sqlutil
from .credentials import CredentialStore
from .errors import IdentError
from .settings import Settings
from .sources_client import SourceEndpoint

log = logging.getLogger("kair-mcp-analyze")


class QueryError(ValueError):
    pass


CATALOG_UNREACHABLE = "카탈로그를 읽지 못했습니다. stone-meta-api POST /meta/catalog 에 연결할 수 없습니다."
EXECUTE_UNREACHABLE = "조회를 실행하지 못했습니다. stone-meta-api POST /query_execute 에 연결할 수 없습니다."
SOURCES_UNREACHABLE = "데이터소스 목록을 읽지 못했습니다. nk-backend GET /air-swmm/data-fabric/api/datasources 에 연결할 수 없습니다."
NEED_CREDENTIALS = "이 소스에 대한 id/pw가 없습니다. set_credentials로 먼저 입력하세요. PG 직조회에만 필요합니다."
VIA_MINDSDB = "mindsdb-query_execute"
VIA_PG = "postgres-direct"


def _row_distinct_value(row: dict[str, Any], physical_column: str) -> Any:
    if not isinstance(row, dict) or not row:
        return None
    lower = {str(key).lower(): value for key, value in row.items()}
    for key in ("distinct_value", "value", physical_column.lower()):
        if key in lower:
            return lower[key]
    return next(iter(row.values()), None)


def _table_ref(item: intersect.AllowedTable) -> dict[str, str]:
    return {
        "source_name": item.source_name,
        "schema_name": item.schema_name,
        "table_name": item.table_name,
        "engine": item.engine,
    }


def _table_labels(item: intersect.AllowedTable) -> dict[str, str | None]:
    return {
        "table_logical_name": item.logical_name or None,
        "description": item.description or None,
    }


async def load_catalog(settings: Settings) -> dict:
    try:
        return await catalog_client.fetch_catalog(settings.stone_meta_url)
    except catalog_client.CatalogError as exc:
        raise QueryError(CATALOG_UNREACHABLE) from exc


async def load_endpoints(settings: Settings) -> list[SourceEndpoint]:
    try:
        return await sources_client.fetch_postgres_endpoints(
            settings.nk_backend_url,
            settings.nk_backend_token,
        )
    except sources_client.SourcesError as exc:
        raise QueryError(SOURCES_UNREACHABLE) from exc


def _require_table_keys(actual_args: dict[str, Any]) -> tuple[str, str, str]:
    source_name = str(actual_args.get("source_name") or "").strip()
    schema_name = str(actual_args.get("schema_name") or "").strip()
    table_name = str(actual_args.get("table_name") or "").strip()
    if not source_name or not schema_name or not table_name:
        raise QueryError("source_name, schema_name, table_name 이 필요합니다.")
    return source_name, schema_name, table_name


def _table_from_catalog(
    catalog: dict,
    source_name: str,
    schema_name: str,
    table_name: str,
) -> intersect.AllowedTable:
    allowed = intersect.catalog_tables(catalog, postgres_only=True)
    if not allowed:
        raise QueryError("조회 가능한 Postgres 표가 없습니다. 카탈로그가 비었거나 표가 없습니다.")
    table = intersect.find_table(allowed, source_name, schema_name, table_name)
    if table is None:
        raise QueryError("허용된 표가 아닙니다. Postgres 카탈로그에 있는 한 소스의 한 스키마만 조회합니다.")
    return table


def _match_endpoint(
    endpoints: list[SourceEndpoint],
    table: intersect.AllowedTable,
) -> SourceEndpoint:
    endpoint = sources_client.find_endpoint(endpoints, table.source_name)
    if endpoint is None:
        raise QueryError(
            f"nk-backend 데이터소스에 Postgres 소스 '{table.source_name}' 이 없습니다."
        )
    if not endpoint.enabled:
        raise QueryError(f"소스 '{table.source_name}' 이 비활성입니다.")
    return endpoint


async def _execute_mindsdb(
    settings: Settings,
    sql: str,
    *,
    max_rows: int,
) -> list[dict]:
    timeout_s = max(1, min(120, settings.statement_timeout_ms // 1000 or 30))
    try:
        return await execute_client.query_execute(
            settings.stone_meta_url,
            sql,
            max_rows=max_rows,
            timeout_s=timeout_s,
        )
    except execute_client.ExecuteError as exc:
        raise QueryError(f"{EXECUTE_UNREACHABLE} {exc}") from exc


async def _execute_pg(
    settings: Settings,
    store: CredentialStore,
    table: intersect.AllowedTable,
    sql: str,
    params: tuple[Any, ...] = (),
    *,
    max_rows: int,
) -> list[dict]:
    endpoints = await load_endpoints(settings)
    endpoint = _match_endpoint(endpoints, table)
    login = store.get(table.source_name)
    if login is None:
        raise QueryError(NEED_CREDENTIALS)
    try:
        return await pg_runner.fetch_all(
            endpoint,
            user=login.user,
            password=login.password,
            sql=sql,
            params=params,
            max_rows=max_rows,
            statement_timeout_ms=settings.statement_timeout_ms,
        )
    except pg_runner.QueryRunError as exc:
        raise QueryError(str(exc)) from exc


def _parse_query_args(
    table: intersect.AllowedTable,
    args: dict[str, Any],
    settings: Settings,
    *,
    mindsdb: bool,
) -> tuple[str, tuple[Any, ...], list[str], int]:
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
        sql, params = sqlutil.assemble_select_bound(
            table.schema_name,
            table.table_name,
            physical_columns,
            bound_filters,
            bound_order,
            limit,
            source=table.source_name if mindsdb else None,
            inline=mindsdb,
        )
    except KeyError as exc:
        raise QueryError(f"허용된 컬럼이 아닙니다: {exc.args[0]}") from exc
    except IdentError as exc:
        raise QueryError(str(exc)) from exc
    return sql, params, physical_columns, limit


def _parse_aggregate_args(
    table: intersect.AllowedTable,
    args: dict[str, Any],
    settings: Settings,
    *,
    mindsdb: bool,
) -> tuple[str, tuple[Any, ...], str, str | None, list[str], int]:
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
            physical_column = intersect.resolve_columns(table, [column])[0]
        group_by = intersect.resolve_columns(table, group_names) if group_names else []
        parsed_filters = filters.parse_filters(args.get("filters"))
        bound_filters = []
        for item in parsed_filters:
            col = intersect.resolve_columns(table, [item.column])[0]
            bound_filters.append(filters.Filter(column=col, op=item.op, value=item.value))
        limit = sqlutil.clamp_limit(args.get("limit"), 1 if not group_by else 50, settings.row_limit)
        sql, params = sqlutil.assemble_aggregate(
            table.schema_name,
            table.table_name,
            func,
            physical_column,
            group_by,
            limit,
            bound_filters,
            source=table.source_name if mindsdb else None,
            inline=mindsdb,
        )
    except KeyError as exc:
        raise QueryError(f"허용된 컬럼이 아닙니다: {exc.args[0]}") from exc
    except IdentError as exc:
        raise QueryError(str(exc)) from exc
    return sql, params, func, physical_column, group_by, limit


async def list_sources(
    settings: Settings,
    store: CredentialStore,
) -> dict:
    catalog = await load_catalog(settings)
    allowed = intersect.catalog_tables(catalog, postgres_only=True)
    endpoints: list[SourceEndpoint] = []
    sources_error = None
    try:
        endpoints = await load_endpoints(settings)
    except QueryError as exc:
        sources_error = str(exc)
    by_name = {item.source_name.lower(): item for item in endpoints}
    seen: dict[tuple[str, str], dict] = {}
    for item in allowed:
        key = (item.source_name, item.schema_name)
        if key in seen:
            seen[key]["table_count"] += 1
            continue
        endpoint = by_name.get(item.source_name.lower())
        seen[key] = {
            "source_name": item.source_name,
            "engine": "postgres",
            "schema_name": item.schema_name,
            "table_count": 1,
            "host": endpoint.host if endpoint else None,
            "port": endpoint.port if endpoint else None,
            "database": endpoint.database if endpoint else None,
            "username": (endpoint.username or None) if endpoint else None,
            "enabled": endpoint.enabled if endpoint else None,
            "credentials_set": store.has(item.source_name),
        }
    payload: dict[str, Any] = {"total": len(seen), "items": list(seen.values())}
    if sources_error:
        payload["datasources_error"] = sources_error
    return payload


async def set_credentials(
    settings: Settings,
    store: CredentialStore,
    source_name: str,
    user: str,
    password: str,
) -> dict:
    name = (source_name or "").strip()
    login_user = (user or "").strip()
    if not name or not login_user or not password:
        raise QueryError("source_name, user, password 가 필요합니다.")
    endpoints = await load_endpoints(settings)
    endpoint = sources_client.find_endpoint(endpoints, name)
    if endpoint is None:
        raise QueryError(f"nk-backend 데이터소스에 Postgres 소스 '{name}' 이 없습니다.")
    if not endpoint.enabled:
        raise QueryError(f"소스 '{name}' 이 비활성입니다.")
    store.set(name, login_user, password)
    return {
        "source_name": endpoint.source_name,
        "user": login_user,
        "configured": True,
        "host": endpoint.host,
        "port": endpoint.port,
        "database": endpoint.database,
        "note": "id/pw 는 query_table_pg / aggregate_table_pg 에만 씁니다. MindsDB 조회에는 필요 없습니다.",
    }


async def clear_credentials(
    store: CredentialStore,
    source_name: str | None = None,
) -> dict:
    store.clear(source_name)
    return {"cleared": True, "source_name": source_name}


async def list_tables(
    settings: Settings,
    schema_name: str | None = None,
) -> dict:
    catalog = await load_catalog(settings)
    allowed = intersect.catalog_tables(catalog, postgres_only=True)
    schema_key = (schema_name or "").strip().lower()
    items = [
        {
            **_table_ref(item),
            **_table_labels(item),
            "columns": list(item.columns),
        }
        for item in allowed
        if not schema_key or item.schema_name.lower() == schema_key
    ]
    return {"total": len(items), "items": items}


async def describe_table(
    settings: Settings,
    args: dict[str, Any],
) -> dict:
    source_name, schema_name, table_name = _require_table_keys(args)
    catalog = await load_catalog(settings)
    table = _table_from_catalog(catalog, source_name, schema_name, table_name)
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
                "logical_name": intersect.catalog_column_logical_name(col) or None,
                "comment": col.get("comment") or col.get("description"),
            }
        )
    return {
        **_table_ref(table),
        "logical_name": table.logical_name or None,
        "description": table.description or None,
        "columns": columns,
    }


async def get_distinct_values(
    settings: Settings,
    store: CredentialStore,
    args: dict[str, Any],
) -> dict:
    source_name, schema_name, table_name = _require_table_keys(args)
    catalog = await load_catalog(settings)
    table = _table_from_catalog(catalog, source_name, schema_name, table_name)
    column = str(args.get("column_name") or args.get("column") or "").strip()
    if not column:
        raise QueryError("column_name 이 필요합니다.")
    try:
        physical_column = intersect.resolve_columns(table, [column])[0]
        limit = sqlutil.clamp_limit(args.get("limit"), 50, settings.row_limit)
        sql = sqlutil.assemble_distinct(
            table.schema_name,
            table.table_name,
            physical_column,
            limit,
            source=table.source_name,
        )
    except KeyError as exc:
        raise QueryError(f"허용된 컬럼이 아닙니다: {exc.args[0]}") from exc
    except IdentError as exc:
        raise QueryError(str(exc)) from exc
    rows = await _execute_mindsdb(settings, sql, max_rows=limit)
    values = [
        value
        for value in (_row_distinct_value(row, physical_column) for row in rows)
        if value is not None
    ]
    log.info(
        "get_distinct_values %s.%s.%s n=%s",
        table.schema_name,
        table.table_name,
        physical_column,
        len(values),
    )
    return {
        **_table_ref(table),
        "via": VIA_MINDSDB,
        "column_name": physical_column,
        "items": values,
    }


async def query_table(
    settings: Settings,
    store: CredentialStore,
    args: dict[str, Any],
) -> dict:
    source_name, schema_name, table_name = _require_table_keys(args)
    catalog = await load_catalog(settings)
    table = _table_from_catalog(catalog, source_name, schema_name, table_name)
    sql, _params, physical_columns, limit = _parse_query_args(
        table, args, settings, mindsdb=True
    )
    rows = await _execute_mindsdb(settings, sql, max_rows=limit)
    log.info("query_table %s.%s rows=%s", table.schema_name, table.table_name, len(rows))
    return {
        **_table_ref(table),
        "via": VIA_MINDSDB,
        "columns": physical_columns,
        "items": rows,
    }


async def query_table_pg(
    settings: Settings,
    store: CredentialStore,
    args: dict[str, Any],
) -> dict:
    source_name, schema_name, table_name = _require_table_keys(args)
    catalog = await load_catalog(settings)
    table = _table_from_catalog(catalog, source_name, schema_name, table_name)
    sql, params, physical_columns, limit = _parse_query_args(
        table, args, settings, mindsdb=False
    )
    rows = await _execute_pg(settings, store, table, sql, params, max_rows=limit)
    log.info("query_table_pg %s.%s rows=%s", table.schema_name, table.table_name, len(rows))
    return {
        **_table_ref(table),
        "via": VIA_PG,
        "columns": physical_columns,
        "items": rows,
    }


async def aggregate_table(
    settings: Settings,
    store: CredentialStore,
    args: dict[str, Any],
) -> dict:
    source_name, schema_name, table_name = _require_table_keys(args)
    catalog = await load_catalog(settings)
    table = _table_from_catalog(catalog, source_name, schema_name, table_name)
    sql, _params, func, physical_column, group_by, limit = _parse_aggregate_args(
        table, args, settings, mindsdb=True
    )
    rows = await _execute_mindsdb(settings, sql, max_rows=limit)
    log.info(
        "aggregate_table %s.%s func=%s rows=%s",
        table.schema_name,
        table.table_name,
        func,
        len(rows),
    )
    return {
        **_table_ref(table),
        "via": VIA_MINDSDB,
        "func": func,
        "column": physical_column,
        "group_by": group_by,
        "items": rows,
    }


async def aggregate_table_pg(
    settings: Settings,
    store: CredentialStore,
    args: dict[str, Any],
) -> dict:
    source_name, schema_name, table_name = _require_table_keys(args)
    catalog = await load_catalog(settings)
    table = _table_from_catalog(catalog, source_name, schema_name, table_name)
    sql, params, func, physical_column, group_by, limit = _parse_aggregate_args(
        table, args, settings, mindsdb=False
    )
    rows = await _execute_pg(settings, store, table, sql, params, max_rows=limit)
    log.info(
        "aggregate_table_pg %s.%s func=%s rows=%s",
        table.schema_name,
        table.table_name,
        func,
        len(rows),
    )
    return {
        **_table_ref(table),
        "via": VIA_PG,
        "func": func,
        "column": physical_column,
        "group_by": group_by,
        "items": rows,
    }
