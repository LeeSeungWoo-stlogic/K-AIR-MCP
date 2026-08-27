from app import sqlutil


def test_assemble_select_quotes_and_limit():
    sql = sqlutil.assemble_select("RWIS", "RDITAG_TB", ["TAGSN", "TAGNM"], 20)
    assert sql == 'SELECT "TAGSN", "TAGNM" FROM "RWIS"."RDITAG_TB" LIMIT 20'


def test_reject_injection_in_ident():
    for bad in ("x;drop", 'x"y', "a.b", "x\\y"):
        try:
            sqlutil.quote_ident(bad)
        except sqlutil.IdentError:
            continue
        raise AssertionError(bad)


def test_does_not_run_user_sql():
    try:
        sqlutil.assemble_select("public", "t", [], 10)
    except sqlutil.IdentError:
        return
    raise AssertionError("empty columns must fail")


def test_clamp_limit():
    assert sqlutil.clamp_limit("999", 50, 200) == 200
    assert sqlutil.clamp_limit("nope", 50, 200) == 50
    assert sqlutil.clamp_limit(0, 50, 200) == 1


def test_assemble_count_star():
    sql = sqlutil.assemble_aggregate("RWIS", "RDITAG_TB", "count", None, [], 1)
    assert sql == 'SELECT COUNT(*) AS row_count FROM "RWIS"."RDITAG_TB" LIMIT 1'


def test_assemble_avg_with_group():
    sql = sqlutil.assemble_aggregate("rwis_mart", "fct", "avg", "measure_value", ["suj_code"], 20)
    assert sql == (
        'SELECT "suj_code", AVG("measure_value") AS value '
        'FROM "rwis_mart"."fct" GROUP BY "suj_code" LIMIT 20'
    )


def test_assemble_aggregate_rejects_unknown_func():
    try:
        sqlutil.assemble_aggregate("s", "t", "drop", None, [], 1)
    except sqlutil.IdentError:
        return
    raise AssertionError("unknown func must fail")


def test_assemble_sum_requires_column():
    try:
        sqlutil.assemble_aggregate("s", "t", "sum", None, [], 1)
    except sqlutil.IdentError:
        return
    raise AssertionError("sum without column must fail")


def test_tibero_filters_use_jdbc_placeholders():
    from app.filters import Filter

    sql, params = sqlutil.assemble_select_bound(
        "RWIS",
        "T",
        ["A"],
        [Filter(column="A", op="eq", value="x")],
        [],
        5,
        "tibero",
    )
    assert "?" in sql and "%s" not in sql
    assert sql.endswith("FETCH FIRST 5 ROWS ONLY")
    assert params == ("x",)


def test_tibero_uses_fetch_first():
    sql = sqlutil.assemble_select("RWIS", "RDITAG_TB", ["TAGSN"], 20, "tibero")
    assert sql == 'SELECT "TAGSN" FROM "RWIS"."RDITAG_TB" FETCH FIRST 20 ROWS ONLY'
    distinct = sqlutil.assemble_distinct("RWIS", "T", "A", 10, "tibero")
    assert distinct.endswith("FETCH FIRST 10 ROWS ONLY")
    agg = sqlutil.assemble_aggregate("RWIS", "T", "count", None, [], 1, "tibero")
    assert agg.endswith("FETCH FIRST 1 ROWS ONLY")
