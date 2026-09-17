import asyncio

import httpx

from app import catalog_client


def test_cached_catalog_single_flight(monkeypatch):
    calls = 0

    async def slow_fetch(_url):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"sources": [], "n": calls}

    monkeypatch.setattr(catalog_client, "fetch_catalog", slow_fetch)

    async def run():
        return await asyncio.gather(
            *(catalog_client.fetch_catalog_cached("http://stone:8096", 300) for _ in range(10))
        )

    results = asyncio.run(run())
    assert calls == 1
    assert all(item["n"] == 1 for item in results)


def test_cached_catalog_expires(monkeypatch):
    calls = 0
    now = [100.0]

    async def fetch(_url):
        nonlocal calls
        calls += 1
        return {"n": calls}

    monkeypatch.setattr(catalog_client, "fetch_catalog", fetch)
    clock = lambda: now[0]  # noqa: E731
    first = asyncio.run(catalog_client.fetch_catalog_cached("http://stone:8096", 300, clock=clock))
    now[0] += 299
    again = asyncio.run(catalog_client.fetch_catalog_cached("http://stone:8096/", 300, clock=clock))
    now[0] += 2
    later = asyncio.run(catalog_client.fetch_catalog_cached("http://stone:8096", 300, clock=clock))
    assert (first["n"], again["n"], later["n"]) == (1, 1, 2)


def test_failures_are_not_cached_and_ttl_zero_disables(monkeypatch):
    calls = 0

    async def flaky(_url):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise catalog_client.CatalogError("down")
        return {"n": calls}

    monkeypatch.setattr(catalog_client, "fetch_catalog", flaky)
    try:
        asyncio.run(catalog_client.fetch_catalog_cached("http://stone:8096", 300))
    except catalog_client.CatalogError:
        pass
    assert asyncio.run(catalog_client.fetch_catalog_cached("http://stone:8096", 300))["n"] == 2
    asyncio.run(catalog_client.fetch_catalog_cached("http://stone:8096", 0))
    assert calls == 3


class _BodyClient:
    bodies: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None):
        type(self).bodies.append(json)

        class _R:
            status_code = 200

            @staticmethod
            def json():
                return {"sources": [], "truncated": False}

        return _R()


def test_fetch_catalog_never_posts_empty_body_and_uses_page_200(monkeypatch):
    _BodyClient.bodies = []
    monkeypatch.setattr(httpx, "AsyncClient", _BodyClient)
    asyncio.run(catalog_client.fetch_catalog("http://stone:8096"))
    assert _BodyClient.bodies == [{"limit": 200}]
