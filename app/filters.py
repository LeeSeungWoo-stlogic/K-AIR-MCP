from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import IdentError

OPS = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "like": "LIKE",
    "in": "IN",
    "is_null": "IS NULL",
    "is_not_null": "IS NOT NULL",
}


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    value: Any = None


@dataclass(frozen=True)
class Order:
    column: str
    direction: str


def parse_filters(raw: Any) -> list[Filter]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raise IdentError("filters 는 SQL 문자열이 아니라 {column, op, value} 배열이다")
    if not isinstance(raw, list):
        raise IdentError("filters 는 배열이어야 한다")
    out: list[Filter] = []
    for item in raw:
        if not isinstance(item, dict):
            raise IdentError("filter 항목은 객체여야 한다")
        column = str(item.get("column") or "").strip()
        op = str(item.get("op") or "").strip().lower()
        if not column or op not in OPS:
            raise IdentError("filter 는 허용된 column 과 op 가 필요하다")
        value = item.get("value")
        if op in {"is_null", "is_not_null"}:
            out.append(Filter(column=column, op=op))
            continue
        if op == "in":
            if not isinstance(value, list) or not value:
                raise IdentError("op=in 은 비어 있지 않은 배열 value 가 필요하다")
            out.append(Filter(column=column, op=op, value=value))
            continue
        if value is None:
            raise IdentError("filter value 가 필요하다")
        out.append(Filter(column=column, op=op, value=value))
    return out


def parse_order(raw: Any) -> list[Order]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raise IdentError("order_by 는 SQL 문자열이 아니라 {column, dir} 배열이다")
    if not isinstance(raw, list):
        raise IdentError("order_by 는 배열이어야 한다")
    out: list[Order] = []
    for item in raw:
        if not isinstance(item, dict):
            raise IdentError("order_by 항목은 객체여야 한다")
        column = str(item.get("column") or "").strip()
        direction = str(item.get("dir") or item.get("direction") or "asc").strip().lower()
        if not column or direction not in {"asc", "desc"}:
            raise IdentError("order_by 는 column 과 asc|desc 만 허용한다")
        out.append(Order(column=column, direction=direction))
    return out
