from app.intersect import catalog_tables, find_table


def test_catalog_tables_use_table_schema_not_source_slot():
    catalog = {
        "sources": [
            {
                "source_name": "RWIS",
                "engine": "postgres",
                "source_schema": "rwis",
                "tables": [
                    {
                        "table_name": "rditag_tb",
                        "schema_name": "rwis",
                        "columns": [{"column_name": "tag_id"}],
                    },
                    {
                        "table_name": "dim_tag",
                        "schema_name": "rwis_mart",
                        "columns": [{"column_name": "tag_id"}],
                    },
                ],
            }
        ]
    }
    allowed = catalog_tables(catalog)
    assert find_table(allowed, "RWIS", "rwis", "rditag_tb") is not None
    assert find_table(allowed, "RWIS", "rwis_mart", "dim_tag") is not None
    assert find_table(allowed, "RWIS", "rwis", "dim_tag") is None
