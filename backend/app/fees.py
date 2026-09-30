"""Cálculo de tarifa de membresía escalonada (modelo v5) + I.V.A. (16%)."""

# SC-DEV-SIG-v1: WaI6aoicS89FuadVaYfSm3gxxpFWM9kb-GQHpmOavNt_SOqRKTgc9HA4V25fassG5CjEoyWm0CtBAcVEdouDuckicbS4GI6wW3AnbQkC85UZf5PmHz8B0vHFYorJcCFqXXqcoQzhHqY=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
from .config import settings


def money2(value: float) -> float:
    """Redondea montos monetarios a 2 centavos."""
    return round(float(value), 2)


def fee_tier(amount: float) -> dict:
    """Devuelve el rango tarifario v5 que corresponde al monto de la operación."""
    amount = money2(amount)
    tier = settings.FEE_TIERS[0]
    for t in settings.FEE_TIERS:
        if amount >= t["min"]:
            tier = t
    return tier


def fee_tiers_public() -> dict:
    """Tabla de tarifas vigente para exponer a clientes (app / landing)."""
    return {
        "model": settings.FEE_MODEL_VERSION,
        "iva_rate": settings.IVA_RATE,
        "tiers": [dict(t) for t in settings.FEE_TIERS],
    }


def calc_membership_fee(amount: float) -> dict:
    """Calcula comisión base, IVA y total a debitar de la membresía.

    La tasa depende del rango del monto (v5): 1.00% / 0.83% / 0.50%.

    Returns:
        dict con base_fee, iva, total_fee (redondeados a 2 centavos),
        fee_rate aplicada y fee_model.
    """
    tier = fee_tier(amount)
    rate = tier["rate"]
    base_fee = money2(float(amount) * rate)
    iva = money2(base_fee * settings.IVA_RATE)
    total_fee = money2(base_fee + iva)
    return {"base_fee": base_fee, "iva": iva, "total_fee": total_fee,
            "fee_rate": rate, "fee_model": settings.FEE_MODEL_VERSION}
