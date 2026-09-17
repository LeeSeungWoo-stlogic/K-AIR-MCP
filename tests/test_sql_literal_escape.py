import pytest

from app.errors import IdentError
from app.filters import Filter
from app.sqlutil import assemble_select_bound, sql_literal


def test_sql_literal_doubles_quote_and_backslash():
    assert sql_literal("a'b") == "'a''b'"
    assert sql_literal(r"a\b") == r"'a\\b'"
    # \' 페이로드: 백슬래시가 따옴표를 이스케이프해 문자열 밖으로 나가면 안 된다.
    assert sql_literal(r"x\' OR 1=1 -- ") == r"'x\\'' OR 1=1 -- '"


def _closes_at_end_mysql(literal: str) -> bool:
    """MySQL 규칙(백슬래시 이스케이프, '' 이스케이프)으로 읽어 리터럴이 정확히 마지막 글자에서 닫히는지."""
    assert literal[0] == "'"
    i = 1
    while i < len(literal):
        ch = literal[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "'":
            if i + 1 < len(literal) and literal[i + 1] == "'":
                i += 2
                continue
            return i == len(literal) - 1
        i += 1
    return False


@pytest.mark.parametrize("payload", [r"\'", r"x\' OR 1=1 -- ", r"\\'", "'\\", r"a\\\'b", "\\", "it's"])
def test_mindsdb_literal_stays_closed_under_mysql_rules(payload):
    assert _closes_at_end_mysql(sql_literal(payload))


def test_old_escaping_would_break_out():
    # 회귀 확인용: 따옴표만 두 배로 하면 \' 페이로드가 리터럴을 일찍 닫는다.
    old = "'" + r"x\' OR 1=1 -- ".replace("'", "''") + "'"
    assert not _closes_at_end_mysql(old)


def test_mindsdb_select_inlines_escaped_payload():
    sql, params = assemble_select_bound(
        "rwis", "t", ["a"], [Filter(column="a", op="eq", value=r"\' OR 1=1 -- ")], [], 5,
        source="RWIS", inline=True,
    )
    assert r"`a` = '\\'' OR 1=1 -- '" in sql
    assert params == ()


def test_sql_literal_rejects_nul():
    with pytest.raises(IdentError):
        sql_literal("a\x00b")
