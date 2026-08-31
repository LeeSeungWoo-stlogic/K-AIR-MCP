from __future__ import annotations

from dataclasses import dataclass

from .engine import normalize_engine


def catalog_engines(catalog: dict) -> set[str]:
    sources = catalog.get("sources") if isinstance(catalog, dict) else None
    if not sources:
        return set()
    engines: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        engine = normalize_engine(source.get("engine"))
        if engine:
            engines.add(engine)
    return engines


def catalog_schemas(catalog: dict, engine: str) -> set[str]:
    sources = catalog.get("sources") if isinstance(catalog, dict) else None
    if not sources:
        return set()
    schemas: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        if normalize_engine(source.get("engine")) != engine:
            continue
        source_schema = str(source.get("source_schema") or "").strip()
        if source_schema:
            schemas.add(source_schema)
        for table in source.get("tables") or []:
            if not isinstance(table, dict):
                continue
            schema_name = str(table.get("schema_name") or source_schema or "").strip()
            if schema_name:
                schemas.add(schema_name)
    return schemas


@dataclass(frozen=True)
class EngineInventory:
    tables: set[tuple[str, str]]
    columns: dict[tuple[str, str], tuple[str, ...]]


@dataclass(frozen=True)
class AllowedTable:
    source_name: str
    schema_name: str
    table_name: str
    engine: str
    physical_schema: str
    physical_table: str
    columns: tuple[str, ...]
    physical_columns: tuple[str, ...]


def _key(schema: str, table: str) -> tuple[str, str]:
    return (schema.lower(), table.lower())


def intersect_catalog(
    catalog: dict,
    inventories: dict[str, EngineInventory],
) -> list[AllowedTable]:
    sources = catalog.get("sources") if isinstance(catalog, dict) else None
    if not sources:
        return []

    allowed: list[AllowedTable] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        engine = normalize_engine(source.get("engine"))
        if engine is None:
            continue
        inventory = inventories.get(engine)
        if inventory is None:
            continue
        source_name = str(source.get("source_name") or "")
        source_schema = str(source.get("source_schema") or "")
        by_key = {_key(schema, table): (schema, table) for schema, table in inventory.tables}
        for table in source.get("tables") or []:
            if not isinstance(table, dict):
                continue
            schema_name = str(table.get("schema_name") or source_schema or "")
            table_name = str(table.get("table_name") or "")
            if not source_name or not schema_name or not table_name:
                continue
            actual = by_key.get(_key(schema_name, table_name))
            if actual is None:
                continue
            catalog_cols = [
                str(col.get("column_name") or "")
                for col in (table.get("columns") or [])
                if isinstance(col, dict) and col.get("column_name")
            ]
            actual_cols = inventory.columns.get(actual, ())
            actual_by_key = {name.lower(): name for name in actual_cols}
            kept_catalog: list[str] = []
            kept_physical: list[str] = []
            for col in catalog_cols:
                physical = actual_by_key.get(col.lower())
                if physical and physical not in kept_physical:
                    kept_catalog.append(col)
                    kept_physical.append(physical)
            if not kept_physical:
                continue
            allowed.append(
                AllowedTable(
                    source_name=source_name,
                    schema_name=schema_name,
                    table_name=table_name,
                    engine=engine,
                    physical_schema=actual[0],
                    physical_table=actual[1],
                    columns=tuple(kept_catalog),
                    physical_columns=tuple(kept_physical),
                )
            )
    return allowed


def find_table(
    allowed: list[AllowedTable],
    source_name: str,
    schema_name: str,
    table_name: str,
) -> AllowedTable | None:
    source_key = source_name.lower()
    schema_key = schema_name.lower()
    table_key = table_name.lower()
    matches = [
        item
        for item in allowed
        if item.source_name.lower() == source_key
        and item.schema_name.lower() == schema_key
        and item.table_name.lower() == table_key
    ]
    return matches[0] if matches else None


def find_catalog_table(
    catalog: dict,
    source_name: str,
    schema_name: str,
    table_name: str,
) -> dict | None:
    sources = catalog.get("sources") if isinstance(catalog, dict) else None
    if not sources:
        return None
    source_key = source_name.lower()
    schema_key = schema_name.lower()
    table_key = table_name.lower()
    for source in sources:
        if not isinstance(source, dict):
            continue
        if str(source.get("source_name") or "").lower() != source_key:
            continue
        source_schema = str(source.get("source_schema") or "")
        for table in source.get("tables") or []:
            if not isinstance(table, dict):
                continue
            schema = str(table.get("schema_name") or source_schema or "")
            name = str(table.get("table_name") or "")
            if schema.lower() == schema_key and name.lower() == table_key:
                return table
    return None


def resolve_columns(table: AllowedTable, requested: list[str] | None) -> list[str]:
    physical_by_key = {name.lower(): name for name in table.physical_columns}
    if not requested:
        return list(table.physical_columns)
    resolved: list[str] = []
    for name in requested:
        physical = physical_by_key.get(str(name).lower())
        if physical is None:
            raise KeyError(name)
        if physical not in resolved:
            resolved.append(physical)
    return resolved
