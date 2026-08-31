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


def test_assemble_exec_select_backticks_and_literals():
    from app.filters import Filter, Order

    sql = sqlutil.assemble_exec_select(
        "rwis_mart",
        "rwis_mart",
        "fct_measure_month",
        ["suj_code", "measure_value"],
        [Filter(column="suj_code", op="eq", value="충주정수장")],
        [Order(column="measure_month", direction="desc")],
        20,
    )
    assert sql == (
        "SELECT `suj_code`, `measure_value` "
        "FROM `rwis_mart`.`rwis_mart`.`fct_measure_month` "
        "WHERE `suj_code` = '충주정수장' "
        "ORDER BY `measure_month` DESC LIMIT 20"
    )
    assert "%s" not in sql


def test_assemble_exec_select_escapes_quote_and_in():
    from app.filters import Filter

    sql = sqlutil.assemble_exec_select(
        "src",
        "sch",
        "tbl",
        ["name"],
        [Filter(column="name", op="in", value=["O'Brien", "A"])],
        [],
        5,
    )
    assert sql == (
        "SELECT `name` FROM `src`.`sch`.`tbl` "
        "WHERE `name` IN ('O''Brien', 'A') LIMIT 5"
    )


def test_assemble_exec_distinct():
    sql = sqlutil.assemble_exec_distinct("src", "sch", "tbl", "metric_name", 50)
    assert sql == (
        "SELECT DISTINCT `metric_name` AS `value` "
        "FROM `src`.`sch`.`tbl` "
        "WHERE `metric_name` IS NOT NULL "
        "ORDER BY 1 LIMIT 50"
    )


def test_assemble_exec_aggregate_count_and_avg():
    count_sql = sqlutil.assemble_exec_aggregate("src", "sch", "tbl", "count", None, [], 1)
    assert count_sql == "SELECT COUNT(*) AS `row_count` FROM `src`.`sch`.`tbl` LIMIT 1"
    avg_sql = sqlutil.assemble_exec_aggregate(
        "src", "sch", "tbl", "avg", "measure_value", ["suj_code"], 20
    )
    assert avg_sql == (
        "SELECT `suj_code`, AVG(`measure_value`) AS `value` "
        "FROM `src`.`sch`.`tbl` GROUP BY `suj_code` LIMIT 20"
    )


def test_assemble_exec_aggregate_with_filter():
    from app.filters import Filter

    sql = sqlutil.assemble_exec_aggregate(
        "src",
        "sch",
        "tbl",
        "count",
        None,
        ["fclty_code"],
        50,
        [Filter(column="basin_name", op="like", value="%한강%")],
    )
    assert sql == (
        "SELECT `fclty_code`, COUNT(*) AS `row_count` "
        "FROM `src`.`sch`.`tbl` "
        "WHERE `basin_name` LIKE '%한강%' "
        "GROUP BY `fclty_code` LIMIT 50"
    )
    assert "%s" not in sql


def test_quote_ident_exec_rejects_bad():
    for bad in ("x;drop", "x`y", 'x"y', "a.b", "x\\y"):
        try:
            sqlutil.quote_ident_exec(bad)
        except sqlutil.IdentError:
            continue
        raise AssertionError(bad)
