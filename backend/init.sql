-- Esquema PostgreSQL de la Webapp SPEI/CoDi (capa no-custodia).
-- Campos sensibles cifrados AES-256 en la app (Regla 58a). Este init.sql
-- crea la estructura; la app también puede autogenerarla con SQLAlchemy.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alias VARCHAR(60) UNIQUE NOT NULL CHECK (alias LIKE '$@%'),  -- identificador $@...
    username VARCHAR(50),                       -- compatibilidad (= alias)
    email VARCHAR(255),
    password_hash VARCHAR(255),                 -- sin contraseña por ahora
    phone_number VARCHAR(15),
    client_type VARCHAR(20) NOT NULL CHECK (client_type IN ('company','individual')),
    display_name VARCHAR(150),                  -- nombre o razón social
    representative_name VARCHAR(150),           -- representante legal (empresa)
    kyc_level INTEGER NOT NULL DEFAULT 1 CHECK (kyc_level BETWEEN 1 AND 4),
    totp_secret VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS companies_metadata (
    id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    rfc_encrypted TEXT NOT NULL,           -- AES-256
    business_name VARCHAR(150) NOT NULL,
    representative_name VARCHAR(150) NOT NULL,
    csf_pdf_url VARCHAR(512),
    logo_url VARCHAR(512),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS individuals_metadata (
    id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    curp_encrypted TEXT NOT NULL,          -- AES-256
    full_name_encrypted TEXT NOT NULL,     -- AES-256
    id_front_path VARCHAR(512),
    id_back_path VARCHAR(512),
    selfie_liveness_path VARCHAR(512),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vault_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    clabe_encrypted TEXT NOT NULL,         -- AES-256
    clabe_masked VARCHAR(18) NOT NULL,
    clabe_hash VARCHAR(64) UNIQUE NOT NULL,
    account_holder VARCHAR(150) NOT NULL,
    bank_name VARCHAR(100) NOT NULL,
    swift_code VARCHAR(11),
    alias VARCHAR(100),
    is_validated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    balance NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','blocked')),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS charges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    destination_account_id UUID NOT NULL REFERENCES vault_accounts(id),
    folio_codi VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(120) NOT NULL,
    amount NUMERIC(12,2) CHECK (amount IS NULL OR amount > 0),  -- NULL = monto libre
    open_amount BOOLEAN NOT NULL DEFAULT FALSE,                  -- el pagador decide el monto
    payment_concept VARCHAR(40) NOT NULL,
    numeric_reference INTEGER NOT NULL,
    charge_type VARCHAR(20) NOT NULL DEFAULT 'OPEN' CHECK (charge_type IN ('OPEN','TARGETED')),
    target_user_id UUID REFERENCES users(id),                   -- sólo cobros TARGETED
    max_uses INTEGER NOT NULL DEFAULT 1 CHECK (max_uses >= 1),  -- nº de pagos permitidos
    uses_count INTEGER NOT NULL DEFAULT 0,
    show_payee BOOLEAN NOT NULL DEFAULT FALSE,                  -- etiqueta "Pagar a:" en el QR
    expiration_at TIMESTAMPTZ NOT NULL,
    requires_pin BOOLEAN DEFAULT FALSE,
    pin_hash VARCHAR(255),
    payer_name VARCHAR(150),
    payer_phone VARCHAR(15),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PROCESSED','EXPIRED','FAILED')),
    reminders_sent INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_charges_folio ON charges(folio_codi);

-- Lista de favoritos por usuario (acceso rápido al crear cobros CoDi)
CREATE TABLE IF NOT EXISTS favorites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    favorite_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT favorites_not_self CHECK (owner_id <> favorite_user_id),
    UNIQUE (owner_id, favorite_user_id)
);
CREATE INDEX IF NOT EXISTS idx_fav_owner ON favorites(owner_id);

CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    charge_id UUID REFERENCES charges(id),
    folio_codi VARCHAR(100) NOT NULL,
    payer_id UUID REFERENCES users(id),
    payee_id UUID NOT NULL REFERENCES users(id),
    amount NUMERIC(12,2) NOT NULL,
    calculated_fee NUMERIC(12,2) NOT NULL DEFAULT 0,   -- 0.05% + I.V.A.
    clave_rastreo VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ DEFAULT now(),
    settled_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tx_folio ON transactions(folio_codi);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    operator VARCHAR(100) NOT NULL,
    action VARCHAR(100) NOT NULL,
    event_category VARCHAR(50) NOT NULL DEFAULT 'general',
    client_ip VARCHAR(45) NOT NULL DEFAULT '0.0.0.0',
    severity VARCHAR(15) NOT NULL DEFAULT 'INFO' CHECK (severity IN ('INFO','WARNING','CRITICAL')),
    details TEXT,
    integrity_hash VARCHAR(64) NOT NULL   -- SHA-256 encadenado (inmutabilidad)
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(timestamp);
