"""Escritura de bitácoras inmutables con hash encadenado (Regla 58a)."""

# SC-DEV-SIG-v1: nZoXOkssQ5xWKfowkDx5GoL0nz_ww6NW305zQ0MKS_Cp6pxJ_oNVXXEY9d-oBDU3ThqBP_OAIF9beJhpU8A2pi1oJ2fQ0O5_GrgFgjeCYKAay74l-n-6lic_lHn3vPXZJG-NrqXkI-V1
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .crypto import chained_hash
from .models import AuditLog


def audit_payload(ts: datetime, operator: str, action: str, category: str,
                  client_ip: str, severity: str) -> str:
    # PostgreSQL (timestamptz) devuelve fechas con zona; el hash se calcula en UTC sin zona.
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return f"{ts.isoformat()}|{operator}|{action}|{category}|{client_ip}|{severity}"


def log_payload(log: AuditLog) -> str:
    return audit_payload(log.timestamp, log.operator, log.action, log.event_category,
                         log.client_ip, log.severity)


def write_audit(db: Session, operator: str, action: str, category: str = "general",
                client_ip: str = "0.0.0.0", severity: str = "INFO", details: dict | None = None) -> AuditLog:
    prev = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).first()
    prev_hash = prev.integrity_hash if prev else "0" * 64
    ts = datetime.utcnow()
    payload = audit_payload(ts, operator, action, category, client_ip, severity)
    entry = AuditLog(
        timestamp=ts, operator=operator, action=action, event_category=category,
        client_ip=client_ip, severity=severity,
        details=json.dumps(details or {}, ensure_ascii=False),
        integrity_hash=chained_hash(prev_hash, payload),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
