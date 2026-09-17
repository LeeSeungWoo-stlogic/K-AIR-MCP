"""HTTP 앞단 경로 판정. API Key 미들웨어가 인증 없이 통과시킬 경로만 정한다."""
from __future__ import annotations

# Docker healthcheck·프록시가 키 없이 치는 경로. `/mcp` 는 절대 넣지 않는다.
HEALTH_PATHS = frozenset({"/health"})


def health_path(path: str) -> bool:
    """정확히 헬스 경로일 때만 True. 접두어·하위 경로·`..` 조합은 통과시키지 않는다."""
    if not isinstance(path, str) or not path:
        return False
    normalized = path.rstrip("/") if len(path) > 1 else path
    return normalized in HEALTH_PATHS
