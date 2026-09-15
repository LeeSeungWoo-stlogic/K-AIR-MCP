from __future__ import annotations

import os
from dataclasses import dataclass

USER_ENV_PREFIX = "MCP_DS_USER_"
PASSWORD_ENV_PREFIX = "MCP_DS_PASSWORD_"


@dataclass(frozen=True)
class DbLogin:
    user: str
    password: str


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
    def __init__(self) -> None:
        self._by_source: dict[str, DbLogin] = {}

    def load_environ(self, environ: dict[str, str] | None = None) -> tuple[str, ...]:
        loaded = credentials_from_environ(environ)
        for source_name, login in loaded.items():
            self._by_source[source_name] = login
        return tuple(sorted(loaded))

    def set(self, source_name: str, user: str, password: str) -> None:
        key = source_name.strip().lower()
        self._by_source[key] = DbLogin(user=user, password=password)

    def get(self, source_name: str) -> DbLogin | None:
        return self._by_source.get(source_name.strip().lower())

    def has(self, source_name: str) -> bool:
        return source_name.strip().lower() in self._by_source

    def clear(self, source_name: str | None = None) -> None:
        if source_name is None:
            self._by_source.clear()
            return
        self._by_source.pop(source_name.strip().lower(), None)
