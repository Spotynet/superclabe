-- Rol de usuario: 'user' (opera sus propios cobros/pagos) | 'superadmin' (sólo administra).
-- Uso:  psql "$DATABASE_URL" -f migrations/005_user_roles.sql

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'user';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_role_check') THEN
    ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('user','superadmin'));
  END IF;
END $$;

COMMIT;
