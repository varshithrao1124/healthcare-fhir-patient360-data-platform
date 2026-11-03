"""Salted hashing for identifiers. The salt is an environment or Key Vault reference."""

from __future__ import annotations

import hashlib


def token(value: str | None, salt: str, length: int = 32) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    digest = hashlib.sha256(f"{salt}|{value}".encode()).hexdigest()
    return digest[:length]


def person_token(enterprise_person_id: str, salt: str) -> str:
    return token(f"deid|{enterprise_person_id}", salt, length=16) or ""
