from __future__ import annotations

POSTGRES = "postgres"
TIBERO = "tibero"

_MAP = {
    "postgres": POSTGRES,
    "postgresql": POSTGRES,
    "postgis": POSTGRES,
    "tibero": TIBERO,
}


def normalize_engine(raw: object) -> str | None:
    key = str(raw or "").strip().lower()
    return _MAP.get(key)


def is_postgres(raw: object) -> bool:
    return normalize_engine(raw) == POSTGRES


def is_tibero(raw: object) -> bool:
    return normalize_engine(raw) == TIBERO
