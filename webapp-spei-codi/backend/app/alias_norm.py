"""Normalización y búsqueda de alias de usuario (case-insensitive)."""
from __future__ import annotations

import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import User

_ALIAS_REST_RE = re.compile(r"^[A-Za-z0-9._-]{3,}$", re.IGNORECASE)


def normalize_alias(alias: str | None) -> str:
    """Normaliza prefijo $@; conserva el resto (la comparación usa lower())."""
    raw = (alias or "").strip()
    if raw.startswith("$@"):
        full = raw
    elif raw.startswith("@"):
        full = "$@" + raw[1:]
    else:
        full = "$@" + raw
    return full


def alias_key(alias: str | None) -> str:
    """Clave canónica para comparar alias (minúsculas)."""
    return normalize_alias(alias).lower()


def find_user_by_alias(db: Session, alias: str | None) -> User | None:
    """Busca usuario por alias ignorando mayúsculas/minúsculas."""
    key = alias_key(alias)
    if not key.startswith("$@") or len(key) < 5:
        return None
    return db.query(User).filter(func.lower(User.alias) == key).first()


def alias_taken(db: Session, alias: str | None) -> bool:
    return find_user_by_alias(db, alias) is not None
