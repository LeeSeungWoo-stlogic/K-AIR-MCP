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
    # Optional legacy DB config (deprecated in favor of pure robo-meta-api serving)
    pg_host: str = "host.docker.internal"
    pg_port: int = 5434
    pg_db: str = ""
    pg_user: str = ""
    pg_password: str = ""
    tb_host: str = ""
    tb_port: int | None = None
    tb_sid: str = ""
    tb_user: str = ""
    tb_password: str = ""
    tb_jdbc_jar: str = ""

    @property
    def pg_configured(self) -> bool:
        return bool(self.pg_db and self.pg_user and self.pg_password)

    @property
    def tb_configured(self) -> bool:
        return bool(
            self.tb_host
            and self.tb_port
            and self.tb_sid
            and self.tb_user
            and self.tb_password
            and self.tb_jdbc_jar
        )

    @property
    def pg_conninfo(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password} "
            "options='-c default_transaction_read_only=on -c statement_timeout=15000'"
        )


def load_settings() -> Settings:
    pg_db = (os.environ.get("MCP_PG_DB") or os.environ.get("SOURCE_PG_DB") or "").strip()
    pg_user = (os.environ.get("MCP_PG_USER") or os.environ.get("SOURCE_PG_USER") or "").strip()
    pg_password = (os.environ.get("MCP_PG_PASSWORD") or os.environ.get("SOURCE_PG_PASS") or "").strip()

    port_raw = (os.environ.get("MCP_PG_PORT") or "5434").strip()
    try:
        pg_port = int(port_raw)
    except ValueError as exc:
        raise SettingsError("MCP_PG_PORT must be an integer") from exc

    limit_raw = (os.environ.get("MCP_ROW_LIMIT") or "200").strip()
    try:
        row_limit = int(limit_raw)
    except ValueError as exc:
        raise SettingsError("MCP_ROW_LIMIT must be an integer") from exc
    if row_limit < 1:
        raise SettingsError("MCP_ROW_LIMIT must be >= 1")

    tb_port_raw = (os.environ.get("MCP_TB_PORT") or "").strip()
    tb_port: int | None = None
    if tb_port_raw:
        try:
            tb_port = int(tb_port_raw)
        except ValueError as exc:
            raise SettingsError("MCP_TB_PORT must be an integer") from exc

    return Settings(
        api_keys=_parse_keys(_require("MCP_API_KEYS")),
        robo_meta_url=(os.environ.get("ROBO_META_URL") or "http://robo-meta-api:8100").rstrip("/"),
        row_limit=row_limit,
        api_host=(os.environ.get("API_HOST") or "0.0.0.0").strip(),
        api_port=int((os.environ.get("API_PORT") or "8110").strip()),
        pg_host=(os.environ.get("MCP_PG_HOST") or "host.docker.internal").strip(),
        pg_port=pg_port,
        pg_db=pg_db,
        pg_user=pg_user,
        pg_password=pg_password,
        tb_host=(os.environ.get("MCP_TB_HOST") or "").strip(),
        tb_port=tb_port,
        tb_sid=(os.environ.get("MCP_TB_SID") or "").strip(),
        tb_user=(os.environ.get("MCP_TB_USER") or "").strip(),
        tb_password=(os.environ.get("MCP_TB_PASSWORD") or "").strip(),
        tb_jdbc_jar=(os.environ.get("MCP_TB_JDBC_JAR") or "").strip(),
    )
