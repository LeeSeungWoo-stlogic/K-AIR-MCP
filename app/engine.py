from __future__ import annotations

POSTGRES = "postgres"
TIBERO = "tibero"
SUPPORTED = frozenset({POSTGRES, TIBERO})

# 카탈로그 t2s_datasources.engine. OA 수집은 Tibero인데 oracle 로 적히는 경우가 있다.
_MAP = {
    "postgres": POSTGRES,
    "postgresql": POSTGRES,
    "postgis": POSTGRES,
    "tibero": TIBERO,
    "tibero7": TIBERO,
    "oracle": TIBERO,
}


def normalize_engine(raw: object) -> str | None:
    key = str(raw or "").strip().lower()
    return _MAP.get(key)
