from app.filters import Filter
from app.sqlutil import assemble_aggregate, assemble_distinct, assemble_select_bound, from_sql


def test_from_sql_mindsdb_uses_three_part_ticks():
    assert from_sql("rwis_mart", "dim_tag", "RWIS") == "`RWIS`.`rwis_mart`.`dim_tag`"


def test_from_sql_pg_uses_schema_table_quotes():
    assert from_sql("rwis_mart", "dim_tag") == '"rwis_mart"."dim_tag"'


def test_assemble_select_pg_uses_placeholders():
    sql, params = assemble_select_bound(
        "rwis",
        "rditag_tb",
        ["tag_id"],
        [Filter(column="tag_id", op="eq", value="A")],
        [],
        5,
        source=None,
        inline=False,
    )
    assert '"rwis"."rditag_tb"' in sql
    assert "$1" in sql
    assert params == ("A",)


def test_assemble_select_mindsdb_inlines_and_keeps_source():
    sql, params = assemble_select_bound(
        "rwis_mart",
        "dim_tag",
        ["tag_id"],
        [Filter(column="tag_id", op="eq", value="A")],
        [],
        5,
        source="RWIS",
        inline=True,
    )
    assert "`RWIS`.`rwis_mart`.`dim_tag`" in sql
    assert "`tag_id`" in sql
    assert '"tag_id"' not in sql
    assert params == ()


def test_assemble_aggregate_mindsdb_does_not_quote_columns_as_strings():
    sql, params = assemble_aggregate(
        "rwis",
        "some_tb",
        "count",
        None,
        [],
        1,
        [Filter(column="suj_name", op="eq", value="충주정수장")],
        source="RWIS",
        inline=True,
    )
    assert "`suj_name` = '충주정수장'" in sql
    assert '"suj_name"' not in sql
    assert params == ()


def test_assemble_aggregate_pg_uses_schema_quotes_and_placeholders():
    sql, params = assemble_aggregate(
        "rwis_mart",
        "dim_tag",
        "count",
        None,
        [],
        1,
        [Filter(column="suj_name", op="eq", value="충주정수장")],
        source=None,
        inline=False,
    )
    assert 'SELECT COUNT(*) AS row_count FROM "rwis_mart"."dim_tag"' in sql
    assert '"suj_name" = $1' in sql
    assert "`suj_name`" not in sql
    assert params == ("충주정수장",)


def test_assemble_distinct_mindsdb_uses_ticks():
    sql = assemble_distinct("rwis", "some_tb", "suj_name", 10, source="RWIS")
    assert "`suj_name`" in sql
    assert '"suj_name"' not in sql
