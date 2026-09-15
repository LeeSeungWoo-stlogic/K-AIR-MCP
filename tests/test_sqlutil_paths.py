from app.filters import Filter
from app.sqlutil import assemble_select_bound, from_sql


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
    assert "tag_id" in sql
    assert params == ()
