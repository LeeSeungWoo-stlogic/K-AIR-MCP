from __future__ import annotations

import logging

from .engine import TIBERO
from .intersect import EngineInventory
from .settings import Settings

# 수집 Tibero 인스턴스가 생기면 JDBC thin(host:port:SID)으로 연다. 지금은 접속이 없어 목록이 비다.

log = logging.getLogger("kair-mcp-query")


class TiberoError(RuntimeError):
    pass


def is_configured(settings: Settings) -> bool:
    return bool(
        settings.tb_host
        and settings.tb_port
        and settings.tb_sid
        and settings.tb_user
        and settings.tb_password
        and settings.tb_jdbc_jar
    )


async def list_tb_inventory(settings: Settings) -> EngineInventory:
    if is_configured(settings):
        log.warning("Tibero 접속 env는 있으나 드라이버 실행은 아직 없다. 카탈로그 Tibero 소스는 목록에서 빠진다.")
    return EngineInventory(tables=set(), columns={})


async def fetch_rows(settings: Settings, sql: str, params: tuple = ()) -> list[dict]:
    raise TiberoError("Tibero 원천이 설정되지 않았습니다")


async def column_comments(settings: Settings, schema: str, table: str) -> dict[str, str]:
    raise TiberoError("Tibero 원천이 설정되지 않았습니다")


def dialect() -> str:
    return TIBERO
