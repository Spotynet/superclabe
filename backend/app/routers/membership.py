"""Módulo 5: Gestión de saldo de membresía prepago (tarifa 0.05%)."""

# SC-DEV-SIG-v1: iVi3vbS2VRLUu-6fT8g3J1lcelssO75o9C5Ena1riU20MCx0t03PxWM3g6PGiOG7C8YUTSbBWHs6dqQrFtpY03cXDVPKrpm0dcRQoIQIvF07-yG5KEAEFszuX03PDFRJKmIQE7Zf47dd92o6zP4=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..config import settings
from ..database import get_db
from ..fees import calc_membership_fee, money2
from ..models import Membership, User
from ..notify import notify
from ..schemas import DeductIn, RechargeIn
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/membership", tags=["5. Membresía prepago (0.05% + I.V.A.)"])


def _membership(db, user):
    m = db.query(Membership).filter(Membership.user_id == user.id).first()
    if not m:
        m = Membership(user_id=user.id, balance=0, status="active")
        db.add(m)
        db.commit()
        db.refresh(m)
    return m


@router.get("")
def get_membership(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _membership(db, user)
    return {"balance": float(m.balance), "status": m.status,
            "fee_rate": settings.MEMBERSHIP_FEE_RATE, "iva_rate": settings.IVA_RATE,
            "currency": "MXN"}


@router.post("/recharge")
def recharge(body: RechargeIn, request: Request,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Recarga por transferencia SPEI a la cuenta concentradora (simulada)."""
    m = _membership(db, user)
    amount = round(body.amount, 2)
    m.balance = round(float(m.balance) + amount, 2)
    reactivated = False
    if m.status == "blocked" and m.balance > 0:
        m.status = "active"
        reactivated = True
    notify(db, user.id, origin="membership", kind="MEMBERSHIP_RECHARGE",
           title="Membresía recargada",
           body=f"Se acreditaron ${amount:,.2f}. Nuevo saldo: ${float(m.balance):,.2f}."
                + (" Tu membresía volvió a estar activa." if reactivated else ""),
           meta={"amount": amount, "balance": float(m.balance)})
    db.commit()
    write_audit(db, user.alias, "MEMBERSHIP_RECHARGE", "membership",
                request.client.host if request.client else "0.0.0.0",
                details={"amount": body.amount, "new_balance": float(m.balance)})
    return {"balance": float(m.balance), "status": m.status}


@router.post("/deduct")
def deduct(body: DeductIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Deducción lógica del 0.05% + I.V.A. (procesamiento interno).

    Si el saldo es insuficiente, bloquea la generación de nuevas transacciones
    (402 Payment Required).
    """
    m = _membership(db, user)
    fees = calc_membership_fee(body.transaction_amount)
    fee = fees["total_fee"]
    if float(m.balance) < fee:
        m.status = "blocked"
        notify(db, user.id, origin="membership", kind="MEMBERSHIP_BLOCKED",
               title="Membresía bloqueada",
               body="Saldo insuficiente para procesar la tarifa. Recarga para continuar.",
               severity="CRITICAL", meta={"required_fee": fee})
        db.commit()
        raise HTTPException(402, {
            "error": "INSUFFICIENT_MEMBERSHIP_BALANCE", "current_balance": float(m.balance),
            "required_fee": fee, "base_fee": fees["base_fee"], "iva": fees["iva"],
            "status": "BLOCKED",
            "system_action": "DENY_TRANSACTION_GENERATION",
            "message": "Saldo de membresía insuficiente. Realiza una recarga.",
        })
    prev = float(m.balance)
    m.balance = money2(prev - fee)
    db.commit()
    return {"user_id": user.id, "calculated_fee": fee, "base_fee": fees["base_fee"],
            "iva": fees["iva"], "previous_balance": prev,
            "new_balance": float(m.balance), "status": "APPROVED",
            "system_action": "ALLOW_TRANSACTION"}
