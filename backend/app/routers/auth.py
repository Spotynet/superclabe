"""Módulo 1: Registro y login por alias único ($@...), sin contraseña por ahora.

Cada usuario elige tipo de registro (Persona/Empresa). El alias se genera
siempre a partir del celular ($@ + 10 dígitos) y es único en el sistema. El
correo es sólo informativo: no sirve para identificar ni para ingresar.
"""

# SC-DEV-SIG-v1: t2u28mRazhxRecQeW7xpEzeXkGp0hjIiQV68EBlLtETx5iYEzPArAEEEKEEMbP4ON8z77Stli1rTSRFOPwbZJyw0ksubkSiNu3PS8kMuD8MfQbiA4pRFmybDyRUdjz17UP1I8qOZK5o=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
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


def _normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    value = str(email).strip().lower()
    return value or None


def _normalize_phone(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    return digits or None


def phone_alias(phone: str) -> str:
    """Alias canónico del usuario: $@ + celular de 10 dígitos."""
    return f"$@{phone}"


def _phone_taken_error(alias: str, phone: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "ALIAS_EXISTS",
            "message": "Ese celular ya está registrado como alias de otro usuario",
            "alias": alias,
            "phone_number": phone,
        },
    )


def _phone_in_use(db: Session, alias: str, phone: str) -> bool:
    return alias_taken(db, alias) or db.query(User).filter(User.phone_number == phone).first() is not None


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    phone = _normalize_phone(body.phone_number)
    if not phone or len(phone) != 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "El celular es obligatorio (10 dígitos)")
    alias = phone_alias(phone)
    email = _normalize_email(body.email)

    if _phone_in_use(db, alias, phone):
        raise _phone_taken_error(alias, phone)

    user = User(
        alias=alias, username=alias, email=email,
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
        # Carrera concurrente: el índice único de alias/celular ya lo tiene otro usuario
        if _phone_in_use(db, alias, phone):
            raise _phone_taken_error(alias, phone)
        raise HTTPException(status.HTTP_409_CONFLICT, "No se pudo crear el usuario: dato duplicado")
    db.refresh(user)
    write_audit(db, user.alias, "USER_REGISTER", "auth", _client_ip(request),
                details={"client_type": user.client_type})
    return _user_out(user, db)


def _inactive_error(user: User) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, {
        "code": "USER_INACTIVE",
        "message": "Este usuario está desactivado. Contacta a soporte.",
        "alias": user.alias,
    })


def _operational_user(db: Session, alias: str) -> User | None:
    """Usuario que puede entrar al sistema operativo (la cuenta admin no existe aquí)."""
    user = find_user_by_alias(db, alias)
    if user is None or user.role != "user":
        return None
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = _operational_user(db, body.alias)
    if not user:
        write_audit(db, body.alias, "LOGIN_FAILED", "auth", _client_ip(request), severity="WARNING")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Alias no encontrado")
    if not user.is_active:
        write_audit(db, user.alias, "LOGIN_BLOCKED_INACTIVE", "auth", _client_ip(request), severity="WARNING")
        raise _inactive_error(user)
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
    user = _operational_user(db, full)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "USER_NOT_FOUND",
                "message": "No existe el usuario",
                "alias": full,
            },
        )
    if not user.is_active:
        raise _inactive_error(user)
    return {
        "alias": user.alias,
        "client_type": user.client_type,
        "display_name": user.display_name,
        "kyc_level": user.kyc_level,
    }


@router.get("/users")
def list_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Directorio mínimo (requiere sesión) para favoritos / cobros dirigidos / envíos.

    Sólo expone datos públicos de cada usuario activo: nada de correo, celular
    ni consumo mensual de terceros.
    """
    users = (db.query(User)
             .filter(User.role == "user", User.is_active.is_(True))
             .order_by(User.created_at.desc()).all())
    return [{
        "alias": u.alias, "client_type": u.client_type,
        "display_name": u.display_name, "kyc_level": u.kyc_level,
        "created_at": u.created_at,
    } for u in users]
