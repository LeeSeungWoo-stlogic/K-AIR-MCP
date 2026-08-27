from __future__ import annotations

import hashlib
import hmac


def key_ok(provided: str, allowed: tuple[str, ...]) -> bool:
    if not provided:
        return False
    provided_h = hashlib.sha256(provided.encode("utf-8")).digest()
    found = False
    for key in allowed:
        candidate = hmac.compare_digest(provided_h, hashlib.sha256(key.encode("utf-8")).digest())
        found = found or candidate
    return found
