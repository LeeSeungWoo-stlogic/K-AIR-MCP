from __future__ import annotations

POSTGRES = "postgres"

_MAP = {
    "postgres": POSTGRES,
    "postgresql": POSTGRES,
    "postgis": POSTGRES,
}


def normalize_engine(raw: object) -> str | None:
    key = str(raw or "").strip().lower()
    return _MAP.get(key)


def is_postgres(raw: object) -> bool:
    return normalize_engine(raw) == POSTGRES
