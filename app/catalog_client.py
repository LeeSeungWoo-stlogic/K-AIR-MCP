from __future__ import annotations

import httpx


class CatalogError(RuntimeError):
    pass


PAGE_LIMIT = 50
MAX_PAGES = 200


def _merge_catalog_sources(pages: list[dict]) -> dict:
    serving = "inactive"
    version = None
    by_key: dict[tuple[str, str, str, str], dict] = {}
    for payload in pages:
        if payload.get("serving_status"):
            serving = str(payload["serving_status"])
        if payload.get("meta_version"):
            version = payload.get("meta_version")
        for source in payload.get("sources") or []:
            if not isinstance(source, dict):
                continue
            key = (
                str(source.get("source_name") or ""),
                str(source.get("engine") or ""),
                str(source.get("source_schema") or ""),
                str(source.get("registered_at") or ""),
            )
            bucket = by_key.get(key)
            if bucket is None:
                bucket = {**source, "tables": []}
                by_key[key] = bucket
            bucket["tables"].extend(source.get("tables") or [])
    merged: dict = {"serving_status": serving, "sources": list(by_key.values())}
    if version is not None:
        merged["meta_version"] = version
    return merged


async def fetch_catalog(robo_meta_url: str) -> dict:
    """표 이름 목록을 페이지로 받아 합친다. 컬럼·FK 는 여기 없다."""
    url = f"{robo_meta_url.rstrip('/')}/meta/catalog"
    pages: list[dict] = []
    cursor = None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for _ in range(MAX_PAGES):
                body: dict = {"limit": PAGE_LIMIT}
                if cursor:
                    body["cursor"] = cursor
                response = await client.post(url, json=body)
                if response.status_code != 200:
                    raise CatalogError(f"catalog HTTP {response.status_code}")
                payload = response.json()
                if not isinstance(payload, dict):
                    raise CatalogError("catalog response is not an object")
                pages.append(payload)
                if not payload.get("truncated"):
                    break
                cursor = payload.get("next_cursor")
                if not cursor:
                    break
            else:
                raise CatalogError("catalog page limit exceeded")
    except httpx.HTTPError as exc:
        raise CatalogError(f"catalog request failed: {exc}") from exc
    return _merge_catalog_sources(pages)


async def fetch_table(
    robo_meta_url: str,
    *,
    source_name: str,
    schema_name: str,
    table_name: str,
    scope: str = "serving",
) -> dict:
    url = f"{robo_meta_url.rstrip('/')}/meta/table"
    body = {
        "source_name": source_name,
        "schema_name": schema_name,
        "table_name": table_name,
        "scope": scope,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=body)
    except httpx.HTTPError as exc:
        raise CatalogError(f"table request failed: {exc}") from exc
    if response.status_code == 404:
        raise CatalogError("table not found")
    if response.status_code != 200:
        raise CatalogError(f"table HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise CatalogError("table response is not an object")
    return payload


async def fetch_refs(
    robo_meta_url: str,
    *,
    source_name: str,
    schema_name: str,
    table_name: str,
    scope: str = "serving",
) -> list:
    url = f"{robo_meta_url.rstrip('/')}/meta/ref"
    body = {
        "source_name": source_name,
        "schema_name": schema_name,
        "table_name": table_name,
        "scope": scope,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=body)
    except httpx.HTTPError as exc:
        raise CatalogError(f"ref request failed: {exc}") from exc
    if response.status_code == 404:
        raise CatalogError("table not found")
    if response.status_code != 200:
        raise CatalogError(f"ref HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise CatalogError("ref response is not an object")
    fks = payload.get("fk")
    return fks if isinstance(fks, list) else []


async def probe_catalog(robo_meta_url: str) -> str:
    """stone-meta 가 살아 있는지만 본다. 카탈로그 전체를 읽지 않는다.

    `/health` 가 `fetch_catalog` 를 부르면 Docker 가 30초마다 목록을 다시 받고,
    그 조회가 워커를 붙잡는다. 목록은 도구가 부를 때만 페이지로 읽는다.
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
