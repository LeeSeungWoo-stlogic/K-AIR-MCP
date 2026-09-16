from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from . import assemble, catalog_client, execute_client, filters, intersect, pg_runner, sources_client, sqlutil, tibero_runner
from .engine import POSTGRES, TIBERO
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
NEED_CREDENTIALS = "이 소스에 대한 id/pw가 없습니다. set_credentials로 먼저 입력하세요. PG/Tibero 직조회에만 필요합니다."
VIA_MINDSDB = "mindsdb-query_execute"
VIA_PG = "postgres-direct"
VIA_TIBERO = "tibero-direct"
VIA_ASSEMBLE = "mcp-assemble"
VIA_ALIASES = {
    "mindsdb": VIA_MINDSDB,
    "mindsdb-query_execute": VIA_MINDSDB,
    "pg": VIA_PG,
    "postgres": VIA_PG,
    "postgres-direct": VIA_PG,
    "tibero": VIA_TIBERO,
    "tibero-direct": VIA_TIBERO,
}


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
        return await sources_client.fetch_direct_endpoints(
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
    *,
    engines: set[str] | None = None,
) -> intersect.AllowedTable:
    allowed = intersect.catalog_tables(
        catalog,
        postgres_only=engines is None,
        engines=engines,
    )
    if not allowed:
        raise QueryError("조회 가능한 표가 없습니다. 카탈로그가 비었거나 허용 엔진 표가 없습니다.")
    table = intersect.find_table(allowed, source_name, schema_name, table_name)
    if table is None:
        raise QueryError("허용된 표가 아닙니다. 카탈로그에 있는 한 소스의 한 스키마만 조회합니다.")
    return table


def _columns_from_table_meta(detail: dict) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for col in detail.get("columns") or []:
        if not isinstance(col, dict):
            continue
        name = str(col.get("column_name") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        names.append(name)
    return tuple(names)


async def _table_with_columns(
    settings: Settings,
    catalog: dict,
    source_name: str,
    schema_name: str,
    table_name: str,
    *,
    engines: set[str] | None = None,
) -> intersect.AllowedTable:
    table = _table_from_catalog(
        catalog, source_name, schema_name, table_name, engines=engines
    )
    if table.columns:
        return table
    try:
        detail = await catalog_client.fetch_table(
            settings.stone_meta_url,
            source_name=table.source_name,
            schema_name=table.schema_name,
            table_name=table.table_name,
        )
    except catalog_client.CatalogError as exc:
        raise QueryError(f"표 상세를 읽지 못했습니다. stone-meta-api POST /meta/table. {exc}") from exc
    cols = _columns_from_table_meta(detail)
    if not cols:
        raise QueryError("허용된 컬럼이 없습니다. /meta/table 에 컬럼이 없습니다.")
    return replace(table, columns=cols)


def _match_endpoint(
    endpoints: list[SourceEndpoint],
    table: intersect.AllowedTable,
) -> SourceEndpoint:
    endpoint = sources_client.find_endpoint(endpoints, table.source_name)
    if endpoint is None:
        raise QueryError(
            f"nk-backend 데이터소스에 소스 '{table.source_name}' 이 없습니다."
        )
    if table.engine and endpoint.engine != table.engine:
        raise QueryError(
            f"소스 '{table.source_name}' 엔진이 {endpoint.engine} 입니다. {table.engine} 경로와 맞지 않습니다."
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


async def _execute_tibero(
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
        return await tibero_runner.fetch_all(
            endpoint,
            user=login.user,
            password=login.password,
            sql=sql,
            params=params,
            max_rows=max_rows,
            jar_path=settings.tibero_jdbc_jar or None,
        )
    except tibero_runner.QueryRunError as exc:
        raise QueryError(str(exc)) from exc


def _parse_query_args(
    table: intersect.AllowedTable,
    args: dict[str, Any],
    settings: Settings,
    *,
    mindsdb: bool,
    dialect: str = "postgres",
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
            dialect=dialect,
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
    dialect: str = "postgres",
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
            dialect=dialect,
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
    allowed = intersect.catalog_tables(catalog, postgres_only=False, engines={POSTGRES, TIBERO})
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
            "engine": item.engine,
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
        raise QueryError(f"nk-backend 데이터소스에 소스 '{name}' 이 없습니다.")
    if not endpoint.enabled:
        raise QueryError(f"소스 '{name}' 이 비활성입니다.")
    store.set(name, login_user, password)
    return {
        "source_name": endpoint.source_name,
        "engine": endpoint.engine,
        "user": login_user,
        "configured": True,
        "host": endpoint.host,
        "port": endpoint.port,
        "database": endpoint.database,
        "note": "id/pw 는 query_table_pg / query_table_tibero / 집계 직조회에만 씁니다. MindsDB 조회에는 필요 없습니다.",
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
    allowed = intersect.catalog_tables(catalog, postgres_only=False, engines={POSTGRES, TIBERO})
    schema_key = (schema_name or "").strip().lower()
    items = [
        {
            **_table_ref(item),
            **_table_labels(item),
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
    table = _table_from_catalog(
        catalog, source_name, schema_name, table_name, engines={POSTGRES, TIBERO}
    )
    try:
        detail = await catalog_client.fetch_table(
            settings.stone_meta_url,
            source_name=table.source_name,
            schema_name=table.schema_name,
            table_name=table.table_name,
        )
    except catalog_client.CatalogError as exc:
        raise QueryError(f"표 상세를 읽지 못했습니다. stone-meta-api POST /meta/table. {exc}") from exc
    info = detail.get("table_info") if isinstance(detail.get("table_info"), dict) else {}
    fk_by_col: dict[str, dict] = {}
    for fk in detail.get("fk") or []:
        if not isinstance(fk, dict) or not fk.get("column_name"):
            continue
        fk_by_col[str(fk["column_name"]).lower()] = {
            "schema_name": fk.get("ref_schema_name"),
            "table_name": fk.get("ref_table_name"),
            "column_name": fk.get("ref_column_name"),
            "position": fk.get("position") or 1,
        }
    columns: list[dict] = []
    for col in detail.get("columns") or []:
        if not isinstance(col, dict) or not col.get("column_name"):
            continue
        name = str(col["column_name"])
        constraints = col.get("constraints") or []
        columns.append(
            {
                "column_name": name,
                "data_type": col.get("data_type"),
                "nullable": col.get("is_null") if "is_null" in col else col.get("nullable"),
                "primary_key": "PK" in constraints or bool(col.get("primary_key")),
                "logical_name": col.get("column_name_kr") or intersect.catalog_column_logical_name(col) or None,
                "comment": col.get("column_comment") or col.get("comment") or col.get("description"),
                "references": fk_by_col.get(name.lower()),
                "referenced_by": None,
            }
        )
    return {
        **_table_ref(table),
        "logical_name": table.logical_name or info.get("table_name_kr") or None,
        "description": table.description or info.get("description") or None,
        "columns": columns,
    }


async def get_distinct_values(
    settings: Settings,
    store: CredentialStore,
    args: dict[str, Any],
) -> dict:
    source_name, schema_name, table_name = _require_table_keys(args)
    catalog = await load_catalog(settings)
    table = await _table_with_columns(
        settings, catalog, source_name, schema_name, table_name, engines={POSTGRES, TIBERO}
    )
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
    table = await _table_with_columns(
        settings, catalog, source_name, schema_name, table_name, engines={POSTGRES, TIBERO}
    )
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
    table = await _table_with_columns(
        settings, catalog, source_name, schema_name, table_name, engines={POSTGRES}
    )
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


async def query_table_tibero(
    settings: Settings,
    store: CredentialStore,
    args: dict[str, Any],
) -> dict:
    source_name, schema_name, table_name = _require_table_keys(args)
    catalog = await load_catalog(settings)
    table = await _table_with_columns(
        settings, catalog, source_name, schema_name, table_name, engines={TIBERO}
    )
    sql, params, physical_columns, limit = _parse_query_args(
        table, args, settings, mindsdb=False, dialect="tibero"
    )
    rows = await _execute_tibero(settings, store, table, sql, params, max_rows=limit)
    log.info("query_table_tibero %s.%s rows=%s", table.schema_name, table.table_name, len(rows))
    return {
        **_table_ref(table),
        "via": VIA_TIBERO,
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
    table = await _table_with_columns(
        settings, catalog, source_name, schema_name, table_name, engines={POSTGRES, TIBERO}
    )
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
    table = await _table_with_columns(
        settings, catalog, source_name, schema_name, table_name, engines={POSTGRES}
    )
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


async def aggregate_table_tibero(
    settings: Settings,
    store: CredentialStore,
    args: dict[str, Any],
) -> dict:
    source_name, schema_name, table_name = _require_table_keys(args)
    catalog = await load_catalog(settings)
    table = await _table_with_columns(
        settings, catalog, source_name, schema_name, table_name, engines={TIBERO}
    )
    sql, params, func, physical_column, group_by, limit = _parse_aggregate_args(
        table, args, settings, mindsdb=False, dialect="tibero"
    )
    rows = await _execute_tibero(settings, store, table, sql, params, max_rows=limit)
    log.info(
        "aggregate_table_tibero %s.%s func=%s rows=%s",
        table.schema_name,
        table.table_name,
        func,
        len(rows),
    )
    return {
        **_table_ref(table),
        "via": VIA_TIBERO,
        "func": func,
        "column": physical_column,
        "group_by": group_by,
        "items": rows,
    }


async def _query_via(
    settings: Settings,
    store: CredentialStore,
    via: str,
    args: dict[str, Any],
) -> dict:
    if via == VIA_PG:
        return await query_table_pg(settings, store, args)
    if via == VIA_TIBERO:
        return await query_table_tibero(settings, store, args)
    return await query_table(settings, store, args)


def _parse_via(raw: Any) -> str:
    key = str(raw or "mindsdb").strip().lower()
    via = VIA_ALIASES.get(key)
    if via is None:
        raise QueryError("via 는 mindsdb, pg, tibero 만 됩니다.")
    return via


def _side_args(prefix: str, args: dict[str, Any], on: list[str]) -> dict[str, Any]:
    columns = args.get(f"{prefix}_columns")
    if columns is None:
        merged = None
    elif not isinstance(columns, list):
        raise QueryError(f"{prefix}_columns 는 배열이어야 합니다.")
    else:
        merged = [str(col) for col in columns]
        for key in on:
            if key not in merged:
                merged.append(key)
    return {
        "source_name": args.get(f"{prefix}_source_name"),
        "schema_name": args.get(f"{prefix}_schema_name"),
        "table_name": args.get(f"{prefix}_table_name"),
        "columns": merged,
        "filters": args.get(f"{prefix}_filters"),
        "order_by": args.get(f"{prefix}_order_by"),
        "limit": args.get(f"{prefix}_limit"),
    }


def _lookup_source(
    catalog: dict,
    schema_name: str,
    table_name: str,
) -> str | None:
    matches: list[str] = []
    for source in catalog.get("sources") or []:
        if not isinstance(source, dict):
            continue
        source_name = str(source.get("source_name") or "")
        source_schema = str(source.get("source_schema") or "")
        for table in source.get("tables") or []:
            if not isinstance(table, dict):
                continue
            schema = str(table.get("schema_name") or source_schema or "")
            name = str(table.get("table_name") or "")
            if schema.lower() == schema_name.lower() and name.lower() == table_name.lower():
                if source_name and source_name not in matches:
                    matches.append(source_name)
    return matches[0] if len(matches) == 1 else None


def catalog_fk_hints(catalog: dict) -> list[dict[str, Any]]:
    """카탈로그 컬럼의 references / referenced_by 만 모은다. infer-FK 를 만들지 않는다."""
    items: list[dict[str, Any]] = []
    for source in catalog.get("sources") or []:
        if not isinstance(source, dict):
            continue
        source_name = str(source.get("source_name") or "")
        source_schema = str(source.get("source_schema") or "")
        for table in source.get("tables") or []:
            if not isinstance(table, dict):
                continue
            schema_name = str(table.get("schema_name") or source_schema or "")
            table_name = str(table.get("table_name") or "")
            for col in table.get("columns") or []:
                if not isinstance(col, dict):
                    continue
                column_name = str(col.get("column_name") or "")
                ref = col.get("references")
                if isinstance(ref, dict) and ref.get("table_name") and ref.get("column_name"):
                    to_schema = str(ref.get("schema_name") or "")
                    to_table = str(ref.get("table_name") or "")
                    items.append(
                        {
                            "from": {
                                "source_name": source_name,
                                "schema_name": schema_name,
                                "table_name": table_name,
                                "column_name": column_name,
                            },
                            "to": {
                                "source_name": _lookup_source(catalog, to_schema, to_table),
                                "schema_name": to_schema,
                                "table_name": to_table,
                                "column_name": str(ref.get("column_name") or ""),
                            },
                            "constraint_name": ref.get("constraint_name"),
                            "via": "catalog-fk",
                        }
                    )
    return items


async def list_join_hints(settings: Settings, args: dict[str, Any]) -> dict:
    source_name, schema_name, table_name = _require_table_keys(args)
    catalog = await load_catalog(settings)
    table = _table_from_catalog(
        catalog, source_name, schema_name, table_name, engines={POSTGRES, TIBERO}
    )
    try:
        refs = await catalog_client.fetch_refs(
            settings.stone_meta_url,
            source_name=table.source_name,
            schema_name=table.schema_name,
            table_name=table.table_name,
        )
    except catalog_client.CatalogError as exc:
        raise QueryError(f"FK를 읽지 못했습니다. stone-meta-api POST /meta/ref. {exc}") from exc
    items: list[dict[str, Any]] = []
    for fk in refs:
        if not isinstance(fk, dict) or not fk.get("column_name"):
            continue
        to_schema = str(fk.get("ref_schema_name") or "")
        to_table = str(fk.get("ref_table_name") or "")
        items.append(
            {
                "from": {
                    "source_name": table.source_name,
                    "schema_name": table.schema_name,
                    "table_name": table.table_name,
                    "column_name": str(fk.get("column_name") or ""),
                },
                "to": {
                    "source_name": _lookup_source(catalog, to_schema, to_table),
                    "schema_name": to_schema,
                    "table_name": to_table,
                    "column_name": str(fk.get("ref_column_name") or ""),
                },
                "position": fk.get("position") or 1,
                "via": "meta-ref",
            }
        )
    return {
        "total": len(items),
        "items": items,
        "note": (
            "한 표의 /meta/ref 만 모았습니다. infer-FK·논리 동일 표 후보는 없습니다. "
            "전 표 힌트는 494회 호출이 되므로 표 키를 받습니다."
        ),
    }


async def join_tables(
    settings: Settings,
    store: CredentialStore,
    args: dict[str, Any],
) -> dict:
    try:
        left_on = assemble.normalize_on(args.get("left_on"))
        right_on = assemble.normalize_on(args.get("right_on"))
        how = assemble.parse_how(args.get("how"))
        left_via = _parse_via(args.get("left_via"))
        right_via = _parse_via(args.get("right_via"))
    except assemble.AssembleError as exc:
        raise QueryError(str(exc)) from exc

    left_args = _side_args("left", args, left_on)
    right_args = _side_args("right", args, right_on)
    left = await _query_via(settings, store, left_via, left_args)
    right = await _query_via(settings, store, right_via, right_args)

    try:
        items = assemble.join_rows(
            list(left.get("items") or []),
            list(right.get("items") or []),
            left_on=left_on,
            right_on=right_on,
            how=how,
        )
    except assemble.AssembleError as exc:
        raise QueryError(str(exc)) from exc

    log.info(
        "join_tables %s.%s + %s.%s how=%s rows=%s",
        left.get("schema_name"),
        left.get("table_name"),
        right.get("schema_name"),
        right.get("table_name"),
        how,
        len(items),
    )
    return {
        "via": VIA_ASSEMBLE,
        "how": how,
        "left": {
            **{key: left.get(key) for key in ("source_name", "schema_name", "table_name", "engine", "via")},
            "on": left_on,
            "fetched": len(left.get("items") or []),
        },
        "right": {
            **{key: right.get(key) for key in ("source_name", "schema_name", "table_name", "engine", "via")},
            "on": right_on,
            "fetched": len(right.get("items") or []),
        },
        "row_count": len(items),
        "items": items,
    }
