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
