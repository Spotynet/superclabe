-- El correo pasa a ser sólo informativo: deja de ser único y de identificar al usuario.
-- El alias ($@ + celular) y el celular siguen siendo únicos.
-- Uso:  psql "$DATABASE_URL" -f migrations/004_email_informative.sql

BEGIN;

DROP INDEX IF EXISTS ux_users_email;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;

COMMIT;
