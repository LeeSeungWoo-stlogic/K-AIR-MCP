from app import intersect
from app.engine import POSTGRES, TIBERO


def _pg(tables, columns):
    return {
        POSTGRES: intersect.EngineInventory(tables=tables, columns=columns),
        TIBERO: intersect.EngineInventory(tables=set(), columns={}),
    }


def test_empty_catalog_yields_nothing():
    allowed = intersect.intersect_catalog({"sources": []}, _pg({("RWIS", "T")}, {("RWIS", "T"): ("A",)}))
    assert allowed == []


def test_pg_only_table_is_excluded():
    catalog = {
        "sources": [
            {
                "source_name": "rwis",
                "engine": "postgresql",
                "source_schema": "RWIS",
                "tables": [
                    {
                        "table_name": "CAT_ONLY",
                        "columns": [{"column_name": "A"}],
                    }
                ],
            }
        ]
    }
    allowed = intersect.intersect_catalog(
        catalog, _pg({("RWIS", "PG_ONLY")}, {("RWIS", "PG_ONLY"): ("A",)})
    )
    assert allowed == []


def test_intersection_keeps_matching_table_and_columns():
    catalog = {
        "sources": [
            {
                "source_name": "rwis",
                "engine": "postgresql",
                "source_schema": "RWIS",
                "tables": [
                    {
                        "table_name": "RDITAG_TB",
                        "columns": [{"column_name": "TAGSN"}, {"column_name": "MISSING"}],
                    }
                ],
            }
        ]
    }
    allowed = intersect.intersect_catalog(
        catalog,
        _pg({("RWIS", "RDITAG_TB")}, {("RWIS", "RDITAG_TB"): ("TAGSN", "OTHER")}),
    )
    assert len(allowed) == 1
    assert allowed[0].engine == POSTGRES
    assert allowed[0].physical_columns == ("TAGSN",)
    assert allowed[0].columns == ("TAGSN",)


def test_tibero_source_does_not_use_postgres_inventory():
    catalog = {
        "sources": [
            {
                "source_name": "rwis",
                "engine": "oracle",
                "source_schema": "RWIS",
                "tables": [
                    {
                        "table_name": "RDITAG_TB",
                        "columns": [{"column_name": "TAGSN"}],
                    }
                ],
            }
        ]
    }
    allowed = intersect.intersect_catalog(
        catalog,
        _pg({("RWIS", "RDITAG_TB")}, {("RWIS", "RDITAG_TB"): ("TAGSN",)}),
    )
    assert allowed == []


def test_oracle_engine_intersects_tibero_inventory():
    catalog = {
        "sources": [
            {
                "source_name": "rwis",
                "engine": "oracle",
                "source_schema": "RWIS",
                "tables": [
                    {
                        "table_name": "RDITAG_TB",
                        "columns": [{"column_name": "TAGSN"}],
                    }
                ],
            }
        ]
    }
    inventories = {
        POSTGRES: intersect.EngineInventory(tables=set(), columns={}),
        TIBERO: intersect.EngineInventory(
            tables={("RWIS", "RDITAG_TB")},
            columns={("RWIS", "RDITAG_TB"): ("TAGSN",)},
        ),
    }
    allowed = intersect.intersect_catalog(catalog, inventories)
    assert len(allowed) == 1
    assert allowed[0].engine == TIBERO
    assert allowed[0].physical_columns == ("TAGSN",)


def test_unknown_engine_is_skipped():
    catalog = {
        "sources": [
            {
                "source_name": "other",
                "engine": "mysql",
                "source_schema": "s",
                "tables": [{"table_name": "t", "columns": [{"column_name": "A"}]}],
            }
        ]
    }
    allowed = intersect.intersect_catalog(
        catalog, _pg({("s", "t")}, {("s", "t"): ("A",)})
    )
    assert allowed == []


def test_missing_engine_is_skipped():
    catalog = {
        "sources": [
            {
                "source_name": "rwis",
                "source_schema": "RWIS",
                "tables": [{"table_name": "T", "columns": [{"column_name": "A"}]}],
            }
        ]
    }
    allowed = intersect.intersect_catalog(
        catalog, _pg({("RWIS", "T")}, {("RWIS", "T"): ("A",)})
    )
    assert allowed == []


def test_unknown_column_rejected():
    table = intersect.AllowedTable(
        source_name="rwis",
        schema_name="RWIS",
        table_name="T",
        engine=POSTGRES,
        physical_schema="RWIS",
        physical_table="T",
        columns=("A",),
        physical_columns=("A",),
    )
    try:
        intersect.resolve_columns(table, ["B"])
    except KeyError:
        return
    raise AssertionError("expected KeyError")
