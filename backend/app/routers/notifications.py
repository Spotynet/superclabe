"""Notificaciones in-app por usuario (campana del topbar)."""

# SC-DEV-SIG-v1: AstrmQbJeOsxgkuXW0rOCxaA75M5vz3ww4-5OLv-VH-e6jL46fHry9U5dUCjCNoZNLpcPXf-6Bt39EfKqTvIXA0Lpr747Ng2cNoeLcdaQYvC0dp2jEHtCstet4mNn6U8iT6sH4La8_J3WBW8nV-e9dk=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Notification, User
from ..schemas import NotificationOut, NotificationUnreadOut
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/notifications", tags=["Notificaciones"])

ORIGIN_LABELS = {
    "auth": "Autenticación",
    "billing": "Cobros",
    "checkout": "Pagos",
    "membership": "Membresía",
    "kyc": "Perfil Financiero",
    "vault": "Bóveda",
}


def _to_out(n: Notification) -> NotificationOut:
    meta = None
    if n.meta_json:
        try:
            meta = json.loads(n.meta_json)
        except Exception:
            meta = None
    return NotificationOut(
        id=n.id,
        origin=n.origin,
        origin_label=ORIGIN_LABELS.get(n.origin, n.origin),
        kind=n.kind,
        title=n.title,
        body=n.body,
        severity=n.severity,
        ref=n.ref,
        meta=meta,
        is_read=bool(n.is_read),
        created_at=n.created_at or datetime.utcnow(),
    )


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    limit: int = Query(default=40, ge=1, le=100),
    unread_only: bool = Query(default=False),
    origin: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    if origin:
        q = q.filter(Notification.origin == origin)
    rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
    return [_to_out(n) for n in rows]


@router.get("/unread-count", response_model=NotificationUnreadOut)
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .count()
    )
    return NotificationUnreadOut(unread=n)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .first()
    )
    if not n:
        raise HTTPException(404, "Notificación no encontrada")
    if not n.is_read:
        n.is_read = True
        db.commit()
        db.refresh(n)
    return _to_out(n)


@router.post("/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .update({Notification.is_read: True}, synchronize_session=False)
    )
    db.commit()
    return {"marked": updated}
