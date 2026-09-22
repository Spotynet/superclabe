"""Notificaciones in-app por usuario según el origen del proceso."""

# SC-DEV-SIG-v1: M5ODg7Uko8xwh7BcXatufIx1TvOTi0x48cYVuEHoEN6yxcn80Nu3kF2yZORU5zdvzFMUkYPZdHF6Cwq57l9gz8yi48IUkjDuDAF0fXmI875_OUGyDq2YKPzK96wLGzmrxVLly_l0JVVfXg==
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import json
from datetime import datetime

from sqlalchemy.orm import Session

from .models import Notification

ORIGINS = ("auth", "billing", "checkout", "membership", "kyc", "vault")


def notify(
    db: Session,
    user_id: str,
    *,
    origin: str,
    kind: str,
    title: str,
    body: str = "",
    severity: str = "INFO",
    ref: str | None = None,
    meta: dict | None = None,
) -> Notification | None:
    """Encola una notificación para el usuario. No hace commit (lo hace el caller)."""
    if not user_id or origin not in ORIGINS:
        return None
    n = Notification(
        user_id=user_id,
        origin=origin,
        kind=kind,
        title=(title or kind)[:160],
        body=body or None,
        severity=severity if severity in ("INFO", "WARNING", "CRITICAL") else "INFO",
        ref=(ref[:120] if ref else None),
        meta_json=json.dumps(meta or {}, ensure_ascii=False) if meta else None,
        is_read=False,
        created_at=datetime.utcnow(),
    )
    db.add(n)
    return n
