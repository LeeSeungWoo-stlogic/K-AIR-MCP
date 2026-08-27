from app import filters, sqlutil
from app.errors import IdentError


def test_reject_sql_string_filters():
    try:
        filters.parse_filters("suj_code = 'A'")
    except IdentError:
        return
    raise AssertionError("SQL string filters must fail")


def test_reject_unknown_op():
    try:
        filters.parse_filters([{"column": "a", "op": "between", "value": 1}])
    except IdentError:
        return
    raise AssertionError("unknown op must fail")


def test_assemble_bound_eq_and_order():
    parsed = filters.parse_filters([{"column": "suj_code", "op": "eq", "value": "X"}])
    order = filters.parse_order([{"column": "measure_month", "dir": "desc"}])
    sql, params = sqlutil.assemble_select_bound(
        "rwis_mart",
        "fct_measure_month",
        ["suj_code", "measure_value"],
        parsed,
        order,
        20,
    )
    assert sql == (
        'SELECT "suj_code", "measure_value" FROM "rwis_mart"."fct_measure_month" '
        'WHERE "suj_code" = %s ORDER BY "measure_month" DESC LIMIT 20'
    )
    assert params == ("X",)


def test_reject_sql_string_order():
    try:
        filters.parse_order("created_at DESC")
    except IdentError:
        return
    raise AssertionError("SQL string order must fail")
