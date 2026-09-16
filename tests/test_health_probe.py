import asyncio

import httpx

from app import catalog_client


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeClient:
    seen: list[tuple[str, str]] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        type(self).seen.append(("GET", url))
        return _FakeResponse(200)

    async def post(self, url):
        type(self).seen.append(("POST", url))
        raise AssertionError("probe must not POST /meta/catalog")


def test_probe_catalog_uses_stone_health_not_full_catalog(monkeypatch):
    _FakeClient.seen = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    out = asyncio.run(catalog_client.probe_catalog("http://stone-meta-api:8096"))
    assert out == "ok"
    assert _FakeClient.seen == [("GET", "http://stone-meta-api:8096/health")]
    assert not any(method == "POST" for method, _ in _FakeClient.seen)


def test_probe_catalog_unreachable_on_http_error(monkeypatch):
    class _Down:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "AsyncClient", _Down)
    assert asyncio.run(catalog_client.probe_catalog("http://stone-meta-api:8096")) == "unreachable"
