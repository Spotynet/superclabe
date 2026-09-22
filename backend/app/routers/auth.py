"""Módulo 1: Registro y login por alias único ($@...), sin contraseña por ahora.

Cada usuario elige tipo de registro (Persona/Empresa) y un alias único que
siempre inicia con $@: celular, alias de correo o personalizado.
"""

# SC-DEV-SIG-v1: t2u28mRazhxRecQeW7xpEzeXkGp0hjIiQV68EBlLtETx5iYEzPArAEEEKEEMbP4ON8z77Stli1rTSRFOPwbZJyw0ksubkSiNu3PS8kMuD8MfQbiA4pRFmybDyRUdjz17UP1I8qOZK5o=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import random
import re
import string

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..notify import notify
from ..database import get_db
from ..kyc_limits import usage_snapshot
from ..alias_norm import alias_taken, find_user_by_alias, normalize_alias
from ..models import Membership, User
from ..schemas import LoginIn, RegisterIn, TokenOut, UserOut
from ..security import (create_access_token, generate_totp_secret,
                        get_current_user, verify_totp)

router = APIRouter(prefix="/api/v1/auth", tags=["1. Auth & Onboarding"])

_ALIAS_REST_RE = re.compile(r"^[A-Za-z0-9._-]{3,}$", re.IGNORECASE)
_PHONE_REST_RE = re.compile(r"^\d{8,15}$")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "0.0.0.0"


def _user_out(u: User, db: Session | None = None) -> UserOut:
    snap = usage_snapshot(db, u) if db is not None else {}
    return UserOut(
        user_id=u.id, alias=u.alias, display_name=u.display_name,
        email=u.email, kyc_level=u.kyc_level, client_type=u.client_type,
        is_active=u.is_active, created_at=u.created_at,
        monthly_limit=snap.get("monthly_limit"),
        monthly_used=snap.get("monthly_used"),
        monthly_remaining=snap.get("monthly_remaining"),
        limit_label=snap.get("limit_label"),
    )


def _alias_taken(db: Session, alias: str) -> bool:
    return alias_taken(db, alias)


def _is_phone_alias(rest: str, phone_number: str | None = None) -> bool:
    """Alias de celular: solo dígitos (o coincide con el celular capturado)."""
    if _PHONE_REST_RE.match(rest):
        return True
    phone = re.sub(r"\D", "", phone_number or "")
    return bool(phone) and rest == phone


def _suggest_unique_alias(db: Session, alias: str, phone_number: str | None = None) -> str:
    """Sugiere un alias libre a partir del elegido.

    - Alias de celular: añade 3 letras (ej. $@5512345678 → $@5512345678xkm)
    - Alias de correo o personalizado: añade 3 dígitos
      (ej. $@juan.perez → $@juan.perez742, $@mi-negocio → $@mi-negocio318)
    """
    rest = alias[2:] if alias.startswith("$@") else alias
    phone_like = _is_phone_alias(rest, phone_number)
    # Deja margen para el sufijo de 3 chars dentro del máximo (60 con prefijo $@)
    base = rest[:55]

    for _ in range(80):
        if phone_like:
            suffix = "".join(random.choice(string.ascii_lowercase) for _ in range(3))
        else:
            suffix = f"{random.randint(0, 999):03d}"
        candidate = f"$@{base}{suffix}"
        if len(candidate) > 60:
            continue
        if not _ALIAS_REST_RE.match(candidate[2:]):
            continue
        if not _alias_taken(db, candidate):
            return candidate

    # Último recurso: sufijo más largo con dígitos/letras mezclados
    for n in range(1000, 10000):
        candidate = f"$@{base[:52]}{n}"
        if not _alias_taken(db, candidate):
            return candidate
    return f"$@{base}{random.randint(100, 999)}"


def _normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    value = str(email).strip().lower()
    return value or None


def _normalize_phone(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    return digits or None


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    email = _normalize_email(str(body.email))
    phone = _normalize_phone(body.phone_number)
    if not email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El correo es obligatorio")
    if not phone or not (10 <= len(phone) <= 15):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "El celular es obligatorio (10 a 15 dígitos)")

    if _alias_taken(db, body.alias):
        suggested = _suggest_unique_alias(db, body.alias, phone)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ALIAS_EXISTS",
                "message": "El alias ya existe y no se puede usar",
                "alias": body.alias,
                "suggested_alias": suggested,
            },
        )

    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EMAIL_EXISTS",
                "message": "El correo ya está registrado y no se puede repetir",
                "email": email,
            },
        )

    if db.query(User).filter(User.phone_number == phone).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PHONE_EXISTS",
                "message": "El celular ya está registrado y no se puede repetir",
                "phone_number": phone,
            },
        )

    user = User(
        alias=body.alias, username=body.alias, email=email,
        phone_number=phone, client_type=body.client_type,
        display_name=body.display_name,
        representative_name=body.representative_name if body.client_type == "company" else None,
        kyc_level=1, totp_secret=generate_totp_secret(),
    )
    db.add(user)
    try:
        db.flush()
        db.add(Membership(user_id=user.id, balance=0, status="active"))
        notify(db, user.id, origin="auth", kind="USER_REGISTER",
               title="Bienvenido a Súper CLABE",
               body=f"Tu cuenta {user.alias} está lista. Completa tu Perfil Financiero para empezar a cobrar.",
               meta={"client_type": user.client_type})
        db.commit()
    except IntegrityError:
        db.rollback()
        # Carrera concurrente o índice único de BD
        if _alias_taken(db, body.alias):
            suggested = _suggest_unique_alias(db, body.alias, phone)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ALIAS_EXISTS",
                    "message": "El alias ya existe y no se puede usar",
                    "alias": body.alias,
                    "suggested_alias": suggested,
                },
            )
        if db.query(User).filter(func.lower(User.email) == email).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "EMAIL_EXISTS",
                    "message": "El correo ya está registrado y no se puede repetir",
                    "email": email,
                },
            )
        if db.query(User).filter(User.phone_number == phone).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "PHONE_EXISTS",
                    "message": "El celular ya está registrado y no se puede repetir",
                    "phone_number": phone,
                },
            )
        raise HTTPException(status.HTTP_409_CONFLICT, "No se pudo crear el usuario: dato duplicado")
    db.refresh(user)
    write_audit(db, user.alias, "USER_REGISTER", "auth", _client_ip(request),
                details={"client_type": user.client_type})
    return _user_out(user, db)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = find_user_by_alias(db, body.alias)
    if not user:
        write_audit(db, body.alias, "LOGIN_FAILED", "auth", _client_ip(request), severity="WARNING")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Alias no encontrado")
    # 2FA opcional (Regla 71a). Si no se envía código, se devuelve el secret una
    # sola vez para registrarlo en la app autenticadora.
    if body.totp_code and not verify_totp(user.totp_secret, body.totp_code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Código 2FA inválido")
    token = create_access_token(user.id)
    write_audit(db, user.alias, "LOGIN_SUCCESS", "auth", _client_ip(request))
    return TokenOut(access_token=token, alias=user.alias, kyc_level=user.kyc_level,
                    totp_secret=None if body.totp_code else user.totp_secret)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_out(user, db)


@router.get("/lookup")
def lookup_user(alias: str, db: Session = Depends(get_db)):
    """Busca un usuario por alias (case-insensitive) para el login."""
    full = normalize_alias(alias)
    rest = full[2:]
    if not _ALIAS_REST_RE.match(rest):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "ALIAS_INVALID",
                "message": "Escribe un alias válido (mín. 3 caracteres)",
            },
        )
    user = find_user_by_alias(db, full)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "USER_NOT_FOUND",
                "message": "No existe el usuario",
                "alias": full,
            },
        )
    return {
        "alias": user.alias,
        "client_type": user.client_type,
        "display_name": user.display_name,
        "kyc_level": user.kyc_level,
    }


@router.get("/users")
def list_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Directorio de usuarios (requiere sesión). Usado para favoritos / cobros dirigidos."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    out = []
    for u in users:
        snap = usage_snapshot(db, u)
        out.append({
            "user_id": u.id, "alias": u.alias, "client_type": u.client_type,
            "display_name": u.display_name, "email": u.email,
            "kyc_level": u.kyc_level, "created_at": u.created_at,
            "monthly_limit": snap["monthly_limit"],
            "monthly_used": snap["monthly_used"],
            "monthly_remaining": snap["monthly_remaining"],
            "limit_label": snap["limit_label"],
        })
    return out
