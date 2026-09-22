"""Límites por Perfil Financiero — alineados a Circular 14/2017 (Regla 72a)
y a los niveles de cuenta del art. 115 LIC (referencia SPEI / CoDi).

Criterio normativo de montos:
  El tope mensual aplica a la SUMA DE ABONOS (créditos recibidos) a la cuenta
  del cliente en el mes calendario — no a los cargos/envíos.

Niveles (aproximación en MXN usada por la plataforma):
  1: solo registro (sin operar SPEI/CoDi en la capa PSPI)
  2: abonos hasta $25,000 MXN/mes (~3,000 UDIS)
  3: abonos hasta $68,000 MXN/mes (~8,000 UDIS)
  4: sin límite mensual de abonos

Modelo PSPI · sin captación: la plataforma no custodia fondos; el control
refleja el perfil del cliente receptor de la transferencia.
"""

# SC-DEV-SIG-v1: lxBkCNM1HB5yOLXTep108CPNy_bEsBBsfJdmA1uXRtmWAhxSaQJUY2tW9tppQ78pklGO9VaH2J0SUT50-WzoJ2SfZ8h-Kw8MgLVVgmq4QpeVcnQyFuB20osobBxLDCG1EMsBdJO7ZgmZ1YBCzbo=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import Transaction, User

# Tope mensual de ABONOS por nivel (None = ilimitado)
KYC_MONTHLY_LIMITS: dict[int, Optional[float]] = {
    1: 0.0,
    2: 25_000.0,
    3: 68_000.0,
    4: None,
}

KYC_LIMIT_LABELS = {
    1: "Solo registro (sin operaciones)",
    2: "abonos hasta $25,000 MXN/mes",
    3: "abonos hasta $68,000 MXN/mes",
    4: "Sin límite mensual de abonos",
}

MIN_OPERATING_LEVEL = 2


def monthly_limit_for(level: int) -> Optional[float]:
    return KYC_MONTHLY_LIMITS.get(int(level or 1), 0.0)


def month_start_utc(now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def monthly_volume(db: Session, user_id) -> float:
    """Suma de ABONOS del mes (usuario como beneficiario / payee).

    Conforme a niveles de cuenta: el límite es sobre créditos recibidos,
    no sobre envíos.
    """
    start = month_start_utc()
    total = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            Transaction.status == "PROCESSED",
            Transaction.settled_at >= start,
            Transaction.payee_id == user_id,
        )
        .scalar()
    )
    return round(float(total or 0), 2)


def usage_snapshot(db: Session, user: User) -> dict:
    level = int(user.kyc_level or 1)
    limit = monthly_limit_for(level)
    used = monthly_volume(db, user.id)
    if limit is None:
        remaining = None
    else:
        remaining = round(max(0.0, float(limit) - used), 2)
    return {
        "kyc_level": level,
        "monthly_limit": limit,
        "monthly_used": used,
        "monthly_remaining": remaining,
        "limit_label": KYC_LIMIT_LABELS.get(level, ""),
        "user_alias": user.alias,
    }


def _detail(user: User, snap: dict, code: str, message: str, *,
            amount: float | None = None, role: str = "", as_self: bool = True) -> dict:
    out = {
        "code": code,
        "message": message,
        **snap,
        "role": role,
        "as_self": as_self,
        "limited_user_alias": user.alias,
    }
    if amount is not None:
        out["attempted_amount"] = amount
    return out


def assert_min_kyc_level(
    user: User,
    *,
    role: str = "operar",
    as_self: bool = True,
    min_level: int = MIN_OPERATING_LEVEL,
) -> None:
    """Exige nivel mínimo para usar SPEI/CoDi en la plataforma (sin tope de monto)."""
    level = int(user.kyc_level or 1)
    alias = user.alias
    if level >= min_level:
        return
    if as_self:
        msg = (
            f"Tu usuario ({alias}) tiene Perfil Financiero Nivel {level}. "
            f"Debes completar al menos el Nivel {min_level} para {role}."
        )
    else:
        msg = (
            f"El usuario {alias} tiene Perfil Financiero Nivel {level} y no puede {role}. "
            f"Debe completar al menos el Nivel {min_level}."
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "KYC_LEVEL_BLOCKED",
            "message": msg,
            "kyc_level": level,
            "role": role,
            "as_self": as_self,
            "limited_user_alias": alias,
        },
    )


def assert_abono_within_kyc(
    db: Session,
    user: User,
    amount: float,
    *,
    role: str = "recibir este abono",
    as_self: bool = True,
) -> dict:
    """Valida que el ABONO quepa en el tope mensual del receptor (Regla 72a / art. 115).

    Solo debe invocarse sobre el beneficiario (quien recibe el dinero).
    """
    amount = round(float(amount or 0), 2)
    if amount <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Monto inválido")

    snap = usage_snapshot(db, user)
    level = snap["kyc_level"]
    limit = snap["monthly_limit"]
    remaining = snap["monthly_remaining"]
    alias = user.alias

    if level < MIN_OPERATING_LEVEL or limit == 0:
        if as_self:
            msg = (
                f"Tu usuario ({alias}) tiene Perfil Financiero Nivel {level}. "
                f"Debes completar al menos el Nivel {MIN_OPERATING_LEVEL} para {role}."
            )
        else:
            msg = (
                f"El usuario {alias} tiene Perfil Financiero Nivel {level} y no puede {role}. "
                f"Debe completar al menos el Nivel {MIN_OPERATING_LEVEL}."
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_detail(user, snap, "KYC_LEVEL_BLOCKED", msg,
                           amount=amount, role=role, as_self=as_self),
        )

    if limit is None:
        return snap  # Nivel 4 ilimitado

    if amount > limit or (remaining is not None and amount > remaining):
        if as_self:
            msg = (
                f"Tu usuario ({alias}) ya supera el monto de abonos permitido por su "
                f"Perfil Financiero Nivel {level}."
            )
        else:
            msg = (
                f"El usuario {alias} ya supera el monto de abonos permitido por su "
                f"Perfil Financiero Nivel {level}."
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_detail(user, snap, "KYC_LIMIT_EXCEEDED", msg,
                           amount=amount, role=role, as_self=as_self),
        )

    return snap


# Compatibilidad con imports previos
def assert_amount_within_kyc(
    db: Session,
    user: User,
    amount: float,
    *,
    role: str = "recibir este abono",
    as_self: bool = True,
) -> dict:
    """Alias de assert_abono_within_kyc (tope solo para el receptor)."""
    return assert_abono_within_kyc(db, user, amount, role=role, as_self=as_self)
