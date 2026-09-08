from __future__ import annotations

from dataclasses import dataclass

from .settings import Settings


@dataclass
class Runtime:
    settings: Settings | None = None


RT = Runtime()
