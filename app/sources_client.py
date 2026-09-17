from __future__ import annotations

from dataclasses import dataclass

import httpx

from .engine import POSTGRES, TIBERO, normalize_engine


class SourcesError(RuntimeError):
    pass


DATASOURCES_PATH = "/air-swmm/data-fabric/api/datasources"


@dataclass(frozen=True)
class SourceEndpoint:
    source_id: str
    source_name: str
    engine: str
    host: str
    port: int
    database: str
    schema_name: str
    schema_scope: tuple[str, ...]
    enabled: bool
    username: str = ""


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _schema_scope(row: dict) -> tuple[str, ...]:
    raw = row.get("schema_scope")
    names: list[str] = []
    if isinstance(raw, list):
        names.extend(str(item).strip() for item in raw if str(item).strip())
    single = str(row.get("schema") or row.get("schema_name") or "").strip()
    if single and single.lower() not in {name.lower() for name in names}:
        names.append(single)
    return tuple(names)


def parse_endpoints(payload: dict, *, engines: set[str] | None = None) -> list[SourceEndpoint]:
    rows = payload.get("datasources") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    endpoints: list[SourceEndpoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        connection = row.get("connection") if isinstance(row.get("connection"), dict) else {}
        engine_raw = row.get("engine") or row.get("source_type") or connection.get("engine")
        engine = normalize_engine(engine_raw)
        if engine is None:
            continue
        if engines is not None and engine not in engines:
            continue
        host = str(row.get("host") or connection.get("host") or "").strip()
        port = _as_int(row.get("port") if row.get("port") is not None else connection.get("port"))
        database = str(
            row.get("database")
            or row.get("sid")
            or connection.get("database")
            or connection.get("sid")
            or ""
        ).strip()
        scope = _schema_scope({**connection, **row})
        source_name = str(row.get("name") or row.get("source_name") or "").strip()
        source_id = str(row.get("source_id") or source_name).strip()
        if not host or port is None or not database or not source_name:
            continue
        username = str(
            row.get("username")
            or row.get("user")
            or connection.get("username")
            or connection.get("user")
            or ""
        ).strip()
        endpoints.append(
            SourceEndpoint(
                source_id=source_id,
                source_name=source_name,
                engine=engine,
                host=host,
                port=port,
                database=database,
                schema_name=scope[0] if scope else "",
                schema_scope=scope,
                enabled=row.get("enabled") is not False,
                username=username,
            )
        )
    return endpoints


def parse_postgres_endpoints(payload: dict) -> list[SourceEndpoint]:
    return parse_endpoints(payload, engines={POSTGRES})


def parse_tibero_endpoints(payload: dict) -> list[SourceEndpoint]:
    return parse_endpoints(payload, engines={TIBERO})


def find_endpoint(
    endpoints: list[SourceEndpoint],
    source_name: str,
) -> SourceEndpoint | None:
    key = source_name.strip().lower()
    matches = [item for item in endpoints if item.source_name.lower() == key]
    return matches[0] if matches else None


def schema_allowed(endpoint: SourceEndpoint, schema_name: str) -> bool:
    key = schema_name.strip().lower()
    if not key:
        return False
    if endpoint.schema_scope:
        return key in {name.lower() for name in endpoint.schema_scope}
    if endpoint.schema_name:
        return key == endpoint.schema_name.lower()
    return True


async def fetch_sources(nk_backend_url: str, admin_token: str = "", *, timeout_s: float = 15.0) -> dict:
    url = f"{nk_backend_url.rstrip('/')}{DATASOURCES_PATH}"
    headers: dict[str, str] = {}
    if admin_token:
        headers["Authorization"] = f"Bearer {admin_token}"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise SourcesError(f"sources request failed: {exc}") from exc
    if response.status_code != 200:
        raise SourcesError(f"sources HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise SourcesError("sources response is not an object")
    return payload


async def fetch_postgres_endpoints(
    nk_backend_url: str,
    admin_token: str = "",
) -> list[SourceEndpoint]:
    return parse_postgres_endpoints(await fetch_sources(nk_backend_url, admin_token))


async def fetch_direct_endpoints(
    nk_backend_url: str,
    admin_token: str = "",
) -> list[SourceEndpoint]:
    return parse_endpoints(
        await fetch_sources(nk_backend_url, admin_token),
        engines={POSTGRES, TIBERO},
    )


async def probe_sources(nk_backend_url: str, admin_token: str = "", timeout_s: float = 15.0) -> str:
    try:
        await fetch_sources(nk_backend_url, admin_token, timeout_s=timeout_s)
    except SourcesError:
        return "unreachable"
    return "ok"
