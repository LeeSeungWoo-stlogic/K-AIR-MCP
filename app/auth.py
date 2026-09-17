from __future__ import annotations

import hashlib
import hmac
from typing import Mapping


def key_ok(provided: str, allowed: tuple[str, ...]) -> bool:
    if not provided:
        return False
    provided_h = hashlib.sha256(provided.encode("utf-8")).digest()
    found = False
    for key in allowed:
        candidate = hmac.compare_digest(
            provided_h, hashlib.sha256(key.encode("utf-8")).digest()
        )
        found = found or candidate
    return found


def api_key_from_headers(headers: Mapping[str, str]) -> str:
    """`X-Api-Key`, `Authorization: ApiKey …`, `Authorization: Bearer …` 순으로 키를 꺼낸다."""
    provided = (headers.get("x-api-key") or "").strip()
    authorization = headers.get("authorization") or ""
    if not provided and authorization.lower().startswith("apikey "):
        provided = authorization[7:].strip()
    if not provided and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    return provided
