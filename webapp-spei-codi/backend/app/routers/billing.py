"""Módulo 3: Cobranza y solicitudes de pago (Mensajería CoDi - Apéndice AD)."""

# SC-DEV-SIG-v1: ylkR3R9hsBSpOQPd-8WvEUatXv7JBN5vw5xgQHZvwRAY8PljyM94FsUhJSxDZwBF72KtDXXBqVjuWNpwC9K_vuxNWM1Jk3D5bukEDQoySE7mgf2mD1guxrYNhuuMPo0eJKEnhYBUd6tCrug=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import json
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..notify import notify
from ..alias_norm import find_user_by_alias
from ..config import settings
from ..crypto import hash_password
from ..database import get_db
from ..kyc_limits import assert_abono_within_kyc, assert_min_kyc_level
from ..models import Charge, Favorite, User, VaultAccount
from ..schemas import ChargeIn, ChargeOut, FavoriteOut
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/billing", tags=["3. Cobranza CoDi (Apéndice AD)"])
BASE_URL = "https://www.superclabe.mx"
EXP_UNIT_MINUTES = {"min": 1, "hrs": 60, "dias": 1440}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "comercio").lower()).strip("-")
    return s or "comercio"


def _target_alias(db, c: Charge):
    if not c.target_user_id:
        return None
    u = db.query(User).filter(User.id == c.target_user_id).first()
    return u.alias if u else None


FREQ_DAYS = {"DAILY": 1, "WEEKLY": 7, "MONTHLY": 30}


def _resolve_frequency(body) -> tuple[str, int | None]:
    """Normaliza frecuencia: con 1 uso siempre NONE; CUSTOM exige days."""
    freq = (body.frequency or "NONE").upper()
    if body.max_uses <= 1 or freq == "NONE":
        return "NONE", None
    if freq == "CUSTOM":
        days = body.frequency_every_days
        if not days or days < 1:
            raise HTTPException(422, "La frecuencia personalizada requiere el intervalo en días (≥ 1)")
        return "CUSTOM", int(days)
    if freq not in FREQ_DAYS:
        raise HTTPException(422, "Frecuencia inválida")
    return freq, FREQ_DAYS[freq]


def _qr_payload(c: Charge, holder: str, bank: str, target_alias=None) -> str:
    """Contenido del QR: Mensaje de Cobro CoDi con todo lo necesario para pagar."""
    return json.dumps({
        "v": 1, "type": "CODI_CHARGE", "folio": c.folio_codi,
        "amount": (float(c.amount) if c.amount is not None else None),
        "openAmount": bool(c.open_amount),
        "concept": c.payment_concept, "ref": c.numeric_reference, "holder": holder,
        "bank": bank, "requiresPin": bool(c.requires_pin),
        "chargeType": c.charge_type, "target": target_alias, "maxUses": c.max_uses,
        "frequency": getattr(c, "frequency", None) or "NONE",
        "frequencyEveryDays": getattr(c, "frequency_every_days", None),
        "payTo": (holder if c.show_payee else None),
        "url": f"{BASE_URL}/{c.slug}/{c.folio_codi}",
    }, ensure_ascii=False)


def _to_out(c: Charge, db=None) -> ChargeOut:
    holder, bank, target_alias, owner_alias = "", "", None, None
    if db is not None:
        acc = db.query(VaultAccount).filter(VaultAccount.id == c.destination_account_id).first()
        if acc:
            holder, bank = acc.account_holder, acc.bank_name
        target_alias = _target_alias(db, c)
        owner = db.query(User).filter(User.id == c.user_id).first()
        owner_alias = owner.alias if owner else None
    return ChargeOut(charge_id=c.id, folio_codi=c.folio_codi,
                     payment_url=f"{BASE_URL}/{c.slug}/{c.folio_codi}",
                     qr_payload=_qr_payload(c, holder, bank, target_alias),
                     amount=(float(c.amount) if c.amount is not None else None),
                     open_amount=bool(c.open_amount), charge_type=c.charge_type,
                     target_alias=target_alias, owner_alias=owner_alias,
                     payment_concept=c.payment_concept,
                     max_uses=c.max_uses, uses_count=c.uses_count,
                     frequency=getattr(c, "frequency", None) or "NONE",
                     frequency_every_days=getattr(c, "frequency_every_days", None),
                     last_paid_at=getattr(c, "last_paid_at", None),
                     show_payee=bool(c.show_payee), numeric_reference=c.numeric_reference,
                     status=c.status, reminders_sent=c.reminders_sent, created_at=c.created_at)


@router.post("/charges", response_model=ChargeOut, status_code=201)
def create_charge(body: ChargeIn, request: Request,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Perfil Financiero nivel mínimo 2 para poder cobrar
    assert_min_kyc_level(user, role="generar cobros", as_self=True)
    acc = db.query(VaultAccount).filter(
        VaultAccount.id == body.destination_account_id, VaultAccount.user_id == user.id).first()
    if not acc:
        raise HTTPException(404, "Cuenta destino no encontrada en tu bóveda")
    if user.membership and user.membership.status == "blocked":
        raise HTTPException(402, "Membresía bloqueada por saldo insuficiente. Recarga para continuar.")

    # Monto: fijo o libre (lo decide el pagador)
    if body.open_amount:
        amount = None
    else:
        if not body.amount or body.amount <= 0:
            raise HTTPException(422, "Indica un monto válido o marca 'monto libre'")
        amount = round(body.amount, 2)
        # Tope de ABONOS del beneficiario (quien cobrará / recibirá)
        assert_abono_within_kyc(db, user, amount, role="recibir este cobro", as_self=True)

    # Tipo de cobro: OPEN (cualquiera) o TARGETED (dirigido a un usuario del sistema)
    target_user_id = None
    if body.charge_type == "TARGETED":
        if not body.target_alias:
            raise HTTPException(422, "Un cobro personalizado requiere el alias del usuario destino")
        target = find_user_by_alias(db, body.target_alias)
        if not target:
            raise HTTPException(404, "Usuario destino no encontrado en el sistema")
        target_user_id = target.id
        # El pagador destino no se limita por abonos (el tope aplica al receptor del dinero)

    frequency, freq_days = _resolve_frequency(body)
    minutes = body.expiration_value * EXP_UNIT_MINUTES[body.expiration_unit]
    folio = "FOL" + datetime.utcnow().strftime("%Y%m%d%H%M%S") + str(body.numeric_reference)[-4:]
    slug = _slug(acc.account_holder)
    charge = Charge(
        user_id=user.id, destination_account_id=acc.id, folio_codi=folio, slug=slug,
        amount=amount, open_amount=body.open_amount, payment_concept=body.payment_concept,
        numeric_reference=body.numeric_reference,
        charge_type=body.charge_type, target_user_id=target_user_id,
        max_uses=body.max_uses, uses_count=0, show_payee=body.show_payee,
        frequency=frequency, frequency_every_days=freq_days, last_paid_at=None,
        expiration_at=datetime.utcnow() + timedelta(minutes=minutes),
        requires_pin=body.requires_pin,
        pin_hash=hash_password(body.pin) if (body.requires_pin and body.pin) else None,
        payer_name=body.payer_name, payer_phone=body.payer_phone, status="PENDING",
    )
    db.add(charge)
    amt_txt = "monto libre" if amount is None else f"${float(amount):,.2f}"
    notify(db, user.id, origin="billing", kind="CHARGE_CREATED",
           title="Cobro CoDi generado",
           body=f"Folio {folio} · {body.payment_concept} · {amt_txt}",
           ref=folio,
           meta={"charge_type": body.charge_type, "target": body.target_alias})
    if target_user_id:
        notify(db, target_user_id, origin="billing", kind="CHARGE_REQUEST_RECEIVED",
               title="Nueva solicitud de cobro",
               body=f"{user.alias} te solicita un pago: {body.payment_concept} ({amt_txt}). Revísalo en Pagar → Cobros recibidos.",
               severity="WARNING", ref=folio,
               meta={"from": user.alias, "concept": body.payment_concept})
    db.commit()
    db.refresh(charge)
    write_audit(db, user.alias, "CHARGE_CREATED", "payment_initiation",
                request.client.host if request.client else "0.0.0.0",
                details={"folio": folio, "amount": ("libre" if amount is None else float(amount)),
                         "type": body.charge_type, "target": body.target_alias,
                         "max_uses": body.max_uses, "frequency": frequency,
                         "frequency_every_days": freq_days})
    return _to_out(charge, db)


@router.get("/charges", response_model=list[ChargeOut])
def list_charges(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Marca expirados on-the-fly
    now = datetime.utcnow()
    charges = db.query(Charge).filter(Charge.user_id == user.id).order_by(Charge.created_at.desc()).all()
    changed = False
    for c in charges:
        if c.status == "PENDING" and c.expiration_at and c.expiration_at.replace(tzinfo=None) < now:
            c.status = "EXPIRED"
            changed = True
    if changed:
        db.commit()
    return [_to_out(c, db) for c in charges]


@router.get("/charges/payable", response_model=list[ChargeOut])
def list_payable_charges(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Cobros pendientes dirigidos al usuario autenticado (recibidos de otros)."""
    now = datetime.utcnow()
    charges = (
        db.query(Charge)
        .filter(
            Charge.target_user_id == user.id,
            Charge.user_id != user.id,
            Charge.charge_type == "TARGETED",
            Charge.status == "PENDING",
        )
        .order_by(Charge.created_at.desc())
        .all()
    )
    changed = False
    alive = []
    for c in charges:
        if c.expiration_at and c.expiration_at.replace(tzinfo=None) < now:
            c.status = "EXPIRED"
            changed = True
        else:
            alive.append(c)
    if changed:
        db.commit()
    return [_to_out(c, db) for c in alive]


@router.post("/charges/{charge_id}/remind")
def remind(charge_id: str, request: Request,
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    charge = db.query(Charge).filter(Charge.id == charge_id, Charge.user_id == user.id).first()
    if not charge:
        raise HTTPException(404, "Cobro no encontrado")
    if charge.reminders_sent >= settings.MAX_WHATSAPP_REMINDERS:
        raise HTTPException(429, f"Límite de {settings.MAX_WHATSAPP_REMINDERS} recordatorios alcanzado")
    charge.reminders_sent += 1
    notify(db, user.id, origin="billing", kind="CHARGE_REMINDER_SENT",
           title="Recordatorio enviado",
           body=f"Recordatorio {charge.reminders_sent} del cobro {charge.folio_codi}.",
           ref=charge.folio_codi)
    if charge.target_user_id:
        notify(db, charge.target_user_id, origin="billing", kind="CHARGE_REMINDER",
               title="Recordatorio de pago pendiente",
               body=f"{user.alias} te recuerda el cobro {charge.folio_codi}: {charge.payment_concept}.",
               severity="WARNING", ref=charge.folio_codi,
               meta={"from": user.alias})
    db.commit()
    write_audit(db, user.alias, "WHATSAPP_REMINDER_SENT", "payment_initiation",
                request.client.host if request.client else "0.0.0.0",
                details={"folio": charge.folio_codi, "n": charge.reminders_sent})
    return {"charge_id": charge.id, "reminders_sent": charge.reminders_sent,
            "reminders_remaining": settings.MAX_WHATSAPP_REMINDERS - charge.reminders_sent,
            "last_sent_at": datetime.utcnow(), "status": "SENT"}


# ---------- Búsqueda de usuarios y lista de favoritos (cobros CoDi) ----------
def _user_out(u: User) -> FavoriteOut:
    return FavoriteOut(alias=u.alias, display_name=u.display_name,
                       client_type=u.client_type, kyc_level=u.kyc_level)


@router.get("/users/search", response_model=list[FavoriteOut])
def search_users(q: str = "", limit: int = 8,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Busca usuarios del sistema por alias, nombre o correo (excluye al propio)."""
    query = db.query(User).filter(User.id != user.id)
    if q:
        like = f"%{q.lower()}%"
        from sqlalchemy import func, or_
        query = query.filter(or_(
            func.lower(User.alias).like(like),
            func.lower(func.coalesce(User.display_name, "")).like(like),
            func.lower(func.coalesce(User.email, "")).like(like),
        ))
    return [_user_out(u) for u in query.order_by(User.alias).limit(max(1, min(limit, 50))).all()]


@router.get("/favorites", response_model=list[FavoriteOut])
def list_favorites(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    favs = db.query(Favorite).filter(Favorite.owner_id == user.id).all()
    out = []
    for f in favs:
        u = db.query(User).filter(User.id == f.favorite_user_id).first()
        if u:
            out.append(_user_out(u))
    return out


@router.post("/favorites/{alias}", response_model=list[FavoriteOut], status_code=201)
def add_favorite(alias: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = find_user_by_alias(db, alias)
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    if target.id == user.id:
        raise HTTPException(422, "No puedes agregarte a ti mismo")
    exists = db.query(Favorite).filter(
        Favorite.owner_id == user.id, Favorite.favorite_user_id == target.id).first()
    if not exists:
        db.add(Favorite(owner_id=user.id, favorite_user_id=target.id))
        db.commit()
    return list_favorites(user, db)


@router.delete("/favorites/{alias}", response_model=list[FavoriteOut])
def remove_favorite(alias: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = find_user_by_alias(db, alias)
    if target:
        db.query(Favorite).filter(
            Favorite.owner_id == user.id, Favorite.favorite_user_id == target.id).delete()
        db.commit()
    return list_favorites(user, db)
