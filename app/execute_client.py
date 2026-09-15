"""stone-meta-api `POST /query_execute` — 서빙 승인 표를 그 창구로만 실행한다."""
from __future__ import annotations

from typing import Any

import httpx


class ExecuteError(RuntimeError):
    pass


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
    if response.status_code == 400:
        detail = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        msg = detail.get("detail") if isinstance(detail, dict) else response.text
        raise ExecuteError(str(msg) or "query_execute HTTP 400")
    if response.status_code != 200:
        raise ExecuteError(f"query_execute HTTP {response.status_code}")
    payload = response.json()
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
