"""stone-meta-api `POST /query_execute` — 서빙 승인 표를 그 창구로만 실행한다."""
from __future__ import annotations

import json
from typing import Any

import httpx


class ExecuteError(RuntimeError):
    pass


DETAIL_MAX_CHARS = 500


def _truncate(text: str, limit: int = DETAIL_MAX_CHARS) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def response_detail(response: Any) -> str:
    """오류 응답에서 사람이 읽을 부분만 짧게 꺼낸다. JSON 이 아니면 본문 앞부분."""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        for key in ("detail", "error", "message"):
            value = payload.get(key)
            if value in (None, ""):
                continue
            return _truncate(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    try:
        return _truncate(response.text or "")
    except Exception:  # noqa: BLE001 - 본문 디코딩 실패 시 빈 설명
        return ""


def rows_as_dicts(payload: dict) -> list[dict[str, Any]]:
    columns = payload.get("columns") or []
    raw_rows = payload.get("rows") or []
    if not isinstance(columns, list) or not isinstance(raw_rows, list):
        return []
    names = [str(col) for col in columns]
    out: list[dict[str, Any]] = []
    for row in raw_rows:
        if isinstance(row, dict):
            out.append(row)
            continue
        if isinstance(row, list):
            out.append({names[i]: row[i] for i in range(min(len(names), len(row)))})
    return out


async def query_execute(
    stone_meta_url: str,
    sql: str,
    *,
    max_rows: int,
    timeout_s: int,
) -> list[dict[str, Any]]:
    url = f"{stone_meta_url.rstrip('/')}/query_execute"
    body = {"sql": sql, "timeout_s": timeout_s, "max_rows": max_rows}
    try:
        async with httpx.AsyncClient(timeout=float(timeout_s) + 10.0) as client:
            response = await client.post(url, json=body)
    except httpx.HTTPError as exc:
        raise ExecuteError(f"query_execute request failed: {exc}") from exc
    if response.status_code != 200:
        detail = response_detail(response)
        if response.status_code == 400 and detail:
            raise ExecuteError(detail)
        suffix = f": {detail}" if detail else ""
        raise ExecuteError(f"query_execute HTTP {response.status_code}{suffix}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExecuteError(
            f"query_execute 응답이 JSON 이 아닙니다: {_truncate(response.text or '', 200)}"
        ) from exc
    if not isinstance(payload, dict):
        raise ExecuteError("query_execute response is not an object")
    status = str(payload.get("status") or "")
    if status != "ok":
        raise ExecuteError(str(payload.get("error") or f"query_execute status={status or 'unknown'}"))
    return rows_as_dicts(payload)


async def probe_execute(stone_meta_url: str) -> str:
    url = f"{stone_meta_url.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url)
    except httpx.HTTPError:
        return "unreachable"
    if response.status_code != 200:
        return "unreachable"
    return "ok"
