from __future__ import annotations

from dataclasses import dataclass

from .engine import POSTGRES, normalize_engine


def _slot_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def catalog_table_logical_name(table: dict) -> str:
    return _slot_text(table.get("logical_name"), table.get("comment"))


def catalog_table_description(table: dict) -> str:
    return _slot_text(table.get("description"))


def catalog_column_logical_name(column: dict) -> str:
    return _slot_text(column.get("logical_name"), column.get("comment"))


@dataclass(frozen=True)
class AllowedTable:
    source_name: str
    schema_name: str
    table_name: str
    engine: str
    columns: tuple[str, ...]
    logical_name: str = ""
    description: str = ""


def catalog_tables(
    catalog: dict,
    *,
    postgres_only: bool = True,
    engines: set[str] | None = None,
) -> list[AllowedTable]:
    sources = catalog.get("sources") if isinstance(catalog, dict) else None
    if not sources:
        return []
    wanted = engines
    if wanted is None and postgres_only:
        wanted = {POSTGRES}

    allowed: list[AllowedTable] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        engine = normalize_engine(source.get("engine"))
        if engine is None:
            continue
        if wanted is not None and engine not in wanted:
            continue
        source_name = str(source.get("source_name") or "")
        source_schema = str(source.get("source_schema") or "")
        for table in source.get("tables") or []:
            if not isinstance(table, dict):
                continue
            schema_name = str(table.get("schema_name") or source_schema or "")
            table_name = str(table.get("table_name") or "")
            if not source_name or not schema_name or not table_name:
                continue
            catalog_cols = [
                str(col.get("column_name") or "")
                for col in (table.get("columns") or [])
                if isinstance(col, dict) and col.get("column_name")
            ]
            allowed.append(
                AllowedTable(
                    source_name=source_name,
                    schema_name=schema_name,
                    table_name=table_name,
                    engine=engine,
                    columns=tuple(catalog_cols),
                    logical_name=catalog_table_logical_name(table),
                    description=catalog_table_description(table),
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
    physical_by_key = {name.lower(): name for name in table.columns}
    if not requested:
        return list(table.columns)
    resolved: list[str] = []
    for name in requested:
        physical = physical_by_key.get(str(name).lower())
        if physical is None:
            raise KeyError(name)
        if physical not in resolved:
            resolved.append(physical)
    return resolved
