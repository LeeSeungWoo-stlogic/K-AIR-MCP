import asyncio

from app.assemble import AssembleError, join_rows, normalize_on
from app.settings import Settings
from app.tools import catalog_fk_hints, join_tables


def test_inner_join_matches_equal_keys():
    left = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    right = [{"owner_id": 2, "code": "x"}, {"owner_id": 3, "code": "y"}]
    items = join_rows(left, right, left_on=["id"], right_on=["owner_id"], how="inner")
    assert items == [{"left": {"id": 2, "name": "b"}, "right": {"owner_id": 2, "code": "x"}}]


def test_left_join_keeps_unmatched():
    left = [{"id": 1}, {"id": 2}]
    right = [{"owner_id": 2}]
    items = join_rows(left, right, left_on=["id"], right_on=["owner_id"], how="left")
    assert items == [
        {"left": {"id": 1}, "right": None},
        {"left": {"id": 2}, "right": {"owner_id": 2}},
    ]


def test_null_keys_do_not_match():
    items = join_rows(
        [{"id": None}],
        [{"owner_id": None}],
        left_on=["id"],
        right_on=["owner_id"],
        how="inner",
    )
    assert items == []


def test_normalize_on_rejects_empty():
    try:
        normalize_on(["", "  "])
    except AssembleError as exc:
        assert "조인 키" in str(exc)
    else:
        raise AssertionError("empty keys must fail")


def test_catalog_fk_hints_do_not_invent_edges():
    catalog = {
        "sources": [
            {
                "source_name": "SRC_A",
                "engine": "postgres",
                "tables": [
                    {
                        "schema_name": "s1",
                        "table_name": "child_t",
                        "columns": [
                            {
                                "column_name": "parent_id",
                                "references": {
                                    "schema_name": "s1",
                                    "table_name": "parent_t",
                                    "column_name": "id",
                                    "constraint_name": "fk_child_parent",
                                },
                            }
                        ],
                    },
                    {
                        "schema_name": "s1",
                        "table_name": "parent_t",
                        "columns": [{"column_name": "id"}],
                    },
                ],
            }
        ]
    }
    items = catalog_fk_hints(catalog)
    assert len(items) == 1
    assert items[0]["from"]["table_name"] == "child_t"
    assert items[0]["to"]["table_name"] == "parent_t"
    assert items[0]["to"]["source_name"] == "SRC_A"
    assert items[0]["via"] == "catalog-fk"


def test_catalog_fk_hints_empty_when_no_references():
    catalog = {
        "sources": [
            {
                "source_name": "SRC_A",
                "engine": "postgres",
                "tables": [
                    {
                        "schema_name": "s1",
                        "table_name": "alone_t",
                        "columns": [{"column_name": "id"}],
                    }
                ],
            }
        ]
    }
    assert catalog_fk_hints(catalog) == []


def test_join_tables_assembles_after_two_fetches(monkeypatch):
    settings = Settings(
        api_keys=("k",),
        stone_meta_url="http://stone",
        robo_meta_url="http://stone",
        nk_backend_url="http://nk",
        nk_backend_token="",
    )

    async def fake_query(_settings, _store, args):
        name = args["table_name"]
        if name == "left_t":
            return {
                "source_name": args["source_name"],
                "schema_name": args["schema_name"],
                "table_name": name,
                "engine": "postgres",
                "via": "mindsdb-query_execute",
                "items": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
            }
        return {
            "source_name": args["source_name"],
            "schema_name": args["schema_name"],
            "table_name": name,
            "engine": "postgres",
            "via": "postgres-direct",
            "items": [{"owner_id": 2, "code": "x"}],
        }

    monkeypatch.setattr("app.tools.query_table", fake_query)
    monkeypatch.setattr("app.tools.query_table_pg", fake_query)

    payload = asyncio.run(
        join_tables(
            settings,
            store=None,
            args={
                "left_source_name": "SRC_A",
                "left_schema_name": "s1",
                "left_table_name": "left_t",
                "left_on": "id",
                "left_via": "mindsdb",
                "right_source_name": "SRC_B",
                "right_schema_name": "s2",
                "right_table_name": "right_t",
                "right_on": "owner_id",
                "right_via": "pg",
            },
        )
    )
    assert payload["via"] == "mcp-assemble"
    assert payload["row_count"] == 1
    assert payload["left"]["via"] == "mindsdb-query_execute"
    assert payload["right"]["via"] == "postgres-direct"
    assert payload["items"][0]["left"]["name"] == "b"


def test_join_tables_injects_where_in_to_right(monkeypatch):
    settings = Settings(
        api_keys=("k",),
        stone_meta_url="http://stone",
        robo_meta_url="http://stone",
        nk_backend_url="http://nk",
        nk_backend_token="",
    )
    captured_right_filters = []

    async def fake_query(_settings, _store, args):
        name = args["table_name"]
        if name == "master_t":
            return {
                "source_name": args["source_name"],
                "schema_name": args["schema_name"],
                "table_name": name,
                "engine": "postgres",
                "via": "mindsdb-query_execute",
                "items": [{"code": "S01", "name": "팔당"}, {"code": "S02", "name": "성남"}],
            }
        captured_right_filters.extend(args.get("filters") or [])
        return {
            "source_name": args["source_name"],
            "schema_name": args["schema_name"],
            "table_name": name,
            "engine": "postgres",
            "via": "postgres-direct",
            "items": [{"site_cd": "S01", "turbidity": 0.12}],
        }

    monkeypatch.setattr("app.tools.query_table", fake_query)
    monkeypatch.setattr("app.tools.query_table_pg", fake_query)

    payload = asyncio.run(
        join_tables(
            settings,
            store=None,
            args={
                "left_source_name": "SRC_A",
                "left_schema_name": "s1",
                "left_table_name": "master_t",
                "left_on": "code",
                "left_via": "mindsdb",
                "right_source_name": "SRC_B",
                "right_schema_name": "s2",
                "right_table_name": "fact_t",
                "right_on": "site_cd",
                "right_via": "pg",
            },
        )
    )
    assert payload["status"] == "SUCCESS"
    assert payload["row_count"] == 1
    # 2단계 쿼리의 filters에 code in ['S01', 'S02']가 정상 주입되었는지 검증
    assert len(captured_right_filters) == 1
    assert captured_right_filters[0] == {"column": "site_cd", "op": "in", "value": ["S01", "S02"]}


def test_join_tables_returns_too_many_candidates(monkeypatch):
    settings = Settings(
        api_keys=("k",),
        stone_meta_url="http://stone",
        robo_meta_url="http://stone",
        nk_backend_url="http://nk",
        nk_backend_token="",
    )
    right_called = False

    async def fake_query(_settings, _store, args):
        nonlocal right_called
        name = args["table_name"]
        if name == "master_t":
            # 5개의 다른 키를 반환
            return {
                "source_name": args["source_name"],
                "schema_name": args["schema_name"],
                "table_name": name,
                "engine": "postgres",
                "via": "mindsdb-query_execute",
                "items": [{"code": f"S0{i}"} for i in range(5)],
            }
        right_called = True
        return {"items": []}

    monkeypatch.setattr("app.tools.query_table", fake_query)
    monkeypatch.setattr("app.tools.query_table_pg", fake_query)

    # max_in_keys를 3으로 제한
    payload = asyncio.run(
        join_tables(
            settings,
            store=None,
            args={
                "left_source_name": "SRC_A",
                "left_schema_name": "s1",
                "left_table_name": "master_t",
                "left_on": "code",
                "left_via": "mindsdb",
                "right_source_name": "SRC_B",
                "right_schema_name": "s2",
                "right_table_name": "fact_t",
                "right_on": "site_cd",
                "right_via": "pg",
                "max_in_keys": 3,
            },
        )
    )
    assert payload["status"] == "TOO_MANY_CANDIDATES"
    assert payload["candidate_count"] == 5
    assert payload["threshold"] == 3
    assert not right_called
    assert "안전 상한(3건)을 초과" in payload["message"]

