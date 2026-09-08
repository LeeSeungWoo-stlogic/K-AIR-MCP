from __future__ import annotations

import asyncio
import time

import httpx

CACHE_TTL_S = 45.0
_PROBE_TIMEOUT_S = 5.0
_FETCH_TIMEOUT_S = 15.0

_cache: dict[str, tuple[float, dict]] = {}
_lock = asyncio.Lock()


class CatalogError(RuntimeError):
    pass


def _cache_key(robo_meta_url: str) -> str:
    return robo_meta_url.rstrip("/")


def clear_cache() -> None:
    _cache.clear()


async def _http_fetch(robo_meta_url: str, timeout_s: float) -> dict:
    url = f"{robo_meta_url.rstrip('/')}/meta/catalog"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(url)
    except httpx.HTTPError as exc:
        raise CatalogError(f"catalog request failed: {exc}") from exc
    if response.status_code != 200:
        raise CatalogError(f"catalog HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise CatalogError("catalog response is not an object")
    return payload


def _store(robo_meta_url: str, payload: dict) -> dict:
    _cache[_cache_key(robo_meta_url)] = (time.monotonic(), payload)
    return payload


async def fetch_catalog(robo_meta_url: str) -> dict:
    key = _cache_key(robo_meta_url)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    async with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
        return _store(robo_meta_url, await _http_fetch(robo_meta_url, _FETCH_TIMEOUT_S))


async def probe_catalog(robo_meta_url: str) -> str:
    try:
        payload = await _http_fetch(robo_meta_url, _PROBE_TIMEOUT_S)
    except CatalogError:
        return "unreachable"
    _store(robo_meta_url, payload)
    return "ok"
