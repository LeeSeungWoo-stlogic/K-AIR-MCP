from __future__ import annotations

from dataclasses import dataclass, field

from .credentials import CredentialStore
from .settings import Settings


@dataclass
class Runtime:
    settings: Settings | None = None
    credentials: CredentialStore = field(default_factory=CredentialStore)


RT = Runtime()
