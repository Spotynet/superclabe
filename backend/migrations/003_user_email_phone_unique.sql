-- Unicidad de correo y celular por usuario (llaves de identidad).
-- Uso:  psql "$DATABASE_URL" -f migrations/003_user_email_phone_unique.sql

BEGIN;

-- Normaliza: email minúsculas, teléfono sólo dígitos
UPDATE users
SET email = NULLIF(lower(trim(email)), '')
WHERE email IS NOT NULL;

UPDATE users
SET phone_number = NULLIF(regexp_replace(coalesce(phone_number, ''), '\D', '', 'g'), '')
WHERE phone_number IS NOT NULL;

-- Resuelve duplicados de email (conserva el usuario más antiguo)
WITH ranked AS (
  SELECT id,
         ROW_NUMBER() OVER (PARTITION BY lower(email) ORDER BY created_at ASC, id ASC) AS rn
  FROM users
  WHERE email IS NOT NULL AND email <> ''
)
UPDATE users u
SET email = NULL
FROM ranked r
WHERE u.id = r.id AND r.rn > 1;

-- Resuelve duplicados de teléfono (conserva el usuario más antiguo)
WITH ranked AS (
  SELECT id,
         ROW_NUMBER() OVER (PARTITION BY phone_number ORDER BY created_at ASC, id ASC) AS rn
  FROM users
  WHERE phone_number IS NOT NULL AND phone_number <> ''
)
UPDATE users u
SET phone_number = NULL
FROM ranked r
WHERE u.id = r.id AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email
  ON users (lower(email))
  WHERE email IS NOT NULL AND email <> '';

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_phone_number
  ON users (phone_number)
  WHERE phone_number IS NOT NULL AND phone_number <> '';

COMMIT;
