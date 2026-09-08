from app import intersect
from app.engine import POSTGRES, TIBERO


def test_catalog_engines_and_schemas():
    catalog = {
        "sources": [
            {
                "source_name": "rwis",
                "engine": "oracle",
                "source_schema": "RWIS",
                "tables": [{"table_name": "T", "schema_name": "RWIS", "columns": [{"column_name": "A"}]}],
            },
            {
                "source_name": "mart",
                "engine": "postgresql",
                "source_schema": "rwis_mart",
                "tables": [{"table_name": "fct", "columns": [{"column_name": "v"}]}],
            },
        ]
    }
    assert intersect.catalog_engines(catalog) == {POSTGRES, TIBERO}
    assert intersect.catalog_schemas(catalog, TIBERO) == {"RWIS"}
    assert intersect.catalog_schemas(catalog, POSTGRES) == {"rwis_mart"}


def test_empty_catalog_yields_nothing():
    assert intersect.catalog_tables({"sources": []}) == []


def test_catalog_tables_copies_logical_name_and_description():
    catalog = {
        "sources": [
            {
                "source_name": "rwis_mart",
                "engine": "postgresql",
                "source_schema": "rwis_mart",
                "tables": [
                    {
                        "table_name": "fct_measure_day",
                        "logical_name": "일 계측 팩트",
                        "description": "태그별 일 집계값",
                        "columns": [{"column_name": "tagsn"}],
                    }
                ],
            }
        ]
    }
    allowed = intersect.catalog_tables(catalog)
    assert allowed[0].logical_name == "일 계측 팩트"
    assert allowed[0].description == "태그별 일 집계값"
    assert intersect.catalog_column_logical_name({"logical_name": "집계일"}) == "집계일"


def test_catalog_tables_keeps_registered_table():
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
    allowed = intersect.catalog_tables(catalog)
    assert len(allowed) == 1
    assert allowed[0].engine == POSTGRES
    assert allowed[0].columns == ("TAGSN", "MISSING")
    assert allowed[0].physical_columns == ("TAGSN", "MISSING")


def test_catalog_tables_keeps_unmapped_engine():
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
    allowed = intersect.catalog_tables(catalog)
    assert len(allowed) == 1
    assert allowed[0].engine == "mysql"


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
