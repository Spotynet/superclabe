-- Frecuencia de cobros programados (varios pagos dentro de la vigencia)
ALTER TABLE charges ADD COLUMN IF NOT EXISTS frequency VARCHAR(20) NOT NULL DEFAULT 'NONE';
ALTER TABLE charges ADD COLUMN IF NOT EXISTS frequency_every_days INTEGER;
ALTER TABLE charges ADD COLUMN IF NOT EXISTS last_paid_at TIMESTAMPTZ;

DO $$ BEGIN
  ALTER TABLE charges ADD CONSTRAINT charges_frequency_check
    CHECK (frequency IN ('NONE','DAILY','WEEKLY','MONTHLY','CUSTOM'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE charges ADD CONSTRAINT charges_frequency_days_check
    CHECK (frequency_every_days IS NULL OR frequency_every_days >= 1);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
