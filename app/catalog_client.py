from __future__ import annotations

import httpx


class CatalogError(RuntimeError):
    pass


async def fetch_catalog(robo_meta_url: str) -> dict:
    url = f"{robo_meta_url.rstrip('/')}/meta/catalog"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url)
    except httpx.HTTPError as exc:
        raise CatalogError(f"catalog request failed: {exc}") from exc
    if response.status_code != 200:
        raise CatalogError(f"catalog HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise CatalogError("catalog response is not an object")
    return payload


async def probe_catalog(robo_meta_url: str) -> str:
    """stone-meta 가 살아 있는지만 본다. 카탈로그 전체를 읽지 않는다.

    `/health` 가 `fetch_catalog` 를 부르면 Docker 가 30초마다 서빙 정본을 다시
    받고, 워커 하나인 stone-meta 가 그 조회에 묶인다.
    """
    url = f"{robo_meta_url.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url)
    except httpx.HTTPError:
        return "unreachable"
    if response.status_code != 200:
        return "unreachable"
    return "ok"
