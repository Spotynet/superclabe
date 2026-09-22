"""Módulo 6: Bitácoras de auditoría, conciliación y verificación de integridad."""

# SC-DEV-SIG-v1: vD6DduWorGGix6k1MrSYIwrbVwyD5TK6xNjDE1rSz9fOEyX1FODabSK_enxqp3NGut0hIQ-uA1ssq4B3l4l7aCrK-ADihonMWSIPXNt4UedMjtbS4nJ6VhrAwDPBk_lXvZORrWah6-BqG0yMrRo=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..crypto import chained_hash
from ..database import get_db
from ..models import AuditLog, Transaction, User
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/compliance", tags=["6. Auditoría & Conciliación (Regla 58a)"])
CEP = "https://www.banxico.org.mx/cep/check?folio="


@router.get("/audit-logs")
def audit_logs(event_category: str | None = Query(default=None),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
    if event_category:
        q = q.filter(AuditLog.event_category == event_category)
    logs = q.limit(500).all()
    return {
        "log_entries_count": len(logs),
        "retention_policy": "Mínimo 6 meses (SPEI) y 1 año (Canales Electrónicos)",
        "logs": [{
            "log_id": l.id, "timestamp": l.timestamp, "operator": l.operator,
            "action": l.action, "event_category": l.event_category,
            "client_ip": l.client_ip, "severity": l.severity,
            "details": json.loads(l.details) if l.details else {},
            "integrity_hash": l.integrity_hash,
        } for l in logs],
    }


@router.get("/audit-logs/verify")
def verify_chain(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Recalcula la cadena de hashes y confirma la inmutabilidad de la bitácora."""
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.asc()).all()
    prev = "0" * 64
    broken = None
    for l in logs:
        payload = f"{l.timestamp.isoformat()}|{l.operator}|{l.action}|{l.event_category}|{l.client_ip}|{l.severity}"
        expected = chained_hash(prev, payload)
        if expected != l.integrity_hash:
            broken = l.id
            break
        prev = l.integrity_hash
    return {"total": len(logs), "chain_valid": broken is None, "first_broken_id": broken}


@router.get("/transactions")
def transactions(scope: str = Query(default="all"),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Transacciones del sistema (scope=all) o del usuario actual (scope=me).

    Devuelve alias de emisor y receptor para visibilidad entre dispositivos.
    """
    q = db.query(Transaction).order_by(Transaction.created_at.desc())
    if scope == "me":
        q = q.filter((Transaction.payer_id == user.id) | (Transaction.payee_id == user.id))
    txs = q.limit(1000).all()
    # Mapa de id -> alias para no consultar usuario por transacción
    aliases = {u.id: u.alias for u in db.query(User).all()}
    out = []
    for t in txs:
        out.append({
            "folio": t.folio_codi,
            "payer": aliases.get(t.payer_id),
            "payee": aliases.get(t.payee_id),
            "amount": float(t.amount),
            "fee": float(t.calculated_fee),
            "clave": t.clave_rastreo,
            "status": t.status,
            "settled": t.settled_at,
            "direct": (t.charge_id is None),
            "cep": CEP + t.folio_codi,
        })
    return out


@router.get("/reconciliation")
def reconciliation(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Panel de conciliación con vínculos al CEP (Apéndice E)."""
    txs = db.query(Transaction).filter(Transaction.payee_id == user.id).order_by(
        Transaction.created_at.desc()).all()
    return [{
        "transaction_id": t.id, "folio_codi": t.folio_codi, "amount": float(t.amount),
        "calculated_fee": float(t.calculated_fee), "clave_rastreo": t.clave_rastreo,
        "status": t.status, "settled_at": t.settled_at, "cep_url": CEP + t.folio_codi,
    } for t in txs]
