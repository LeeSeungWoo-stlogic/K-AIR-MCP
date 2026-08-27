from __future__ import annotations

from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool

from .settings import Settings


@dataclass
class Runtime:
    settings: Settings | None = None
    pool: AsyncConnectionPool | None = None


RT = Runtime()
