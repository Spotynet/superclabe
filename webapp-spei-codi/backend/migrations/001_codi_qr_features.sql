-- ============================================================================
-- Migración 001 · Funciones de QR de cobro CoDi (PostgreSQL)
-- ----------------------------------------------------------------------------
-- Agrega a `charges` los campos de: monto libre, tipo de cobro (libre/
-- personalizado), usuario destino, número de usos, y etiqueta "Pagar a:".
-- Crea la tabla `favorites` (favoritos por usuario).
--
-- Idempotente: usa IF NOT EXISTS. Seguro de re-ejecutar.
-- Uso:  psql "$DATABASE_URL" -f migrations/001_codi_qr_features.sql
--   o:  docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
--            < backend/migrations/001_codi_qr_features.sql
-- ============================================================================

BEGIN;

-- 1) Nuevas columnas en charges ------------------------------------------------
ALTER TABLE charges ADD COLUMN IF NOT EXISTS open_amount    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE charges ADD COLUMN IF NOT EXISTS charge_type    VARCHAR(20) NOT NULL DEFAULT 'OPEN';
ALTER TABLE charges ADD COLUMN IF NOT EXISTS target_user_id UUID;
ALTER TABLE charges ADD COLUMN IF NOT EXISTS max_uses       INTEGER NOT NULL DEFAULT 1;
ALTER TABLE charges ADD COLUMN IF NOT EXISTS uses_count     INTEGER NOT NULL DEFAULT 0;
ALTER TABLE charges ADD COLUMN IF NOT EXISTS show_payee     BOOLEAN NOT NULL DEFAULT FALSE;

-- 2) El monto ahora puede ser NULL (cobros de monto libre) ---------------------
ALTER TABLE charges ALTER COLUMN amount DROP NOT NULL;

-- 3) FK del usuario destino (sólo si aún no existe) ----------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'charges_target_user_fk'
    ) THEN
        ALTER TABLE charges
            ADD CONSTRAINT charges_target_user_fk
            FOREIGN KEY (target_user_id) REFERENCES users(id);
    END IF;
END$$;

-- 4) CHECK constraints (sólo si aún no existen) --------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'charges_type_check') THEN
        ALTER TABLE charges ADD CONSTRAINT charges_type_check
            CHECK (charge_type IN ('OPEN','TARGETED'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'charges_max_uses_check') THEN
        ALTER TABLE charges ADD CONSTRAINT charges_max_uses_check
            CHECK (max_uses >= 1);
    END IF;
END$$;

-- La restricción vieja "amount > 0" (NOT NULL implícito) se relaja para permitir
-- NULL en cobros de monto libre; se recrea admitiendo NULL.
ALTER TABLE charges DROP CONSTRAINT IF EXISTS charges_amount_positive;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'charges_amount_positive') THEN
        ALTER TABLE charges ADD CONSTRAINT charges_amount_positive
            CHECK (amount IS NULL OR amount > 0);
    END IF;
END$$;

-- 5) Tabla de favoritos --------------------------------------------------------
CREATE TABLE IF NOT EXISTS favorites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    favorite_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT favorites_not_self CHECK (owner_id <> favorite_user_id),
    UNIQUE (owner_id, favorite_user_id)
);
CREATE INDEX IF NOT EXISTS idx_fav_owner ON favorites(owner_id);

COMMIT;
