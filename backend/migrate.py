"""Migrador idempotente de esquema (dev SQLite y prod PostgreSQL).

Aplica los cambios de las funciones de QR de cobro CoDi sobre una base de datos
existente sin destruir datos:

  * charges: open_amount, charge_type, target_user_id, max_uses, uses_count,
    show_payee (+ amount pasa a admitir NULL para cobros de monto libre).
  * favorites: tabla nueva de favoritos por usuario.

Detecta las columnas ya presentes y sólo agrega lo que falta, por lo que es
seguro re-ejecutarlo. En PostgreSQL se recomienda además el SQL declarativo de
`migrations/001_codi_qr_features.sql` (incluye FK y CHECK constraints con nombre).

Uso:
    python migrate.py            # aplica la migración
    python migrate.py --check    # sólo reporta lo que falta (no modifica)
"""
import sys

from sqlalchemy import inspect, text

from app.database import Base, engine
import app.models  # noqa: F401  (registra los modelos en Base.metadata)
from app.models import Favorite

# Columnas nuevas de `charges` con su tipo por dialecto.
# (nombre, tipo_postgresql, tipo_sqlite)
CHARGE_COLUMNS = [
    ("open_amount",    "BOOLEAN NOT NULL DEFAULT FALSE",   "BOOLEAN NOT NULL DEFAULT 0"),
    ("charge_type",    "VARCHAR(20) NOT NULL DEFAULT 'OPEN'", "VARCHAR(20) NOT NULL DEFAULT 'OPEN'"),
    ("target_user_id", "UUID",                             "CHAR(36)"),
    ("max_uses",       "INTEGER NOT NULL DEFAULT 1",       "INTEGER NOT NULL DEFAULT 1"),
    ("uses_count",     "INTEGER NOT NULL DEFAULT 0",       "INTEGER NOT NULL DEFAULT 0"),
    ("show_payee",     "BOOLEAN NOT NULL DEFAULT FALSE",   "BOOLEAN NOT NULL DEFAULT 0"),
    ("frequency",      "VARCHAR(20) NOT NULL DEFAULT 'NONE'", "VARCHAR(20) NOT NULL DEFAULT 'NONE'"),
    ("frequency_every_days", "INTEGER",                    "INTEGER"),
    ("last_paid_at",   "TIMESTAMPTZ",                      "DATETIME"),
]


def _existing_columns(insp, table):
    if table not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns(table)}


def plan():
    """Devuelve la lista de acciones pendientes (para --check y para aplicar)."""
    insp = inspect(engine)
    dialect = engine.dialect.name
    actions = []

    charge_cols = _existing_columns(insp, "charges")
    if charge_cols is None:
        actions.append(("note", "La tabla 'charges' no existe todavía; "
                                 "usa Base.metadata.create_all (arranque normal de la app)."))
    else:
        for name, pg_type, sqlite_type in CHARGE_COLUMNS:
            if name not in charge_cols:
                col_type = pg_type if dialect != "sqlite" else sqlite_type
                actions.append(("sql", f'ALTER TABLE charges ADD COLUMN {name} {col_type}'))
        # amount -> admite NULL (sólo PostgreSQL; SQLite no lo soporta vía ALTER,
        # pero su default dev se recrea con create_all).
        if dialect == "postgresql":
            actions.append(("sql", "ALTER TABLE charges ALTER COLUMN amount DROP NOT NULL"))

    if "favorites" not in insp.get_table_names():
        actions.append(("create_favorites", None))

    # Unicidad de email / celular (llaves de usuario)
    if "users" in insp.get_table_names():
        idx_names = {i["name"] for i in insp.get_indexes("users")}
        if dialect == "postgresql":
            if "ux_users_email" not in idx_names:
                actions.append(("sql",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email "
                    "ON users (lower(email)) WHERE email IS NOT NULL AND email <> ''"))
            if "ux_users_phone_number" not in idx_names:
                actions.append(("sql",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_phone_number "
                    "ON users (phone_number) WHERE phone_number IS NOT NULL AND phone_number <> ''"))
        else:
            # SQLite: índices únicos simples (NULL permitido varias veces)
            if "ux_users_email" not in idx_names:
                actions.append(("sql",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email ON users (email)"))
            if "ux_users_phone_number" not in idx_names:
                actions.append(("sql",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_phone_number ON users (phone_number)"))

    return actions, dialect


def main():
    check_only = "--check" in sys.argv
    actions, dialect = plan()

    pending = [a for a in actions if a[0] != "note"]
    notes = [a for a in actions if a[0] == "note"]
    for _, msg in notes:
        print(f"ℹ  {msg}")

    if not pending:
        print(f"✓ Sin cambios pendientes (dialecto: {dialect}). El esquema ya está al día.")
        return

    print(f"→ {len(pending)} acción(es) pendiente(s) en dialecto '{dialect}':")
    for kind, payload in pending:
        print(f"   • {'CREATE TABLE favorites' if kind == 'create_favorites' else payload}")

    if check_only:
        print("\n(--check) No se aplicó ningún cambio.")
        return

    with engine.begin() as conn:
        for kind, payload in pending:
            if kind == "sql":
                conn.execute(text(payload))
            elif kind == "create_favorites":
                Favorite.__table__.create(bind=conn, checkfirst=True)
    print("\n✓ Migración aplicada correctamente.")


if __name__ == "__main__":
    main()
