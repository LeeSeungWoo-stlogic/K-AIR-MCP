import asyncio

import httpx
import pytest

from app import execute_client


def _client_returning(response: httpx.Response):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            return response

    return _Client


def _run(monkeypatch, response: httpx.Response):
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(response))
    return asyncio.run(
        execute_client.query_execute("http://stone:8096", "SELECT 1", max_rows=1, timeout_s=5)
    )


def test_422_surfaces_validation_detail(monkeypatch):
    response = httpx.Response(
        422, json={"detail": [{"loc": ["body", "sql"], "msg": "field required"}]}
    )
    with pytest.raises(execute_client.ExecuteError) as info:
        _run(monkeypatch, response)
    assert "422" in str(info.value)
    assert "field required" in str(info.value)


def test_500_plain_text_detail_is_truncated(monkeypatch):
    response = httpx.Response(500, text="Traceback: " + "x" * 5000)
    with pytest.raises(execute_client.ExecuteError) as info:
        _run(monkeypatch, response)
    message = str(info.value)
    assert message.startswith("query_execute HTTP 500: Traceback:")
    assert len(message) < 600


def test_400_keeps_detail_message(monkeypatch):
    response = httpx.Response(400, json={"detail": "table not allowed"})
    with pytest.raises(execute_client.ExecuteError) as info:
        _run(monkeypatch, response)
    assert str(info.value) == "table not allowed"


def test_200_non_json_is_execute_error(monkeypatch):
    response = httpx.Response(200, text="<html>proxy error</html>")
    with pytest.raises(execute_client.ExecuteError) as info:
        _run(monkeypatch, response)
    assert "JSON" in str(info.value)
    assert "proxy error" in str(info.value)


def test_200_ok_rows(monkeypatch):
    response = httpx.Response(200, json={"status": "ok", "columns": ["a"], "rows": [[1]]})
    assert _run(monkeypatch, response) == [{"a": 1}]
