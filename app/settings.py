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
    robo_meta_url: str
    row_limit: int = 200
    api_host: str = "0.0.0.0"
    api_port: int = 8110


def load_settings() -> Settings:
    limit_raw = (os.environ.get("MCP_ROW_LIMIT") or "200").strip()
    try:
        row_limit = int(limit_raw)
    except ValueError as exc:
        raise SettingsError("MCP_ROW_LIMIT must be an integer") from exc
    if row_limit < 1:
        raise SettingsError("MCP_ROW_LIMIT must be >= 1")

    return Settings(
        api_keys=_parse_keys(_require("MCP_API_KEYS")),
        robo_meta_url=(os.environ.get("ROBO_META_URL") or "http://robo-meta-api:8100").rstrip("/"),
        row_limit=row_limit,
        api_host=(os.environ.get("API_HOST") or "0.0.0.0").strip(),
        api_port=int((os.environ.get("API_PORT") or "8110").strip()),
    )
