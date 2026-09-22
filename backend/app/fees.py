"""Cálculo de tarifa de membresía (0.05%) + I.V.A. (16%)."""

# SC-DEV-SIG-v1: WaI6aoicS89FuadVaYfSm3gxxpFWM9kb-GQHpmOavNt_SOqRKTgc9HA4V25fassG5CjEoyWm0CtBAcVEdouDuckicbS4GI6wW3AnbQkC85UZf5PmHz8B0vHFYorJcCFqXXqcoQzhHqY=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
from .config import settings


def money2(value: float) -> float:
    """Redondea montos monetarios a 2 centavos."""
    return round(float(value), 2)


def calc_membership_fee(amount: float) -> dict:
    """Calcula comisión base, IVA y total a debitar de la membresía.

    Returns:
        dict con base_fee, iva, total_fee (todos redondeados a 2 centavos).
    """
    base_fee = money2(float(amount) * settings.MEMBERSHIP_FEE_RATE)
    iva = money2(base_fee * settings.IVA_RATE)
    total_fee = money2(base_fee + iva)
    return {"base_fee": base_fee, "iva": iva, "total_fee": total_fee}
