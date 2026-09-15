from app.execute_client import rows_as_dicts


def test_rows_as_dicts_from_columns_and_lists():
    rows = rows_as_dicts({"columns": ["a", "b"], "rows": [[1, 2], {"a": 3, "b": 4}]})
    assert rows == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
