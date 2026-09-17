from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

USER_ENV_PREFIX = "MCP_DS_USER_"
PASSWORD_ENV_PREFIX = "MCP_DS_PASSWORD_"
# stdio 는 로컬 한 사용자다. 고정 범위 하나로 둔다.
LOCAL_SCOPE = "local"
DEFAULT_TTL_S = 8 * 60 * 60


@dataclass(frozen=True)
class DbLogin:
    user: str
    # repr·로그에 비밀번호가 새지 않게 한다.
    password: str = field(repr=False)


def scope_for_api_key(api_key: str) -> str:
    """API Key 원문을 들고 있지 않도록 해시로만 범위를 만든다."""
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return f"key:{digest}"


def credentials_from_environ(environ: dict[str, str] | None = None) -> dict[str, DbLogin]:
    """mcp.json env / 프로세스 환경에서 소스별 id/pw를 읽는다. 값은 로그에 남기지 않는다."""
    env = os.environ if environ is None else environ
    users: dict[str, str] = {}
    passwords: dict[str, str] = {}
    for raw_key, raw_value in env.items():
        key = raw_key.strip()
        value = (raw_value or "").strip()
        if not value:
            continue
        if key.startswith(USER_ENV_PREFIX):
            users[key[len(USER_ENV_PREFIX) :].strip().lower()] = value
        elif key.startswith(PASSWORD_ENV_PREFIX):
            passwords[key[len(PASSWORD_ENV_PREFIX) :].strip().lower()] = value
    out: dict[str, DbLogin] = {}
    for slug, user in users.items():
        password = passwords.get(slug)
        if not password:
            continue
        out[slug] = DbLogin(user=user, password=password)
    return out


class CredentialStore:
    """소스별 DB 계정.

    - 운영자 env(`MCP_DS_USER_/PASSWORD_<소스>`): 서버 전역 기본값.
    - `set_credentials`: 호출자 범위(HTTP 는 API Key 해시, stdio 는 local)에만 들어가고 TTL 뒤 사라진다.
    - 조회 우선순위: 호출자 범위 > env. 다른 키의 계정은 절대 보지 않는다.
    """

    def __init__(self, ttl_s: int = DEFAULT_TTL_S, clock: Callable[[], float] = time.monotonic) -> None:
        self._env: dict[str, DbLogin] = {}
        self._scoped: dict[str, dict[str, tuple[DbLogin, float]]] = {}
        self._ttl_s = max(1, int(ttl_s))
        self._clock = clock
        self._lock = threading.Lock()

    def set_ttl(self, ttl_s: int) -> None:
        self._ttl_s = max(1, int(ttl_s))

    def load_environ(self, environ: dict[str, str] | None = None) -> tuple[str, ...]:
        loaded = credentials_from_environ(environ)
        with self._lock:
            self._env.update(loaded)
        return tuple(sorted(loaded))

    def _live(self, scope: str) -> dict[str, tuple[DbLogin, float]]:
        now = self._clock()
        bucket = self._scoped.get(scope) or {}
        for key in [k for k, (_login, expires) in bucket.items() if expires <= now]:
            bucket.pop(key, None)
        if not bucket:
            self._scoped.pop(scope, None)
        return bucket

    def set(self, source_name: str, user: str, password: str, *, scope: str = LOCAL_SCOPE) -> None:
        key = source_name.strip().lower()
        with self._lock:
            bucket = self._scoped.setdefault(scope, {})
            bucket[key] = (DbLogin(user=user, password=password), self._clock() + self._ttl_s)

    def get(self, source_name: str, *, scope: str = LOCAL_SCOPE) -> DbLogin | None:
        key = source_name.strip().lower()
        with self._lock:
            hit = self._live(scope).get(key)
            if hit is not None:
                return hit[0]
            return self._env.get(key)

    def has(self, source_name: str, *, scope: str = LOCAL_SCOPE) -> bool:
        return self.get(source_name, scope=scope) is not None

    def origin(self, source_name: str, *, scope: str = LOCAL_SCOPE) -> str | None:
        """계정 출처만 알려 준다(caller / env). 값은 돌려주지 않는다."""
        key = source_name.strip().lower()
        with self._lock:
            if key in self._live(scope):
                return "caller"
            if key in self._env:
                return "env"
        return None

    def clear(self, source_name: str | None = None, *, scope: str = LOCAL_SCOPE) -> None:
        """호출자 범위만 지운다. env 기본값과 다른 범위는 건드리지 않는다."""
        with self._lock:
            if source_name is None:
                self._scoped.pop(scope, None)
                return
            bucket = self._scoped.get(scope)
            if bucket is not None:
                bucket.pop(source_name.strip().lower(), None)
                if not bucket:
                    self._scoped.pop(scope, None)

    def clear_all(self) -> None:
        """프로세스 종료용. env 기본값까지 비운다."""
        with self._lock:
            self._scoped.clear()
            self._env.clear()

    def scoped(self, scope: str) -> "ScopedCredentials":
        return ScopedCredentials(self, scope)


class ScopedCredentials:
    """한 호출자 범위에 묶인 보기. 도구 코드는 범위를 몰라도 된다."""

    def __init__(self, store: CredentialStore, scope: str) -> None:
        self._store = store
        self.scope = scope

    def set(self, source_name: str, user: str, password: str) -> None:
        self._store.set(source_name, user, password, scope=self.scope)

    def get(self, source_name: str) -> DbLogin | None:
        return self._store.get(source_name, scope=self.scope)

    def has(self, source_name: str) -> bool:
        return self._store.has(source_name, scope=self.scope)

    def origin(self, source_name: str) -> str | None:
        return self._store.origin(source_name, scope=self.scope)

    def clear(self, source_name: str | None = None) -> None:
        self._store.clear(source_name, scope=self.scope)

    def __repr__(self) -> str:
        return f"ScopedCredentials(scope={self.scope[:12]}…)"
