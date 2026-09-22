"""Esquemas Pydantic (contratos de API)."""

# SC-DEV-SIG-v1: KfEf68nc6fXfQsQcw5qxc_UhI1-8zpYbURke8QN0uazbCykIBEoklht65O6FlPj-Q1prUzIlGZrfLMx4eS-YLn5Mjh47WKpo6rnCxdcDHA6C4JzTPZ86cNzODNKLzFFwOgibFroIK9iK7yA=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ---- Auth / Onboarding (por alias $@, sin contraseña por ahora) ----
class RegisterIn(BaseModel):
    # El alias siempre inicia con $@ (p. ej. $@5512345678 o $@juan.perez)
    alias: str = Field(pattern=r"^\$@[A-Za-z0-9._-]{3,}$", max_length=60)
    client_type: str = Field(pattern="^(company|individual)$")
    # El nombre / razón social se captura después en el módulo Perfil Financiero
    display_name: Optional[str] = Field(default=None, max_length=150)
    representative_name: Optional[str] = Field(default=None, max_length=150)
    # Correo y celular son llaves únicas del usuario (obligatorias al registrar)
    email: EmailStr
    phone_number: str = Field(pattern=r"^\d{10,15}$", min_length=10, max_length=15)


class UserOut(BaseModel):
    user_id: str
    alias: str
    display_name: Optional[str] = None
    email: Optional[EmailStr] = None
    kyc_level: int
    client_type: str
    is_active: bool
    created_at: datetime
    # Uso mensual del Perfil Financiero (límites Regla 72a)
    monthly_limit: Optional[float] = None
    monthly_used: Optional[float] = None
    monthly_remaining: Optional[float] = None
    limit_label: Optional[str] = None


class LoginIn(BaseModel):
    alias: str = Field(pattern=r"^\$@[A-Za-z0-9._-]{3,}$")
    totp_code: Optional[str] = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    alias: str
    totp_secret: Optional[str] = None
    kyc_level: int


# ---- KYC ----
class KycUpgradeIn(BaseModel):
    target_level: int = Field(ge=2, le=4)
    curp: Optional[str] = None
    rfc: Optional[str] = None
    full_name: Optional[str] = None
    business_name: Optional[str] = None
    representative_name: Optional[str] = None
    id_front_path: Optional[str] = None
    id_back_path: Optional[str] = None
    selfie_liveness_path: Optional[str] = None
    csf_pdf_url: Optional[str] = None


# ---- Vault ----
class VaultAccountIn(BaseModel):
    clabe: str = Field(min_length=18, max_length=18)
    account_holder: str
    bank_name: str
    swift_code: Optional[str] = None
    alias: Optional[str] = None


class VaultAccountOut(BaseModel):
    account_id: str
    clabe_masked: str
    account_holder: str
    bank_name: str
    alias: Optional[str]
    is_validated: bool
    created_at: datetime


# ---- Billing / Charges ----
class ChargeIn(BaseModel):
    destination_account_id: str
    # Monto: si open_amount=True, el pagador decide (amount se ignora)
    open_amount: bool = False
    amount: Optional[float] = Field(default=None, gt=0)
    payment_concept: str = Field(max_length=40)
    numeric_reference: int = Field(ge=1, le=9_999_999)
    # Tipo de cobro: OPEN (cualquiera) | TARGETED (dirigido a un usuario del sistema)
    charge_type: str = Field(default="OPEN", pattern="^(OPEN|TARGETED)$")
    target_alias: Optional[str] = Field(default=None, pattern=r"^\$@[A-Za-z0-9._-]{3,}$")
    # Número de pagos/usos permitidos (1 = un solo pago)
    max_uses: int = Field(default=1, ge=1)
    # Frecuencia de programación (sólo aplica con varios pagos)
    frequency: str = Field(default="NONE", pattern="^(NONE|DAILY|WEEKLY|MONTHLY|CUSTOM)$")
    frequency_every_days: Optional[int] = Field(default=None, ge=1, le=365)
    # Incluir etiqueta "Pagar a: <nombre>" al centro de la imagen del QR
    show_payee: bool = False
    # Vigencia: valor + unidad (min | hrs | dias)
    expiration_value: int = Field(default=24, gt=0)
    expiration_unit: str = Field(default="hrs", pattern="^(min|hrs|dias)$")
    requires_pin: bool = False
    pin: Optional[str] = Field(default=None, min_length=4, max_length=4)
    payer_name: Optional[str] = None
    payer_phone: Optional[str] = None


class ChargeOut(BaseModel):
    charge_id: str
    folio_codi: str
    payment_url: str
    qr_payload: str          # Contenido JSON del QR (Mensaje de Cobro CoDi)
    amount: Optional[float]
    open_amount: bool
    charge_type: str
    target_alias: Optional[str] = None
    owner_alias: Optional[str] = None
    payment_concept: Optional[str] = None
    max_uses: int
    uses_count: int
    frequency: str = "NONE"
    frequency_every_days: Optional[int] = None
    last_paid_at: Optional[datetime] = None
    show_payee: bool
    numeric_reference: int
    status: str
    reminders_sent: int
    created_at: datetime


class FavoriteOut(BaseModel):
    alias: str
    display_name: Optional[str] = None
    client_type: str
    kyc_level: int


class ScanIn(BaseModel):
    qr_payload: str          # Contenido leído del QR en el módulo Pagar


# ---- Checkout ----
class CheckoutOut(BaseModel):
    charge_id: str
    folio_codi: str
    masked_beneficiary_name: str
    beneficiary_bank: str
    amount: Optional[float]
    open_amount: bool
    charge_type: str
    target_alias: Optional[str] = None
    owner_alias: Optional[str] = None  # beneficiario (receptor del abono)
    max_uses: int
    uses_count: int
    frequency: str = "NONE"
    frequency_every_days: Optional[int] = None
    last_paid_at: Optional[datetime] = None
    payment_concept: str
    numeric_reference: int
    requires_pin_validation: bool
    status: str
    cep_url: str


class PayIn(BaseModel):
    pin: Optional[str] = None
    payer_totp: Optional[str] = None
    payer_alias: Optional[str] = None      # identidad del pagador (obligatoria en cobros TARGETED)
    pay_amount: Optional[float] = Field(default=None, gt=0)  # monto elegido en cobros de monto libre


class DirectPayIn(BaseModel):
    """Envío de pago directo a un usuario del sistema, sin QR de cobro."""
    recipient_alias: str = Field(pattern=r"^\$@[A-Za-z0-9._-]{3,}$")
    amount: float = Field(gt=0)
    concept: Optional[str] = Field(default=None, max_length=40)


# ---- Membership ----
class RechargeIn(BaseModel):
    amount: float = Field(gt=0)


class DeductIn(BaseModel):
    transaction_amount: float = Field(gt=0)
    charge_id: Optional[str] = None


# ---- Notifications ----
class NotificationOut(BaseModel):
    id: str
    origin: str
    origin_label: str
    kind: str
    title: str
    body: Optional[str] = None
    severity: str
    ref: Optional[str] = None
    meta: Optional[dict] = None
    is_read: bool
    created_at: datetime


class NotificationUnreadOut(BaseModel):
    unread: int
