from __future__ import annotations

import os
from dataclasses import dataclass


class SettingsError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise SettingsError(f"{name} is required")
    return value


def _parse_keys(raw: str) -> tuple[str, ...]:
    keys = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not keys:
        raise SettingsError("MCP_API_KEYS is required")
    return keys


@dataclass(frozen=True)
class Settings:
    api_keys: tuple[str, ...]
    stone_meta_url: str
    robo_meta_url: str
    nk_backend_url: str
    nk_backend_token: str
    row_limit: int = 200
    api_host: str = "0.0.0.0"
    api_port: int = 8111
    statement_timeout_ms: int = 60000
    tibero_jdbc_jar: str = ""
    direct_max_concurrency: int = 4


def load_settings() -> Settings:
    limit_raw = (os.environ.get("MCP_ROW_LIMIT") or "200").strip()
    try:
        row_limit = int(limit_raw)
    except ValueError as exc:
        raise SettingsError("MCP_ROW_LIMIT must be an integer") from exc
    if row_limit < 1:
        raise SettingsError("MCP_ROW_LIMIT must be >= 1")

    timeout_raw = (os.environ.get("MCP_STATEMENT_TIMEOUT_MS") or "60000").strip()
    try:
        statement_timeout_ms = int(timeout_raw)
    except ValueError as exc:
        raise SettingsError("MCP_STATEMENT_TIMEOUT_MS must be an integer") from exc
    if statement_timeout_ms < 1:
        raise SettingsError("MCP_STATEMENT_TIMEOUT_MS must be >= 1")

    concurrency_raw = (os.environ.get("MCP_DIRECT_MAX_CONCURRENCY") or "4").strip()
    try:
        direct_max_concurrency = int(concurrency_raw)
    except ValueError as exc:
        raise SettingsError("MCP_DIRECT_MAX_CONCURRENCY must be an integer") from exc
    if direct_max_concurrency < 1:
        raise SettingsError("MCP_DIRECT_MAX_CONCURRENCY must be >= 1")

    stone = (
        (os.environ.get("STONE_META_URL") or os.environ.get("ROBO_META_URL") or "http://127.0.0.1:8096")
        .strip()
        .rstrip("/")
    )
    return Settings(
        api_keys=_parse_keys(_require("MCP_API_KEYS")),
        stone_meta_url=stone,
        robo_meta_url=stone,
        nk_backend_url=(os.environ.get("NK_BACKEND_URL") or "http://127.0.0.1:8000").rstrip("/"),
        nk_backend_token=(os.environ.get("NK_BACKEND_TOKEN") or "").strip(),
        row_limit=row_limit,
        api_host=(os.environ.get("API_HOST") or "0.0.0.0").strip(),
        api_port=int((os.environ.get("API_PORT") or "8111").strip()),
        statement_timeout_ms=statement_timeout_ms,
        tibero_jdbc_jar=(os.environ.get("TIBERO_JDBC_JAR") or "").strip(),
        direct_max_concurrency=direct_max_concurrency,
    )
