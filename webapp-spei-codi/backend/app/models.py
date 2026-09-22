"""Modelos SQLAlchemy 2.0 de la plataforma de cobranza SPEI/CoDi.

Alineados con el esquema del análisis: usuarios con KYC gradual (Regla 72a),
metadatos de empresa/persona, bóveda cifrada (Regla 58a), membresías prepago,
transacciones inmutables y bitácoras de auditoría encadenadas.
"""

# SC-DEV-SIG-v1: IcSqsDcCKvlKow4spwhGEE1z8eW8b_2bTfEL8HxdasnotK4U5yp8FDf3_2dTblBWtHF8VkLsFlIJdP8qpMicBspiRdyxUhQINX7eNCYSSSfpsnUM_bEFdJXYnG1P-MDY9dwXmNoj6wi_mw==
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from .database import Base


class GUID(TypeDecorator):
    """UUID portable: usa UUID nativo en PostgreSQL y CHAR(36) en SQLite."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return str(value)


def _uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id = Column(GUID(), primary_key=True, default=_uuid)
    alias = Column(String(60), nullable=False, unique=True)  # identificador $@... único
    username = Column(String(50), nullable=True)             # compatibilidad (= alias)
    email = Column(String(255), nullable=True, unique=True)  # llave única (normalizado a minúsculas)
    password_hash = Column(String(255), nullable=True)       # sin contraseña por ahora
    phone_number = Column(String(15), nullable=True, unique=True)  # llave única (solo dígitos)
    client_type = Column(String(20), nullable=False)   # 'company' | 'individual'
    display_name = Column(String(150), nullable=True)        # nombre / razón social
    representative_name = Column(String(150), nullable=True)  # representante legal (empresa)
    kyc_level = Column(Integer, nullable=False, default=1)  # 1..4 (Regla 72a)
    totp_secret = Column(String(64), nullable=True)     # 2FA (Regla 71a)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    company_metadata = relationship("CompanyMetadata", back_populates="user", uselist=False, cascade="all, delete-orphan")
    individual_metadata = relationship("IndividualMetadata", back_populates="user", uselist=False, cascade="all, delete-orphan")
    vault_accounts = relationship("VaultAccount", back_populates="user", cascade="all, delete-orphan")
    membership = relationship("Membership", back_populates="user", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("alias LIKE '$@%'", name="users_alias_prefix_check"),
        CheckConstraint("client_type IN ('company','individual')", name="users_client_type_check"),
        CheckConstraint("kyc_level BETWEEN 1 AND 4", name="users_kyc_level_check"),
    )


class CompanyMetadata(Base):
    __tablename__ = "companies_metadata"
    id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    rfc_encrypted = Column(Text, nullable=False)          # AES-256
    business_name = Column(String(150), nullable=False)
    representative_name = Column(String(150), nullable=False)
    csf_pdf_url = Column(String(512), nullable=True)      # Constancia Situación Fiscal
    logo_url = Column(String(512), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="company_metadata")


class IndividualMetadata(Base):
    __tablename__ = "individuals_metadata"
    id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    curp_encrypted = Column(Text, nullable=False)         # AES-256
    full_name_encrypted = Column(Text, nullable=False)    # AES-256
    id_front_path = Column(String(512), nullable=True)    # INE frente
    id_back_path = Column(String(512), nullable=True)     # INE reverso
    selfie_liveness_path = Column(String(512), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="individual_metadata")


class VaultAccount(Base):
    """Bóveda bancaria cifrada (Regla 58a)."""
    __tablename__ = "vault_accounts"
    id = Column(GUID(), primary_key=True, default=_uuid)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    clabe_encrypted = Column(Text, nullable=False)        # AES-256
    clabe_masked = Column(String(18), nullable=False)     # **************4567
    clabe_hash = Column(String(64), nullable=False, unique=True)  # lookup SHA-256
    account_holder = Column(String(150), nullable=False)
    bank_name = Column(String(100), nullable=False)
    swift_code = Column(String(11), nullable=True)
    alias = Column(String(100), nullable=True)
    is_validated = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    user = relationship("User", back_populates="vault_accounts")


class Membership(Base):
    """Saldo prepago de membresía para el cobro del 0.05%."""
    __tablename__ = "memberships"
    id = Column(GUID(), primary_key=True, default=_uuid)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    balance = Column(Numeric(12, 2), nullable=False, default=0)
    status = Column(String(20), nullable=False, default="active")  # active|suspended|blocked
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    user = relationship("User", back_populates="membership")
    __table_args__ = (
        CheckConstraint("balance >= 0", name="memberships_balance_positive"),
        CheckConstraint("status IN ('active','suspended','blocked')", name="memberships_status_check"),
    )


class Charge(Base):
    """Solicitud de cobro (Mensaje de Cobro CoDi - Apéndice AD)."""
    __tablename__ = "charges"
    id = Column(GUID(), primary_key=True, default=_uuid)
    user_id = Column(GUID(), ForeignKey("users.id"), nullable=False)   # beneficiario
    destination_account_id = Column(GUID(), ForeignKey("vault_accounts.id"), nullable=False)
    folio_codi = Column(String(100), nullable=False, unique=True)
    slug = Column(String(120), nullable=False)             # superclabe.mx/<slug>/<folio>
    amount = Column(Numeric(12, 2), nullable=True)         # NULL = monto libre (lo decide el pagador)
    open_amount = Column(Boolean, nullable=False, default=False)  # el pagador decide el monto
    payment_concept = Column(String(40), nullable=False)   # máx 40 chars
    numeric_reference = Column(Integer, nullable=False)    # 7 dígitos
    # Tipo de cobro: OPEN (cualquiera lo paga) | TARGETED (dirigido a un usuario)
    charge_type = Column(String(20), nullable=False, default="OPEN")
    target_user_id = Column(GUID(), ForeignKey("users.id"), nullable=True)  # sólo TARGETED
    max_uses = Column(Integer, nullable=False, default=1)   # nº de pagos permitidos (1 = único)
    uses_count = Column(Integer, nullable=False, default=0)  # pagos ya realizados
    # Frecuencia de cobros programados (sólo con max_uses > 1)
    # NONE | DAILY | WEEKLY | MONTHLY | CUSTOM
    frequency = Column(String(20), nullable=False, default="NONE")
    frequency_every_days = Column(Integer, nullable=True)  # intervalo en días (CUSTOM o derivado)
    last_paid_at = Column(DateTime(timezone=True), nullable=True)
    show_payee = Column(Boolean, nullable=False, default=False)  # etiqueta "Pagar a:" en el QR
    expiration_at = Column(DateTime(timezone=True), nullable=False)
    requires_pin = Column(Boolean, default=False)
    pin_hash = Column(String(255), nullable=True)
    payer_name = Column(String(150), nullable=True)
    payer_phone = Column(String(15), nullable=True)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING|PROCESSED|EXPIRED|FAILED
    reminders_sent = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("amount IS NULL OR amount > 0", name="charges_amount_positive"),
        CheckConstraint("max_uses >= 1", name="charges_max_uses_check"),
        CheckConstraint("charge_type IN ('OPEN','TARGETED')", name="charges_type_check"),
        CheckConstraint(
            "frequency IN ('NONE','DAILY','WEEKLY','MONTHLY','CUSTOM')",
            name="charges_frequency_check",
        ),
        CheckConstraint(
            "frequency_every_days IS NULL OR frequency_every_days >= 1",
            name="charges_frequency_days_check",
        ),
        CheckConstraint("status IN ('PENDING','PROCESSED','EXPIRED','FAILED')", name="charges_status_check"),
        Index("idx_charges_folio", "folio_codi"),
    )


class Favorite(Base):
    """Lista de usuarios favoritos de cada usuario (acceso rápido en cobros CoDi)."""
    __tablename__ = "favorites"
    id = Column(GUID(), primary_key=True, default=_uuid)
    owner_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    favorite_user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    __table_args__ = (
        Index("idx_fav_owner", "owner_id"),
        CheckConstraint("owner_id <> favorite_user_id", name="favorites_not_self"),
    )


class Transaction(Base):
    """Registro inmutable de liquidaciones CoDi/SPEI."""
    __tablename__ = "transactions"
    id = Column(GUID(), primary_key=True, default=_uuid)
    charge_id = Column(GUID(), ForeignKey("charges.id"), nullable=True)
    folio_codi = Column(String(100), nullable=False)
    payer_id = Column(GUID(), ForeignKey("users.id"), nullable=True)
    payee_id = Column(GUID(), ForeignKey("users.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    calculated_fee = Column(Numeric(12, 2), nullable=False, default=0)  # 0.05% + I.V.A.
    clave_rastreo = Column(String(100), nullable=True)     # Clave de rastreo SPEI
    status = Column(String(20), nullable=False, default="PENDING")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("idx_tx_folio", "folio_codi"),
    )


class AuditLog(Base):
    """Bitácora inmutable con hash encadenado (Regla 58a)."""
    __tablename__ = "audit_logs"
    id = Column(GUID(), primary_key=True, default=_uuid)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    operator = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    event_category = Column(String(50), nullable=False, default="general")
    client_ip = Column(String(45), nullable=False, default="0.0.0.0")
    severity = Column(String(15), nullable=False, default="INFO")  # INFO|WARNING|CRITICAL
    details = Column(Text, nullable=True)
    integrity_hash = Column(String(64), nullable=False)
    __table_args__ = (
        CheckConstraint("severity IN ('INFO','WARNING','CRITICAL')", name="audit_severity_check"),
        Index("idx_audit_ts", "timestamp"),
    )


class Notification(Base):
    """Alertas por usuario, ligadas al módulo/origen del proceso."""
    __tablename__ = "notifications"
    id = Column(GUID(), primary_key=True, default=_uuid)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Origen del proceso: auth|billing|checkout|membership|kyc|vault
    origin = Column(String(40), nullable=False)
    kind = Column(String(60), nullable=False)          # código del evento
    title = Column(String(160), nullable=False)
    body = Column(Text, nullable=True)
    severity = Column(String(15), nullable=False, default="INFO")  # INFO|WARNING|CRITICAL
    ref = Column(String(120), nullable=True)           # folio / id de referencia
    meta_json = Column(Text, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    __table_args__ = (
        CheckConstraint(
            "origin IN ('auth','billing','checkout','membership','kyc','vault')",
            name="notifications_origin_check",
        ),
        CheckConstraint("severity IN ('INFO','WARNING','CRITICAL')", name="notifications_severity_check"),
        Index("idx_notifications_user_created", "user_id", "created_at"),
        Index("idx_notifications_user_unread", "user_id", "is_read"),
    )
