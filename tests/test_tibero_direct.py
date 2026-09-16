from app.engine import TIBERO, is_tibero
from app.filters import Filter
from app.intersect import catalog_tables
from app.sources_client import parse_tibero_endpoints
from app.sqlutil import assemble_select_bound
from app.tibero_runner import QueryRunError, jdbc_url
from app.sources_client import SourceEndpoint


def test_is_tibero_engine():
    assert is_tibero("Tibero")
    assert is_tibero("tibero")
    assert not is_tibero("postgres")


def test_catalog_tables_can_keep_tibero():
    catalog = {
        "sources": [
            {
                "source_name": "HDAPS",
                "engine": "tibero",
                "tables": [
                    {
                        "schema_name": "NBEAVER",
                        "table_name": "DAMCD",
                        "columns": [{"column_name": "DAMCD"}],
                    }
                ],
            },
            {
                "source_name": "SRC_PG",
                "engine": "postgres",
                "tables": [
                    {
                        "schema_name": "s1",
                        "table_name": "t1",
                        "columns": [{"column_name": "id"}],
                    }
                ],
            },
        ]
    }
    only_tb = catalog_tables(catalog, engines={TIBERO})
    assert len(only_tb) == 1
    assert only_tb[0].engine == "tibero"
    assert only_tb[0].table_name == "DAMCD"
    assert catalog_tables(catalog, postgres_only=True)[0].engine == "postgres"


def test_parse_tibero_endpoint_uses_sid():
    endpoints = parse_tibero_endpoints(
        {
            "datasources": [
                {
                    "name": "HDAPS",
                    "engine": "tibero",
                    "host": "172.18.0.1",
                    "port": 11629,
                    "sid": "tibero",
                    "schema": "NBEAVER",
                    "enabled": True,
                }
            ]
        }
    )
    assert len(endpoints) == 1
    assert endpoints[0].database == "tibero"
    assert endpoints[0].port == 11629
    assert endpoints[0].engine == "tibero"


def test_jdbc_url_thin():
    url = jdbc_url(
        SourceEndpoint(
            source_id="HDAPS",
            source_name="HDAPS",
            engine="tibero",
            host="172.18.0.1",
            port=11629,
            database="tibero",
            schema_name="NBEAVER",
            schema_scope=("NBEAVER",),
            enabled=True,
        )
    )
    assert url == "jdbc:tibero:thin:@172.18.0.1:11629:tibero"


def test_jdbc_url_rejects_bad_host():
    try:
        jdbc_url(
            SourceEndpoint(
                source_id="X",
                source_name="X",
                engine="tibero",
                host="bad;host",
                port=1629,
                database="tibero",
                schema_name="",
                schema_scope=(),
                enabled=True,
            )
        )
    except QueryRunError:
        return
    raise AssertionError("bad host must fail")


def test_assemble_select_tibero_uses_qmark_and_rownum():
    sql, params = assemble_select_bound(
        "NBEAVER",
        "DAMCD",
        ["DAMCD"],
        [Filter(column="DAMCD", op="eq", value="A")],
        [],
        5,
        dialect="tibero",
    )
    assert "ROWNUM <= 5" in sql
    assert "?" in sql
    assert "$1" not in sql
    assert "LIMIT" not in sql
    assert params == ("A",)
