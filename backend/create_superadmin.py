"""Crea o restablece la cuenta de super administrador del sistema.

La cuenta admin no se puede registrar desde la web: sólo con este script en el
servidor. Genera una contraseña fuerte (o usa SUPERADMIN_PASSWORD) y un secreto
2FA TOTP; ambos se muestran UNA sola vez.

Uso:
    DATABASE_URL=... python create_superadmin.py                     # crea $@superadmin
    DATABASE_URL=... python create_superadmin.py --alias '$@soporte' --name 'Soporte'
    DATABASE_URL=... python create_superadmin.py --reset              # nueva contraseña + nuevo 2FA
"""
import argparse
import os
import secrets
import string
from urllib.parse import quote

from app.database import Base, SessionLocal, engine
import app.models  # noqa: F401
from app.alias_norm import find_user_by_alias, normalize_alias
from app.crypto import hash_password
from app.models import User
from app.security import generate_totp_secret


def _random_password(n: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%*-_"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alias", default="$@superadmin")
    ap.add_argument("--name", default="Super Administrador")
    ap.add_argument("--reset", action="store_true", help="Restablece contraseña y 2FA del admin existente")
    args = ap.parse_args()

    alias = normalize_alias(args.alias)
    if alias[2:].isdigit():
        raise SystemExit("El alias del admin no puede ser un celular (esos alias son de usuarios).")

    Base.metadata.create_all(bind=engine, checkfirst=True)
    password = os.getenv("SUPERADMIN_PASSWORD") or _random_password()
    if len(password) < 12:
        raise SystemExit("La contraseña debe tener al menos 12 caracteres.")
    totp = generate_totp_secret()

    db = SessionLocal()
    try:
        user = find_user_by_alias(db, alias)
        if user and user.role != "superadmin":
            raise SystemExit(f"{alias} ya existe como usuario normal; usa otro alias.")
        if user and not args.reset:
            raise SystemExit(f"{alias} ya existe. Usa --reset para generar nueva contraseña y 2FA.")
        if not user:
            user = User(alias=alias, username=alias, client_type="individual",
                        display_name=args.name, kyc_level=1, role="superadmin", is_active=True)
            db.add(user)
        user.password_hash = hash_password(password)
        user.totp_secret = totp
        user.is_active = True
        db.commit()
    finally:
        db.close()

    uri = f"otpauth://totp/{quote('Súper CLABE Admin')}:{quote(alias)}?secret={totp}&issuer={quote('Súper CLABE')}"
    print(f"✓ Super admin {'restablecido' if args.reset else 'creado'}: {alias}")
    if not os.getenv("SUPERADMIN_PASSWORD"):
        print(f"  Contraseña (se muestra una sola vez): {password}")
    print(f"  Secreto 2FA TOTP: {totp}")
    print(f"  URI para la app autenticadora: {uri}")
    print("  Panel: /admin.html")


if __name__ == "__main__":
    main()
