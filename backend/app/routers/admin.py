"""Módulo 7: Super administración del sistema (gestión, soporte y auditoría).

El super administrador gestiona usuarios (activar/desactivar), membresías
(saldo y estatus), consulta movimientos, perfiles y la bitácora de todo el
sistema. NO opera a nombre de los usuarios: su token no es válido en los
endpoints de cobro, pago, bóveda ni KYC, y aquí nunca se descifran datos
sensibles (CLABE, CURP, RFC, nombre legal) ni se exponen secretos (TOTP, PIN).
"""
import json
import time
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..alias_norm import find_user_by_alias
from ..audit import log_payload, write_audit
from ..crypto import chained_hash, decrypt_aes, encrypt_aes, hash_password, verify_password
from ..database import get_db
from ..fees import fee_tier, money2
from ..kyc_limits import usage_snapshot
from ..models import (AuditLog, Charge, CompanyMetadata, IndividualMetadata, KycDossier,
                      Membership, Transaction, User, VaultAccount)
from ..notify import notify
from ..security import SCOPE_ADMIN, create_access_token, get_current_admin, verify_totp

router = APIRouter(prefix="/api/v1/admin", tags=["7. Super administración"])
CEP = "https://www.banxico.org.mx/cep/check?folio="

MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 15 * 60
_failed_logins: dict[str, list[float]] = {}


class AdminLoginIn(BaseModel):
    alias: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=1, max_length=200)
    totp_code: str = Field(pattern=r"^\d{6}$")


class AdminPasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)
    totp_code: str = Field(pattern=r"^\d{6}$")


class UserStatusIn(BaseModel):
    active: bool
    reason: str = Field(min_length=5, max_length=300)


class MembershipAdjustIn(BaseModel):
    amount: float = Field(description="Positivo acredita, negativo debita")
    reason: str = Field(min_length=5, max_length=300)


class MembershipStatusIn(BaseModel):
    status: str = Field(pattern="^(active|suspended|blocked)$")
    reason: str = Field(min_length=5, max_length=300)


class ExpedienteEditIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)
    email: str | None = Field(default=None, max_length=255)
    fields: dict[str, str] = Field(default_factory=dict)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "0.0.0.0"


def _locked(key: str) -> bool:
    now = time.time()
    recent = [t for t in _failed_logins.get(key, []) if now - t < LOCKOUT_SECONDS]
    _failed_logins[key] = recent
    return len(recent) >= MAX_FAILED_LOGINS


def _managed_user(db: Session, user_id: str) -> User:
    """Sólo usuarios operativos son gestionables (nunca otra cuenta admin)."""
    u = db.query(User).filter(User.id == user_id, User.role == "user").first()
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    return u


def _membership(db: Session, u: User) -> Membership:
    m = db.query(Membership).filter(Membership.user_id == u.id).first()
    if not m:
        m = Membership(user_id=u.id, balance=0, status="active")
        db.add(m)
        db.flush()
    return m


def _user_row(db: Session, u: User) -> dict:
    m = u.membership
    return {
        "user_id": u.id, "alias": u.alias, "client_type": u.client_type,
        "display_name": u.display_name, "phone_number": u.phone_number, "email": u.email,
        "kyc_level": u.kyc_level, "is_active": u.is_active, "created_at": u.created_at,
        "membership_balance": float(m.balance) if m else 0.0,
        "membership_status": m.status if m else "active",
    }


def _fee_rate(amount) -> float:
    """Tasa del rango v5 que se aplicó al monto (antes de I.V.A.)."""
    return float(fee_tier(float(amount))["rate"])


def _tx_out(t: Transaction, aliases: dict) -> dict:
    return {
        "transaction_id": t.id, "folio": t.folio_codi,
        "payer": aliases.get(t.payer_id), "payee": aliases.get(t.payee_id),
        "amount": float(t.amount), "fee": float(t.calculated_fee),
        "fee_rate": _fee_rate(t.amount),
        "clave": t.clave_rastreo, "status": t.status,
        "direct": t.charge_id is None, "settled": t.settled_at, "created": t.created_at,
        "cep": CEP + t.folio_codi,
    }


def _alias_map(db: Session, txs) -> dict:
    ids = {t.payer_id for t in txs} | {t.payee_id for t in txs}
    ids.discard(None)
    if not ids:
        return {}
    return {u.id: u.alias for u in db.query(User).filter(User.id.in_(ids)).all()}


def _log_out(l: AuditLog) -> dict:
    return {
        "log_id": l.id, "timestamp": l.timestamp, "operator": l.operator,
        "action": l.action, "event_category": l.event_category,
        "client_ip": l.client_ip, "severity": l.severity,
        "details": json.loads(l.details) if l.details else {},
        "integrity_hash": l.integrity_hash,
    }


# ---------------- Sesión del super administrador ----------------
@router.post("/login")
def admin_login(body: AdminLoginIn, request: Request, db: Session = Depends(get_db)):
    """Login exclusivo del super admin: alias + contraseña + código 2FA (TOTP)."""
    key = body.alias.strip().lower()
    if _locked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Demasiados intentos fallidos. Espera 15 minutos.")
    user = find_user_by_alias(db, body.alias)
    ok = (user is not None and user.role == "superadmin" and user.is_active
          and user.password_hash and verify_password(body.password, user.password_hash)
          and verify_totp(user.totp_secret, body.totp_code))
    if not ok:
        _failed_logins.setdefault(key, []).append(time.time())
        write_audit(db, body.alias, "ADMIN_LOGIN_FAILED", "admin", _ip(request), severity="WARNING")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales de administrador inválidas")
    _failed_logins.pop(key, None)
    write_audit(db, user.alias, "ADMIN_LOGIN_SUCCESS", "admin", _ip(request))
    return {"access_token": create_access_token(user.id, scope=SCOPE_ADMIN),
            "token_type": "bearer", "alias": user.alias, "display_name": user.display_name}


@router.get("/me")
def admin_me(admin: User = Depends(get_current_admin)):
    return {"alias": admin.alias, "display_name": admin.display_name, "role": admin.role}


@router.post("/me/password")
def admin_change_password(body: AdminPasswordIn, request: Request,
                          admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    if not (verify_password(body.current_password, admin.password_hash or "")
            and verify_totp(admin.totp_secret, body.totp_code)):
        write_audit(db, admin.alias, "ADMIN_PASSWORD_CHANGE_FAILED", "admin", _ip(request), severity="WARNING")
        raise HTTPException(401, "Contraseña actual o código 2FA inválido")
    admin.password_hash = hash_password(body.new_password)
    db.commit()
    write_audit(db, admin.alias, "ADMIN_PASSWORD_CHANGED", "admin", _ip(request), severity="WARNING")
    return {"status": "OK"}


# ---------------- Panorama general ----------------
_MX = ZoneInfo("America/Mexico_City")


def _month_keys(end_d, n: int = 12) -> list[str]:
    """n meses calendario, de más antiguo a más reciente, terminando en end_d."""
    y, m = end_d.year, end_d.month
    keys = []
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y -= 1
            m = 12
    keys.reverse()
    return keys


def _month_expr(db: Session, column):
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "postgresql":
        return func.to_char(func.timezone("America/Mexico_City", column), "YYYY-MM")
    return func.strftime("%Y-%m", column)


def _parse_period(date_from: str | None, date_to: str | None):
    """Días calendario en hora de México. Sin fechas, usa el mes en curso hasta hoy."""
    today = datetime.now(_MX).date()
    try:
        start_d = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else today.replace(day=1)
        end_d = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else today
    except ValueError:
        raise HTTPException(422, "Usa fechas con formato AAAA-MM-DD")
    if end_d < start_d:
        raise HTTPException(422, "La fecha final no puede ser anterior a la inicial")
    start = datetime.combine(start_d, dt_time.min, tzinfo=_MX)
    end = datetime.combine(end_d + timedelta(days=1), dt_time.min, tzinfo=_MX)
    return start, end, start_d.isoformat(), end_d.isoformat()


@router.get("/overview")
def overview(date_from: str | None = Query(default=None, alias="from"),
             date_to: str | None = Query(default=None, alias="to"),
             admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Panorama. Tarifas, volumen y bitácora respetan el periodo; el resto es el estado actual."""
    users_q = db.query(User).filter(User.role == "user")
    total_users = users_q.count()
    active_users = users_q.filter(User.is_active.is_(True)).count()
    start, end, from_iso, to_iso = _parse_period(date_from, date_to)

    def tx_stats(q):
        count, volume, fees = q.with_entities(
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0),
            func.coalesce(func.sum(Transaction.calculated_fee), 0),
        ).one()
        return {"count": int(count), "volume": money2(volume), "fees": money2(fees)}

    period_tx = db.query(Transaction).filter(
        Transaction.status == "PROCESSED",
        Transaction.settled_at >= start,
        Transaction.settled_at < end,
    )
    stats = tx_stats(period_tx)
    rate_amounts = [float(amount) for (amount,) in db.query(Transaction.amount).filter(
        Transaction.status == "PROCESSED",
        Transaction.settled_at >= start,
        Transaction.settled_at < end,
    ).all()]
    stats["avg_fee_rate"] = (
        round(sum(_fee_rate(amount) for amount in rate_amounts) / len(rate_amounts), 6)
        if rate_amounts else None
    )
    audit_n = db.query(AuditLog).filter(
        AuditLog.timestamp >= start, AuditLog.timestamp < end,
    ).count()
    keys = _month_keys(datetime.strptime(to_iso, "%Y-%m-%d").date())
    window_start = datetime.combine(
        datetime.strptime(keys[0] + "-01", "%Y-%m-%d").date(), dt_time.min, tzinfo=_MX,
    )
    user_month = _month_expr(db, User.created_at)
    users_by_month = {
        str(month): int(count)
        for month, count in db.query(user_month, func.count(User.id)).filter(
            User.role == "user",
            User.created_at >= window_start,
            User.created_at < end,
        ).group_by(user_month).all()
        if month
    }
    tx_month = _month_expr(db, Transaction.settled_at)
    ops_by_month = {}
    for month, count, volume, fees in (
        db.query(
            tx_month,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0),
            func.coalesce(func.sum(Transaction.calculated_fee), 0),
        ).filter(
            Transaction.status == "PROCESSED",
            Transaction.settled_at.isnot(None),
            Transaction.settled_at >= window_start,
            Transaction.settled_at < end,
        ).group_by(tx_month).all()
    ):
        if month:
            ops_by_month[str(month)] = {
                "operations": int(count), "volume": money2(volume), "fees": money2(fees),
            }
    months = []
    for key in keys:
        ops = ops_by_month.get(key, {})
        months.append({
            "month": key,
            "users": users_by_month.get(key, 0),
            "operations": ops.get("operations", 0),
            "volume": ops.get("volume", 0.0),
            "fees": ops.get("fees", 0.0),
        })
    return {
        "period": {"from": from_iso, "to": to_iso, **stats},
        "users": {"total": total_users, "active": active_users, "inactive": total_users - active_users},
        "memberships": {
            "total_balance": money2(db.query(func.coalesce(func.sum(Membership.balance), 0)).scalar()),
            "blocked": db.query(Membership).filter(Membership.status == "blocked").count(),
            "suspended": db.query(Membership).filter(Membership.status == "suspended").count(),
        },
        "charges_pending": {
            "count": db.query(Charge).filter(Charge.status == "PENDING").count(),
            "amount": money2(db.query(func.coalesce(func.sum(Charge.amount), 0)).filter(
                Charge.status == "PENDING",
                Charge.open_amount.is_(False),
                Charge.amount.isnot(None),
            ).scalar()),
            "open": db.query(Charge).filter(
                Charge.status == "PENDING", Charge.open_amount.is_(True),
            ).count(),
        },
        "audit_entries": audit_n,
        "months": months,
    }


# ---------------- Usuarios ----------------
@router.get("/users")
def list_users(q: str = "", status_filter: str = Query(default="all", alias="status"),
               limit: int = 50, offset: int = 0,
               admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    query = db.query(User).filter(User.role == "user")
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.filter(or_(
            func.lower(User.alias).like(like),
            func.lower(func.coalesce(User.display_name, "")).like(like),
            func.coalesce(User.phone_number, "").like(like),
            func.lower(func.coalesce(User.email, "")).like(like),
        ))
    if status_filter == "active":
        query = query.filter(User.is_active.is_(True))
    elif status_filter == "inactive":
        query = query.filter(User.is_active.is_(False))
    total = query.count()
    rows = (query.order_by(User.created_at.desc())
            .offset(max(0, offset)).limit(max(1, min(limit, 200))).all())
    ids = [u.id for u in rows]
    fees = {}
    if ids:
        for payee_id, total_fee in (
            db.query(Transaction.payee_id, func.coalesce(func.sum(Transaction.calculated_fee), 0))
            .filter(Transaction.payee_id.in_(ids), Transaction.status == "PROCESSED")
            .group_by(Transaction.payee_id)
            .all()
        ):
            fees[payee_id] = money2(total_fee)
    items = []
    for u in rows:
        row = _user_row(db, u)
        row["fees_paid"] = fees.get(u.id, 0.0)
        items.append(row)
    return {"total": total, "items": items}


@router.get("/users/{user_id}")
def user_detail(user_id: str, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Perfil de soporte: datos de contacto y estado, sin datos sensibles descifrados."""
    u = _managed_user(db, user_id)
    snap = usage_snapshot(db, u)
    ind = db.query(IndividualMetadata).filter(IndividualMetadata.id == u.id).first()
    com = db.query(CompanyMetadata).filter(CompanyMetadata.id == u.id).first()
    kyc_docs = {}
    if ind:
        kyc_docs = {"curp_registrada": bool(ind.curp_encrypted), "identificacion_frente": bool(ind.id_front_path),
                    "identificacion_reverso": bool(ind.id_back_path), "selfie": bool(ind.selfie_liveness_path)}
    if com:
        kyc_docs = {"rfc_registrado": bool(com.rfc_encrypted), "constancia_fiscal": bool(com.csf_pdf_url)}
    accounts = db.query(VaultAccount).filter(VaultAccount.user_id == u.id).all()
    tx_q = db.query(Transaction).filter((Transaction.payer_id == u.id) | (Transaction.payee_id == u.id))
    return {
        **_user_row(db, u),
        "representative_name": u.representative_name,
        "business_name": com.business_name if com else None,
        "kyc": {**snap, "documents": kyc_docs},
        "vault_accounts": [{
            "account_id": a.id, "alias": a.alias, "bank_name": a.bank_name,
            "account_holder": a.account_holder, "clabe_masked": a.clabe_masked,
            "is_validated": a.is_validated, "created_at": a.created_at,
        } for a in accounts],
        "stats": {
            "transactions": tx_q.count(),
            "received": money2(tx_q.filter(Transaction.payee_id == u.id)
                               .with_entities(func.coalesce(func.sum(Transaction.amount), 0)).scalar()),
            "sent": money2(tx_q.filter(Transaction.payer_id == u.id)
                           .with_entities(func.coalesce(func.sum(Transaction.amount), 0)).scalar()),
            "fees_paid": money2(tx_q.filter(Transaction.payee_id == u.id)
                                .with_entities(func.coalesce(func.sum(Transaction.calculated_fee), 0)).scalar()),
            "charges": db.query(Charge).filter(Charge.user_id == u.id).count(),
        },
    }


_DOSSIER_FIELDS = (
    ("full_name", "Nombre completo"),
    ("birth_date", "Fecha de nacimiento"),
    ("gender", "Género"),
    ("curp", "CURP"),
    ("address", "Domicilio"),
    ("id_doc_type", "Documento de identidad"),
    ("rfc", "RFC"),
    ("business_name", "Razón social"),
    ("representative_name", "Representante legal"),
)
_FIELD_LABEL = dict(_DOSSIER_FIELDS)
_FIELD_MAX = {
    "full_name": 150, "birth_date": 20, "gender": 30, "curp": 18, "address": 300,
    "id_doc_type": 40, "rfc": 13, "business_name": 150, "representative_name": 150,
}
_EDIT_BY_TYPE = {
    "individual": ("full_name", "birth_date", "gender", "curp", "address", "id_doc_type", "rfc"),
    "company": ("business_name", "rfc", "representative_name", "address", "id_doc_type"),
}
_REQUIRED_IDENTITY = {
    "individual": ("curp", "full_name"),
    "company": ("rfc", "business_name", "representative_name"),
}


def _plain(token: str | None) -> str:
    if not token:
        return ""
    try:
        return (decrypt_aes(token) or "").strip()
    except Exception:
        return ""


def _dossier_payload(db: Session, u: User) -> tuple[dict, object]:
    row = db.query(KycDossier).filter(KycDossier.user_id == u.id).first()
    if not row:
        return {}, None
    try:
        data = json.loads(decrypt_aes(row.payload_encrypted) or "{}")
    except Exception:
        data = {}
    return (data if isinstance(data, dict) else {}), row


def _expediente(db: Session, u: User) -> dict:
    """Datos de registro y validación del Perfil Financiero, con adjuntos."""
    payload, row = _dossier_payload(db, u)
    stored = dict(payload.get("fields") or {})
    ind = db.query(IndividualMetadata).filter(IndividualMetadata.id == u.id).first()
    com = db.query(CompanyMetadata).filter(CompanyMetadata.id == u.id).first()
    if ind:
        stored.setdefault("curp", _plain(ind.curp_encrypted))
        stored.setdefault("full_name", _plain(ind.full_name_encrypted))
    if com:
        stored.setdefault("rfc", _plain(com.rfc_encrypted))
        stored.setdefault("business_name", (com.business_name or "").strip())
        stored.setdefault("representative_name", (com.representative_name or "").strip())
    if u.representative_name:
        stored.setdefault("representative_name", u.representative_name.strip())
    if u.display_name:
        key = "business_name" if u.client_type == "company" else "full_name"
        stored.setdefault(key, u.display_name.strip())
    campos = [{"label": label, "value": stored[key].strip()}
              for key, label in _DOSSIER_FIELDS
              if isinstance(stored.get(key), str) and stored[key].strip()]
    files = []
    seen = set()
    for item in payload.get("files") or []:
        if not isinstance(item, dict) or item.get("id") in seen:
            continue
        data = item.get("data") if isinstance(item.get("data"), str) else ""
        if data and not data.startswith("data:"):
            data = ""
        seen.add(item["id"])
        files.append({
            "id": item.get("id"), "label": item.get("label") or "Adjunto",
            "name": item.get("name") or "archivo", "mime": item.get("mime") or "",
            "data": data or None, "note": None,
        })
    legacy = []
    if ind:
        legacy = [
            ("kFront", "Identificación — frente", ind.id_front_path),
            ("kBack", "Identificación — reverso", ind.id_back_path),
            ("kSelfie", "Selfie", ind.selfie_liveness_path),
        ]
    if com and com.csf_pdf_url:
        legacy.append(("kCsf", "Constancia de Situación Fiscal", com.csf_pdf_url))
    for fid, label, path in legacy:
        if fid in seen or not path:
            continue
        files.append({
            "id": fid, "label": label, "name": path, "mime": "", "data": None,
            "note": "Quedó registrado el nombre, sin el archivo.",
        })
    updated = None
    if row is not None:
        updated = row.updated_at
    elif ind is not None:
        updated = ind.updated_at
    elif com is not None:
        updated = com.updated_at
    kind = u.client_type if u.client_type in _EDIT_BY_TYPE else "individual"
    form = [{"key": key, "label": _FIELD_LABEL[key], "value": (stored.get(key) or "").strip()
             if isinstance(stored.get(key), str) else ""}
            for key in _EDIT_BY_TYPE[kind]]
    return {
        "alias": u.alias,
        "registro": {
            "tipo": "Empresa" if u.client_type == "company" else "Persona física",
            "celular": u.phone_number, "correo": u.email or "", "alias": u.alias,
            "alta": u.created_at, "nombre": u.display_name,
        },
        "validacion": {"nivel": u.kyc_level, "actualizado": updated, "campos": campos},
        "form": form,
        "adjuntos": files,
    }


def _clean_field(key: str, value: str) -> str:
    value = " ".join(value.split())
    if key in ("curp", "rfc"):
        value = value.upper().replace(" ", "")
    return value[:_FIELD_MAX[key]]


def _apply_identity(db: Session, u: User, fields: dict, changed: set) -> None:
    """Refleja CURP, RFC y nombres en las tablas que ya usa el perfil."""
    if u.client_type == "individual":
        ind = db.query(IndividualMetadata).filter(IndividualMetadata.id == u.id).first()
        curp, name = fields.get("curp") or "", fields.get("full_name") or ""
        identity = {"curp", "full_name"} & changed
        if ind:
            if not curp or not name:
                raise HTTPException(422, "La CURP y el nombre completo no pueden quedar vacíos")
            ind.curp_encrypted = encrypt_aes(curp)
            ind.full_name_encrypted = encrypt_aes(name)
            u.display_name = name
        elif identity:
            if not curp or not name:
                raise HTTPException(422, "Para registrar la identidad hacen falta la CURP y el nombre completo")
            db.add(IndividualMetadata(id=u.id, curp_encrypted=encrypt_aes(curp),
                                      full_name_encrypted=encrypt_aes(name)))
            u.display_name = name
        return
    com = db.query(CompanyMetadata).filter(CompanyMetadata.id == u.id).first()
    rfc = fields.get("rfc") or ""
    business = fields.get("business_name") or ""
    rep = fields.get("representative_name") or ""
    identity = {"rfc", "business_name", "representative_name"} & changed
    if com:
        if not rfc or not business or not rep:
            raise HTTPException(422, "El RFC, la razón social y el representante no pueden quedar vacíos")
        com.rfc_encrypted = encrypt_aes(rfc)
        com.business_name = business
        com.representative_name = rep
        u.display_name = business
        u.representative_name = rep
    elif identity:
        if not rfc or not business or not rep:
            raise HTTPException(422, "Para registrar la empresa hacen falta RFC, razón social y representante")
        db.add(CompanyMetadata(id=u.id, rfc_encrypted=encrypt_aes(rfc),
                               business_name=business, representative_name=rep))
        u.display_name = business
        u.representative_name = rep


@router.get("/users/{user_id}/expediente")
def user_expediente(user_id: str, request: Request,
                    admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Expediente de registro y validación. La consulta queda en la bitácora."""
    u = _managed_user(db, user_id)
    out = _expediente(db, u)
    write_audit(db, admin.alias, "ADMIN_EXPEDIENTE_VIEW", "admin", _ip(request),
                details={"user": u.alias})
    return out


@router.post("/users/{user_id}/expediente")
def edit_expediente(user_id: str, body: ExpedienteEditIn, request: Request,
                    admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Corrige datos del expediente. El alias y el celular no se modifican."""
    u = _managed_user(db, user_id)
    kind = u.client_type if u.client_type in _EDIT_BY_TYPE else "individual"
    allowed = set(_EDIT_BY_TYPE[kind])
    unknown = set(body.fields) - allowed
    if unknown:
        raise HTTPException(422, "Hay datos que no corresponden a este tipo de usuario")
    payload, row = _dossier_payload(db, u)
    stored = dict(payload.get("fields") or {})
    shown = {item["key"]: _clean_field(item["key"], item.get("value") or "")
             for item in _expediente(db, u)["form"]}
    cleaned = {key: _clean_field(key, body.fields.get(key, shown.get(key, "")))
               for key in allowed}
    for key, value in cleaned.items():
        if key == "curp" and value and len(value) != 18:
            raise HTTPException(422, "La CURP debe tener 18 caracteres")
        if key == "rfc" and value and not (12 <= len(value) <= 13):
            raise HTTPException(422, "El RFC debe tener 12 o 13 caracteres")
        if key == "birth_date" and value and len(value) > 20:
            raise HTTPException(422, "La fecha de nacimiento no es válida")
    email = (body.email or "").strip() or None
    if email and (email.count("@") != 1 or "." not in email.split("@")[-1] or " " in email):
        raise HTTPException(422, "El correo no es válido")
    changed = []
    if email != (u.email or None):
        u.email = email
        changed.append("correo")
    if cleaned != shown:
        field_changes = {key for key in allowed if cleaned[key] != shown[key]}
        changed.extend(field_changes)
        _apply_identity(db, u, cleaned, field_changes)
        for key, value in cleaned.items():
            if value:
                stored[key] = value
            else:
                stored.pop(key, None)
        blob = encrypt_aes(json.dumps({"fields": stored, "files": payload.get("files") or []},
                                      ensure_ascii=False))
        if row:
            row.payload_encrypted = blob
            row.updated_at = datetime.utcnow()
        else:
            db.add(KycDossier(user_id=u.id, payload_encrypted=blob))
    if not changed:
        return _expediente(db, u)
    write_audit(db, admin.alias, "ADMIN_EXPEDIENTE_EDIT", "admin", _ip(request), severity="WARNING",
                details={"user": u.alias, "fields": changed, "reason": body.reason})
    return _expediente(db, u)


@router.get("/users/{user_id}/transactions")
def user_transactions(user_id: str, limit: int = 200,
                      admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    u = _managed_user(db, user_id)
    txs = (db.query(Transaction)
           .filter((Transaction.payer_id == u.id) | (Transaction.payee_id == u.id))
           .order_by(Transaction.created_at.desc()).limit(max(1, min(limit, 1000))).all())
    aliases = _alias_map(db, txs)
    rows = []
    for t in txs:
        row = _tx_out(t, aliases)
        # La tarifa se descuenta solo de quien cobra (el beneficiario).
        charged = t.payee_id == u.id
        row["fee_charged_here"] = charged
        if not charged:
            row["fee"] = None
            row["fee_rate"] = None
        rows.append(row)
    return rows


@router.get("/users/{user_id}/charges")
def user_charges(user_id: str, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Cobros del usuario (sólo lectura: sin PIN ni capacidad de modificarlos)."""
    u = _managed_user(db, user_id)
    charges = db.query(Charge).filter(Charge.user_id == u.id).order_by(Charge.created_at.desc()).limit(200).all()
    ids = [c.id for c in charges]
    rates_by_charge: dict = {}
    if ids:
        paid = (db.query(Transaction)
                .filter(Transaction.charge_id.in_(ids), Transaction.status == "PROCESSED")
                .order_by(Transaction.settled_at.asc(), Transaction.created_at.asc())
                .all())
        for t in paid:
            rates = rates_by_charge.setdefault(t.charge_id, [])
            rate = _fee_rate(t.amount)
            if rate not in rates:
                rates.append(rate)
    return [{
        "charge_id": c.id, "folio": c.folio_codi, "concept": c.payment_concept,
        "amount": float(c.amount) if c.amount is not None else None, "open_amount": bool(c.open_amount),
        "charge_type": c.charge_type, "status": c.status, "uses": f"{c.uses_count}/{c.max_uses}",
        "requires_pin": bool(c.requires_pin), "created_at": c.created_at, "expiration_at": c.expiration_at,
        "fee_rates": rates_by_charge.get(c.id, []),
    } for c in charges]


@router.get("/users/{user_id}/audit")
def user_audit(user_id: str, limit: int = 200,
               admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    u = _managed_user(db, user_id)
    logs = (db.query(AuditLog).filter(AuditLog.operator == u.alias)
            .order_by(AuditLog.timestamp.desc()).limit(max(1, min(limit, 1000))).all())
    return [_log_out(l) for l in logs]


@router.post("/users/{user_id}/status")
def set_user_status(user_id: str, body: UserStatusIn, request: Request,
                    admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Activa o desactiva un usuario. Desactivado: no entra, no cobra, no paga, no recibe."""
    u = _managed_user(db, user_id)
    if u.is_active == body.active:
        return _user_row(db, u)
    u.is_active = body.active
    if body.active:
        notify(db, u.id, origin="auth", kind="USER_REACTIVATED", title="Cuenta reactivada",
               body="Tu cuenta fue reactivada por soporte. Ya puedes operar de nuevo.")
    db.commit()
    write_audit(db, admin.alias, "ADMIN_USER_ACTIVATED" if body.active else "ADMIN_USER_DEACTIVATED",
                "admin", _ip(request), severity="WARNING",
                details={"user": u.alias, "reason": body.reason})
    return _user_row(db, u)


@router.post("/users/{user_id}/membership/adjust")
def adjust_membership(user_id: str, body: MembershipAdjustIn, request: Request,
                      admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Ajuste administrativo del saldo de membresía (bonificación o corrección)."""
    u = _managed_user(db, user_id)
    amount = money2(body.amount)
    if amount == 0:
        raise HTTPException(422, "El ajuste debe ser distinto de cero")
    m = _membership(db, u)
    prev = float(m.balance)
    new = money2(prev + amount)
    if new < 0:
        raise HTTPException(422, f"El ajuste dejaría el saldo negativo (saldo actual ${prev:,.2f})")
    m.balance = new
    if m.status == "blocked" and new > 0:
        m.status = "active"
    elif new == 0 and m.status == "active":
        m.status = "blocked"
    notify(db, u.id, origin="membership", kind="MEMBERSHIP_ADMIN_ADJUST",
           title="Ajuste de membresía",
           body=(f"Soporte {'acreditó' if amount > 0 else 'debitó'} ${abs(amount):,.2f} a tu membresía. "
                 f"Nuevo saldo: ${new:,.2f}. Motivo: {body.reason}"),
           meta={"amount": amount, "balance": new})
    db.commit()
    write_audit(db, admin.alias, "ADMIN_MEMBERSHIP_ADJUST", "admin", _ip(request), severity="WARNING",
                details={"user": u.alias, "amount": amount, "previous_balance": prev,
                         "new_balance": new, "reason": body.reason})
    return {"balance": new, "status": m.status}


@router.post("/users/{user_id}/membership/status")
def set_membership_status(user_id: str, body: MembershipStatusIn, request: Request,
                          admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    u = _managed_user(db, user_id)
    m = _membership(db, u)
    prev = m.status
    m.status = body.status
    notify(db, u.id, origin="membership", kind="MEMBERSHIP_ADMIN_STATUS",
           title="Estatus de membresía actualizado",
           body=f"Soporte cambió tu membresía a '{body.status}'. Motivo: {body.reason}",
           severity="WARNING" if body.status != "active" else "INFO")
    db.commit()
    write_audit(db, admin.alias, "ADMIN_MEMBERSHIP_STATUS", "admin", _ip(request), severity="WARNING",
                details={"user": u.alias, "previous": prev, "new": body.status, "reason": body.reason})
    return {"balance": float(m.balance), "status": m.status}


# ---------------- Movimientos y bitácora del sistema ----------------
def _users_matching(db: Session, text: str) -> list:
    like = f"%{text.strip().lower()}%"
    return [u.id for u in db.query(User).filter(or_(
        func.lower(User.alias).like(like),
        func.lower(func.coalesce(User.display_name, "")).like(like),
        func.coalesce(User.phone_number, "").like(like),
    )).all()]


@router.get("/transactions")
def all_transactions(q: str = "", user: str = "", kind: str = "",
                     date_from: str | None = Query(default=None, alias="from"),
                     date_to: str | None = Query(default=None, alias="to"),
                     limit: int = 100, offset: int = 0,
                     admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Movimientos del sistema. Fechas en calendario de México; sin fechas, no recorta."""
    if kind not in ("", "all", "direct", "qr"):
        raise HTTPException(422, "Tipo de movimiento no válido")
    query = db.query(Transaction)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        ids = _users_matching(db, q)
        conds = [func.lower(Transaction.folio_codi).like(like),
                 func.lower(func.coalesce(Transaction.clave_rastreo, "")).like(like)]
        if ids:
            conds += [Transaction.payer_id.in_(ids), Transaction.payee_id.in_(ids)]
        query = query.filter(or_(*conds))
    if user.strip():
        ids = _users_matching(db, user)
        if not ids:
            return {"total": 0, "volume": 0.0, "fees": 0.0, "items": []}
        query = query.filter(or_(Transaction.payer_id.in_(ids), Transaction.payee_id.in_(ids)))
    if kind == "direct":
        query = query.filter(Transaction.charge_id.is_(None))
    elif kind == "qr":
        query = query.filter(Transaction.charge_id.isnot(None))
    if date_from or date_to:
        if not date_from or not date_to:
            raise HTTPException(422, "Indica la fecha inicial y la final")
        start, end, _, _ = _parse_period(date_from, date_to)
        stamp = func.coalesce(Transaction.settled_at, Transaction.created_at)
        query = query.filter(stamp >= start, stamp < end)
    total = query.count()
    volume, fees = query.with_entities(
        func.coalesce(func.sum(Transaction.amount), 0),
        func.coalesce(func.sum(Transaction.calculated_fee), 0),
    ).one()
    stamp = func.coalesce(Transaction.settled_at, Transaction.created_at)
    txs = (query.order_by(stamp.desc(), Transaction.created_at.desc())
           .offset(max(0, offset)).limit(max(1, min(limit, 500))).all())
    aliases = _alias_map(db, txs)
    ids = {t.payer_id for t in txs} | {t.payee_id for t in txs}
    ids.discard(None)
    names = {}
    if ids:
        names = {u.id: u.display_name for u in db.query(User).filter(User.id.in_(ids)).all()}
    charge_ids = {t.charge_id for t in txs if t.charge_id}
    concepts = {}
    if charge_ids:
        concepts = {c.id: c.payment_concept
                    for c in db.query(Charge).filter(Charge.id.in_(charge_ids)).all()}
    items = []
    for t in txs:
        row = _tx_out(t, aliases)
        row["payer_name"] = names.get(t.payer_id) or ""
        row["payee_name"] = names.get(t.payee_id) or ""
        row["concept"] = concepts.get(t.charge_id) or ""
        items.append(row)
    return {"total": total, "volume": money2(volume), "fees": money2(fees), "items": items}


@router.get("/audit-logs")
def audit_logs(category: str | None = None, severity: str | None = None, q: str = "",
               limit: int = 100, offset: int = 0,
               admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    query = db.query(AuditLog)
    if category:
        query = query.filter(AuditLog.event_category == category)
    if severity:
        query = query.filter(AuditLog.severity == severity.upper())
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.filter(or_(func.lower(AuditLog.operator).like(like),
                                 func.lower(AuditLog.action).like(like)))
    total = query.count()
    logs = (query.order_by(AuditLog.timestamp.desc())
            .offset(max(0, offset)).limit(max(1, min(limit, 500))).all())
    categories = [c for (c,) in db.query(AuditLog.event_category).distinct().all()]
    return {"total": total, "categories": sorted(categories), "items": [_log_out(l) for l in logs]}


@router.get("/audit-logs/verify")
def verify_chain(admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Recalcula la cadena SHA-256 completa y reporta el primer eslabón roto."""
    prev = "0" * 64
    broken = None
    total = 0
    for l in db.query(AuditLog).order_by(AuditLog.timestamp.asc()).yield_per(500):
        total += 1
        if chained_hash(prev, log_payload(l)) != l.integrity_hash:
            broken = l.id
            break
        prev = l.integrity_hash
    return {"total": total, "chain_valid": broken is None, "first_broken_id": broken,
            "verified_at": datetime.utcnow()}
