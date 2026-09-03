from __future__ import annotations

from typing import Any

import httpx

_DEFAULT_TIMEOUT_S = 60
_ERROR_RETURN_GRACE_S = 30


class ExecuteError(RuntimeError):
    pass


def _http_timeout_s(timeout_s: int | None) -> float:
    applied = timeout_s if timeout_s is not None else _DEFAULT_TIMEOUT_S
    return float(max(1, applied) + _ERROR_RETURN_GRACE_S)


def _error_message(payload: object, status_code: int) -> str:
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, dict):
                nested = value.get("message") or value.get("code")
                if nested:
                    return str(nested)
            if value:
                return str(value)
        status = payload.get("status")
        if status:
            return str(status)
    return f"query_execute HTTP {status_code}"


def rows_to_dicts(columns: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for index, name in enumerate(columns):
            item[name] = row[index] if index < len(row) else None
        out.append(item)
    return out


async def execute_query(
    robo_meta_url: str,
    sql: str,
    *,
    max_rows: int,
    timeout_s: int | None = None,
) -> list[dict[str, Any]]:
    url = f"{robo_meta_url.rstrip('/')}/query_execute"
    body: dict[str, Any] = {"sql": sql, "max_rows": max_rows}
    if timeout_s is not None:
        body["timeout_s"] = timeout_s
    try:
        async with httpx.AsyncClient(timeout=_http_timeout_s(timeout_s)) as client:
            response = await client.post(url, json=body)
    except httpx.HTTPError as exc:
        detail = str(exc).strip() or f"{type(exc).__name__} (request timeout or connection closed)"
        raise ExecuteError(f"query_execute request failed: {detail}") from exc

    payload: object
    try:
        payload = response.json()
    except Exception:
        payload = None

    if response.status_code != 200:
        raise ExecuteError(_error_message(payload, response.status_code))
    if not isinstance(payload, dict):
        raise ExecuteError("query_execute response is not an object")
    status = str(payload.get("status") or "")
    if status != "ok":
        raise ExecuteError(_error_message(payload, response.status_code))

    columns = [str(name) for name in (payload.get("columns") or [])]
    raw_rows = payload.get("rows") or []
    if not isinstance(raw_rows, list):
        raise ExecuteError("query_execute rows is not an array")
    return rows_to_dicts(columns, raw_rows)
