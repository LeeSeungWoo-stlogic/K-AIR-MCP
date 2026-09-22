"""조회 결과를 MCP 프로세스에서 붙인다. SQL 조인을 엔진에 보내지 않는다."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class AssembleError(ValueError):
    pass


def normalize_on(raw: Any) -> list[str]:
    if raw is None:
        raise AssembleError("조인 키가 필요합니다.")
    if isinstance(raw, str):
        keys = [raw.strip()] if raw.strip() else []
    elif isinstance(raw, list):
        keys = [str(item).strip() for item in raw if str(item).strip()]
    else:
        raise AssembleError("조인 키는 컬럼명 또는 컬럼명 배열이어야 합니다.")
    if not keys:
        raise AssembleError("조인 키가 필요합니다.")
    return keys


def extract_distinct_keys(rows: list[dict[str, Any]], column: str) -> list[Any]:
    """행 목록에서 특정 컬럼의 고유 값(None 제외)을 순서를 보존하며 추출한다."""
    seen = set()
    result: list[Any] = []
    col_lower = str(column).strip().lower()
    for row in rows:
        if not isinstance(row, dict):
            continue
        lower_map = {str(k).lower(): v for k, v in row.items()}
        val = lower_map.get(col_lower)
        if val is not None and val not in seen:
            seen.add(val)
            result.append(val)
    return result


def join_key(row: dict[str, Any], columns: list[str]) -> tuple[Any, ...] | None:
    values: list[Any] = []
    lower = {str(name).lower(): value for name, value in row.items()}
    for column in columns:
        if column.lower() not in lower:
            return None
        value = lower[column.lower()]
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def parse_how(raw: Any) -> str:
    method = str(raw or "inner").strip().lower()
    if method not in {"inner", "left"}:
        raise AssembleError("how 는 inner 또는 left 만 됩니다.")
    return method


def join_rows(
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    *,
    left_on: list[str],
    right_on: list[str],
    how: str = "inner",
) -> list[dict[str, Any]]:
    if len(left_on) != len(right_on):
        raise AssembleError("left_on 과 right_on 의 길이가 같아야 합니다.")
    method = parse_how(how)

    index: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in right_rows:
        key = join_key(row, right_on)
        if key is None:
            continue
        index[key].append(row)

    items: list[dict[str, Any]] = []
    for left in left_rows:
        key = join_key(left, left_on)
        matches = index.get(key, []) if key is not None else []
        if matches:
            for right in matches:
                items.append({"left": left, "right": right})
        elif method == "left":
            items.append({"left": left, "right": None})
    return items
