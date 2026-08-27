from app.engine import POSTGRES, TIBERO, normalize_engine


def test_normalize_postgres_aliases():
    assert normalize_engine("postgresql") == POSTGRES
    assert normalize_engine("Postgres") == POSTGRES
    assert normalize_engine("postgis") == POSTGRES


def test_normalize_tibero_aliases():
    assert normalize_engine("tibero") == TIBERO
    assert normalize_engine("oracle") == TIBERO
    assert normalize_engine("TIBERO7") == TIBERO


def test_unknown_engine_is_none():
    assert normalize_engine("mysql") is None
    assert normalize_engine("") is None
    assert normalize_engine(None) is None
