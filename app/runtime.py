from __future__ import annotations

from dataclasses import dataclass, field

from .credentials import CredentialStore
from .settings import Settings


@dataclass
class Runtime:
    settings: Settings | None = None
    credentials: CredentialStore = field(default_factory=CredentialStore)
    # "http" 이면 호출자 API Key 가 없을 때 계정 범위를 열지 않는다.
    transport: str | None = None


RT = Runtime()
