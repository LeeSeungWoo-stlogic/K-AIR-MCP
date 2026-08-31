from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx

from app import execute_client


def _run(coro):
    return asyncio.run(coro)


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _patch_post(response):
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return patch("app.execute_client.httpx.AsyncClient", return_value=client), client


def test_ok_maps_columns_and_rows():
    resp = _Resp(
        200,
        {"status": "ok", "columns": ["a", "b"], "rows": [[1, "x"]]},
    )
    patched, client = _patch_post(resp)
    with patched:
        rows = _run(
            execute_client.execute_query("http://robo-meta-api:8100", "SELECT 1", max_rows=10)
        )
    assert rows == [{"a": 1, "b": "x"}]
    url, = client.post.await_args.args
    body = client.post.await_args.kwargs["json"]
    assert url == "http://robo-meta-api:8100/query_execute"
    assert body == {"sql": "SELECT 1", "max_rows": 10}


def test_ok_empty_rows_is_empty_list():
    resp = _Resp(200, {"status": "ok", "columns": ["a"], "rows": []})
    patched, _ = _patch_post(resp)
    with patched:
        rows = _run(execute_client.execute_query("http://robo", "SELECT 1", max_rows=5))
    assert rows == []


def test_status_timeout_is_error_not_empty_items():
    resp = _Resp(200, {"status": "timeout", "error": "timed out", "rows": []})
    patched, _ = _patch_post(resp)
    with patched:
        try:
            _run(execute_client.execute_query("http://robo/", "SELECT 1", max_rows=5))
        except execute_client.ExecuteError as exc:
            assert "timed out" in str(exc)
            return
    raise AssertionError("timeout must fail")


def test_http_400_is_error():
    resp = _Resp(400, {"detail": "unbound source"})
    patched, _ = _patch_post(resp)
    with patched:
        try:
            _run(execute_client.execute_query("http://robo", "SELECT 1", max_rows=5))
        except execute_client.ExecuteError as exc:
            assert "unbound source" in str(exc)
            return
    raise AssertionError("HTTP 400 must fail")


def test_request_failure_is_error():
    client = AsyncMock()
    client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch("app.execute_client.httpx.AsyncClient", return_value=client):
        try:
            _run(execute_client.execute_query("http://robo", "SELECT 1", max_rows=5))
        except execute_client.ExecuteError:
            return
    raise AssertionError("connect failure must fail")


def test_http_timeout_includes_grace():
    assert execute_client._http_timeout_s(None) == 90.0
    assert execute_client._http_timeout_s(10) == 40.0
