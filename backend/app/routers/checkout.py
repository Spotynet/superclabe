"""Módulo 4: Pasarela de aceptación de pagos (vista pública del pagador).

Cumple homologación UX (Circular 9/2026): logo CoDi, folio, beneficiario
enmascarado (Regla 71a / Dimo), monto, concepto, referencia y vínculo al CEP.
"""

# SC-DEV-SIG-v1: PYgTpqVA28wWI7cB719uyO7484Zyzw9RVNKg9y5NDrLQWaEuvI1mKaWjcZ50EdxjxsNVlZPU6HFED76mPkgHG5QQcXrFDIPHlAERotWN9YUzaT2IZ5vbEw-ZrtrYn1I6AkG3cn60e2CT7Yfh
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..alias_norm import alias_key, find_user_by_alias
from ..crypto import verify_password
from ..database import get_db
from ..fees import calc_membership_fee, money2
from ..kyc_limits import assert_abono_within_kyc, assert_min_kyc_level
from ..models import Charge, Membership, Transaction, User, VaultAccount
from ..notify import notify
from ..schemas import CheckoutOut, DirectPayIn, PayIn, ScanIn
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/checkout", tags=["4. Pagos / Checkout (Regla 71a)"])
CEP = "https://www.banxico.org.mx/cep/check?folio="


def _mask_name(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    return " ".join(p[0].upper() + "***" for p in parts) or "B***"


def _get_charge(db, folio):
    c = db.query(Charge).filter(Charge.folio_codi == folio).first()
    if not c:
        raise HTTPException(404, "Solicitud de cobro no encontrada")
    if c.status == "PENDING" and c.expiration_at and c.expiration_at.replace(tzinfo=None) < datetime.utcnow():
        c.status = "EXPIRED"
        db.commit()
    return c


@router.post("/direct", status_code=201)
def direct_payment(body: DirectPayIn, request: Request,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Envía un pago directo a un usuario del sistema, sin QR de cobro.

    El emisor (usuario autenticado) envía dinero al destinatario. La tarifa de
    software (0.05% + I.V.A.) se cobra SOLAMENTE a la membresía del receptor, ya
    que es un cobro no solicitado. El emisor NO paga comisión.
    """
    # Validación clave: no enviarte pagos a ti mismo
    if alias_key(body.recipient_alias) == alias_key(user.alias):
        raise HTTPException(422, {
            "error": "SELF_PAYMENT",
            "message": "No puedes enviarte pagos a ti mismo.",
        })
    recipient = find_user_by_alias(db, body.recipient_alias)
    if not recipient:
        raise HTTPException(404, "Usuario destinatario no encontrado en el sistema")

    amount = round(body.amount, 2)
    # Emisor: solo nivel mínimo para operar (el tope de montos NO aplica a cargos/envíos)
    assert_min_kyc_level(user, role="enviar pagos", as_self=True)
    # Receptor: tope de ABONOS del mes según su Perfil Financiero (Regla 72a / art. 115)
    assert_abono_within_kyc(db, recipient, amount, role="recibir este pago", as_self=False)
    fees = calc_membership_fee(amount)
    fee = fees["total_fee"]  # 0.05% + I.V.A. sólo al receptor

    # La tarifa de software (0.05% + I.V.A.) se cobra SOLAMENTE a la membresía del receptor.
    recipient_ms = db.query(Membership).filter(Membership.user_id == recipient.id).first()

    if recipient_ms is None or float(recipient_ms.balance) < fee:
        if recipient_ms:
            recipient_ms.status = "blocked"
            notify(db, recipient.id, origin="membership", kind="MEMBERSHIP_BLOCKED",
                   title="Membresía bloqueada",
                   body="Saldo insuficiente para recibir un pago directo. Recarga tu membresía.",
                   severity="CRITICAL",
                   meta={"required_fee": fee, "type": "direct"})
            db.commit()
        write_audit(db, recipient.alias, "FEE_DEDUCTION_BLOCKED", "membership",
                    severity="WARNING", details={"required_fee": fee, "base_fee": fees["base_fee"],
                                                 "iva": fees["iva"], "type": "direct", "party": "receptor"})
        raise HTTPException(402, {
            "error": "INSUFFICIENT_MEMBERSHIP_BALANCE",
            "party": "receptor",
            "required_fee": fee,
            "base_fee": fees["base_fee"],
            "iva": fees["iva"],
            "current_balance": float(recipient_ms.balance) if recipient_ms else 0,
            "message": f"Saldo de membresía insuficiente en el destinatario ({recipient.alias}). Recarga para continuar.",
        })

    recipient_ms.balance = money2(float(recipient_ms.balance) - fee)
    folio = "ENV" + datetime.utcnow().strftime("%Y%m%d%H%M%S")
    clave = "SPEI" + datetime.utcnow().strftime("%y%m%d%H%M%S")
    tx = Transaction(
        charge_id=None, folio_codi=folio, payer_id=user.id, payee_id=recipient.id,
        amount=amount, calculated_fee=fee, clave_rastreo=clave,
        status="PROCESSED", settled_at=datetime.utcnow(),
    )
    db.add(tx)
    concept = body.concept or "Pago directo"
    notify(db, user.id, origin="checkout", kind="DIRECT_PAYMENT_SENT",
           title="Pago directo enviado",
           body=f"Enviaste ${amount:,.2f} a {recipient.alias} · {concept}",
           ref=folio, meta={"recipient": recipient.alias, "clave": clave})
    notify(db, recipient.id, origin="checkout", kind="DIRECT_PAYMENT_RECEIVED",
           title="Pago directo recibido",
           body=f"Recibiste ${amount:,.2f} de {user.alias} · {concept}",
           ref=folio, meta={"from": user.alias, "clave": clave})
    db.commit()
    write_audit(db, user.alias, "DIRECT_PAYMENT_SENT", "payment_initiation",
                request.client.host if request.client else "0.0.0.0",
                details={"folio": folio, "clave_rastreo": clave,
                         "fee_recipient": fee, "base_fee": fees["base_fee"], "iva": fees["iva"],
                         "total_fee": fee, "amount": amount, "recipient": recipient.alias,
                         "concept": body.concept})
    return {
        "status": "PROCESSED", "folio_codi": folio, "clave_rastreo": clave,
        "recipient_alias": recipient.alias, "amount": amount,
        "sender_fee": 0, "recipient_fee": fee, "base_fee": fees["base_fee"],
        "iva": fees["iva"], "total_fee": fee,
        "concept": body.concept or "Pago directo",
        "new_sender_balance": None,
        "new_recipient_balance": float(recipient_ms.balance),
        "cep_url": CEP + folio, "settled_at": datetime.utcnow(),
    }


@router.post("/scan", response_model=CheckoutOut)
def scan_qr(body: ScanIn, db: Session = Depends(get_db)):
    """Decodifica el contenido del QR (Mensaje de Cobro CoDi) y devuelve el checkout."""
    import json
    try:
        data = json.loads(body.qr_payload)
    except Exception:
        raise HTTPException(422, "Contenido de QR inválido")
    if data.get("type") != "CODI_CHARGE" or not data.get("folio"):
        raise HTTPException(422, "El QR no es un Mensaje de Cobro CoDi")
    return get_checkout(data["folio"], db)


@router.get("/{folio}", response_model=CheckoutOut)
def get_checkout(folio: str, db: Session = Depends(get_db)):
    c = _get_charge(db, folio)
    acc = db.query(VaultAccount).filter(VaultAccount.id == c.destination_account_id).first()
    target_alias = None
    if c.target_user_id:
        t = db.query(User).filter(User.id == c.target_user_id).first()
        target_alias = t.alias if t else None
    owner = db.query(User).filter(User.id == c.user_id).first()
    return CheckoutOut(
        charge_id=c.id, folio_codi=c.folio_codi,
        masked_beneficiary_name=_mask_name(acc.account_holder if acc else ""),
        beneficiary_bank=acc.bank_name if acc else "",
        amount=(float(c.amount) if c.amount is not None else None),
        open_amount=bool(c.open_amount), charge_type=c.charge_type,
        target_alias=target_alias, owner_alias=(owner.alias if owner else None),
        max_uses=c.max_uses, uses_count=c.uses_count,
        frequency=getattr(c, "frequency", None) or "NONE",
        frequency_every_days=getattr(c, "frequency_every_days", None),
        last_paid_at=getattr(c, "last_paid_at", None),
        payment_concept=c.payment_concept,
        numeric_reference=c.numeric_reference, requires_pin_validation=c.requires_pin,
        status=c.status, cep_url=CEP + c.folio_codi,
    )


@router.post("/{folio}/pay")
def pay(folio: str, body: PayIn, request: Request, db: Session = Depends(get_db)):
    """Simula la aceptación del pago por el pagador y la liquidación SPEI/CoDi.

    En producción esto lo confirma el banco patrocinador vía webhook; aquí se
    ejecuta el flujo completo: validación de PIN, liquidación y deducción 0.05%.
    """
    c = _get_charge(db, folio)
    if c.status != "PENDING":
        raise HTTPException(409, f"El cobro no está disponible (estado: {c.status})")

    # No puedes pagar tu propio cobro (no te pagas a ti mismo)
    if body.payer_alias:
        owner = db.query(User).filter(User.id == c.user_id).first()
        if owner and alias_key(body.payer_alias) == alias_key(owner.alias):
            raise HTTPException(403, {
                "error": "SELF_PAYMENT",
                "message": "No puedes pagar un cobro que tú mismo generaste.",
            })

    if c.requires_pin:
        if not c.pin_hash or not body.pin or not verify_password(body.pin, c.pin_hash):
            raise HTTPException(401, "PIN de acceso incorrecto")

    # Cobro personalizado: sólo el usuario destino puede pagarlo
    if c.charge_type == "TARGETED":
        target = db.query(User).filter(User.id == c.target_user_id).first()
        if (not body.payer_alias or not target
                or alias_key(body.payer_alias) != alias_key(target.alias)):
            raise HTTPException(403, {
                "error": "TARGETED_CHARGE",
                "message": f"Este cobro personalizado sólo lo puede pagar {target.alias if target else 'el usuario destino'}.",
            })

    # Monto: fijo o libre (lo decide el pagador)
    if c.open_amount:
        if not body.pay_amount or body.pay_amount <= 0:
            raise HTTPException(422, "Este cobro es de monto libre: indica el monto a pagar")
        pay_amount = round(body.pay_amount, 2)
    else:
        pay_amount = float(c.amount)

    # Frecuencia programada: espaciar pagos dentro de la vigencia
    freq = (getattr(c, "frequency", None) or "NONE").upper()
    freq_days = getattr(c, "frequency_every_days", None)
    last_paid = getattr(c, "last_paid_at", None)
    if freq != "NONE" and (c.max_uses or 1) > 1 and last_paid and freq_days:
        next_ok = last_paid.replace(tzinfo=None) + timedelta(days=int(freq_days))
        now = datetime.utcnow()
        if now < next_ok:
            raise HTTPException(409, {
                "error": "FREQUENCY_WAIT",
                "message": (
                    f"Este cobro tiene frecuencia {freq.lower()}. "
                    f"El siguiente pago estará disponible a partir del "
                    f"{next_ok.strftime('%d/%m/%Y %H:%M')} UTC."
                ),
                "next_available_at": next_ok.isoformat() + "Z",
                "frequency": freq,
                "frequency_every_days": int(freq_days),
            })

    beneficiary = db.query(User).filter(User.id == c.user_id).first()
    payer = None
    if body.payer_alias:
        payer = find_user_by_alias(db, body.payer_alias)

    # Tope de ABONOS solo al beneficiario (quien recibe). El pagador no se limita por nivel de abonos.
    if not beneficiary:
        raise HTTPException(404, "Beneficiario del cobro no encontrado")
    assert_abono_within_kyc(
        db, beneficiary, pay_amount,
        role="recibir este cobro",
        as_self=False,
    )
    # Si el pagador es usuario del sistema, exige nivel mínimo para operar (sin tope de monto)
    if payer:
        assert_min_kyc_level(payer, role="realizar este pago", as_self=False)

    # --- Módulo 5: deducción del 0.05% + I.V.A. al beneficiario/emisor de la orden ---
    # (el dueño del cobro paga la tarifa de software; no hay comisión al pagador)
    membership = db.query(Membership).filter(Membership.user_id == beneficiary.id).first()
    fees = calc_membership_fee(pay_amount)
    fee = fees["total_fee"]
    if membership is None or float(membership.balance) < fee:
        if membership:
            membership.status = "blocked"
            notify(db, beneficiary.id, origin="membership", kind="MEMBERSHIP_BLOCKED",
                   title="Membresía bloqueada",
                   body=f"Saldo insuficiente para liquidar el cobro {folio}. Recarga tu membresía.",
                   severity="CRITICAL", ref=folio,
                   meta={"required_fee": fee})
            db.commit()
        write_audit(db, beneficiary.alias, "FEE_DEDUCTION_BLOCKED", "membership",
                    severity="WARNING", details={"folio": folio, "required_fee": fee,
                                                 "base_fee": fees["base_fee"], "iva": fees["iva"]})
        raise HTTPException(402, {
            "error": "INSUFFICIENT_MEMBERSHIP_BALANCE",
            "required_fee": fee,
            "base_fee": fees["base_fee"],
            "iva": fees["iva"],
            "current_balance": float(membership.balance) if membership else 0,
            "system_action": "DENY_TRANSACTION_GENERATION",
            "message": "Saldo de membresía insuficiente para procesar. Recarga para continuar.",
        })

    membership.balance = money2(float(membership.balance) - fee)
    # Conteo de usos: el cobro se cierra sólo cuando se agotan los pagos permitidos
    c.uses_count = (c.uses_count or 0) + 1
    c.last_paid_at = datetime.utcnow()
    exhausted = c.uses_count >= (c.max_uses or 1)
    c.status = "PROCESSED" if exhausted else "PENDING"
    clave = "SPEI" + datetime.utcnow().strftime("%y%m%d%H%M%S")
    tx = Transaction(
        charge_id=c.id, folio_codi=c.folio_codi, payee_id=beneficiary.id,
        payer_id=payer.id if payer else None,
        amount=pay_amount, calculated_fee=fee, clave_rastreo=clave,
        status="PROCESSED", settled_at=datetime.utcnow(),
    )
    db.add(tx)
    payer_alias = payer.alias if payer else (body.payer_alias or "pagador")
    notify(db, beneficiary.id, origin="checkout", kind="PAYMENT_RECEIVED",
           title="Pago recibido",
           body=f"Recibiste ${pay_amount:,.2f} de {payer_alias} · {c.payment_concept} (folio {folio})",
           ref=folio, meta={"from": payer_alias, "clave": clave, "fee": fee})
    if payer:
        notify(db, payer.id, origin="checkout", kind="PAYMENT_SENT",
               title="Pago enviado",
               body=f"Pagaste ${pay_amount:,.2f} a {beneficiary.alias} · {c.payment_concept}",
               ref=folio, meta={"to": beneficiary.alias, "clave": clave})
    db.commit()
    write_audit(db, beneficiary.alias, "PAYMENT_SETTLED", "payment_initiation",
                request.client.host if request.client else "0.0.0.0",
                details={"folio": folio, "clave_rastreo": clave, "fee": fee,
                         "base_fee": fees["base_fee"], "iva": fees["iva"],
                         "amount": pay_amount, "uso": f"{c.uses_count}/{c.max_uses}"})
    return {
        "status": "PROCESSED", "folio_codi": c.folio_codi, "clave_rastreo": clave,
        "liquidated_amount": pay_amount, "calculated_fee": fee,
        "base_fee": fees["base_fee"], "iva": fees["iva"],
        "charge_status": c.status, "uses_count": c.uses_count, "max_uses": c.max_uses,
        "new_membership_balance": float(membership.balance),
        "cep_url": CEP + c.folio_codi, "settled_at": datetime.utcnow(),
    }
