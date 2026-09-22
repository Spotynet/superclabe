"""Punto de entrada FastAPI de la Webapp SPEI/CoDi (capa no-custodia).

Integra los 6 módulos regulatorios y sirve el frontend estático.
"""

# SC-DEV-SIG-v1: EjDctX14CX9XU6aXqayry-Es4y5gCMzmqlF-gymQ4b5GU-MP3ma4pVapvaF99jn6b1-JC8ow8193xY1h1Le4pPpFJICWr3PGyhbZmmhJkkaGkaj8t6xysStmBzURnFK8z2QSN47qedA=
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, SessionLocal, engine
from .routers import auth, billing, checkout, compliance, kyc, membership, notifications, vault


def _read_app_version() -> str:
    """Lee la versión semántica desde webapp-spei-codi/VERSION."""
    for p in (
        Path(__file__).resolve().parents[2] / "VERSION",
        Path(__file__).resolve().parents[3] / "VERSION",
    ):
        try:
            if p.is_file():
                ver = p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
                if ver:
                    return ver
        except Exception:
            pass
    return os.getenv("APP_VERSION", "0.0.0")


APP_VERSION = _read_app_version()

# Creación de esquema idempotente y a prueba de carreras entre workers de Gunicorn.
# En producción con PostgreSQL el esquema ya lo crea init.sql; aquí sólo se asegura
# en entornos sin él (p. ej. SQLite en desarrollo) sin tumbar workers concurrentes.
try:
    Base.metadata.create_all(bind=engine, checkfirst=True)
except Exception:
    pass


def seed_demo_users():
    """Crea usuarios demo SOLO si SEED_DEMO_USERS=1 (desactivado por defecto).

    El sistema arranca limpio para altas reales de usuarios. Para sembrar demos:
        SEED_DEMO_USERS=1 ...
    """
    if os.getenv("SEED_DEMO_USERS", "").strip() not in ("1", "true", "TRUE", "yes", "YES"):
        return
    from .crypto import encrypt_aes, lookup_hash, mask_clabe, validate_clabe
    from .models import CompanyMetadata, Membership, User, VaultAccount
    from .security import generate_totp_secret
    db = SessionLocal()
    try:
        if db.query(User).first():
            return  # ya hay usuarios; no siembra
        clabe = "012180001234567895"
        if not validate_clabe(clabe):  # respaldo por si cambia el algoritmo
            base = "01218000123456789"; w = [3, 7, 1]
            t = sum((int(base[i]) * w[i % 3]) % 10 for i in range(17))
            clabe = base + str((10 - (t % 10)) % 10)
        demos = [
            {"alias": "$@empresa.demo", "client_type": "company", "kyc_level": 2,
             "display_name": "Comercializadora de México S.A.", "rep": "Ana López",
             "email": "contacto@demo.mx", "balance": 50, "vault": True},
            {"alias": "$@juan.perez", "client_type": "individual", "kyc_level": 2,
             "display_name": "Juan Pérez López", "email": "juan.perez@mail.mx", "balance": 20},
            {"alias": "$@maria.lopez", "client_type": "individual", "kyc_level": 1,
             "display_name": "María López Ruiz", "email": "maria.lopez@mail.mx", "balance": 0},
        ]
        for d in demos:
            u = User(alias=d["alias"], username=d["alias"], email=d["email"],
                     client_type=d["client_type"], display_name=d["display_name"],
                     representative_name=d.get("rep"), kyc_level=d["kyc_level"],
                     totp_secret=generate_totp_secret())
            db.add(u)
            db.flush()
            db.add(Membership(user_id=u.id, balance=d["balance"], status="active"))
            if d["client_type"] == "company":
                db.add(CompanyMetadata(id=u.id, rfc_encrypted=encrypt_aes("ABC010101AB9"),
                                       business_name=d["display_name"], representative_name=d.get("rep") or ""))
            if d.get("vault"):
                db.add(VaultAccount(user_id=u.id, clabe_encrypted=encrypt_aes(clabe),
                                    clabe_masked=mask_clabe(clabe), clabe_hash=lookup_hash(clabe),
                                    account_holder=d["display_name"], bank_name="BBVA",
                                    swift_code="BBVAMXMMXXX", alias="Cuenta principal", is_validated=True))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


try:
    seed_demo_users()
except Exception:
    pass

app = FastAPI(
    title="Webapp SPEI / CoDi — Capa Segura No-Custodia",
    version=APP_VERSION,
    description=(
        "Plataforma de cobranza y enrutamiento de transferencias conforme a la "
        "Circular 14/2017 (SPEI), Circular 12/2019 (CoDi) y Dimo de Banxico. "
        "Modelo PSPI: el dinero viaja cuenta-a-cuenta; sólo se deduce el 0.05% "
        "de membresía. Sin captación de fondos (no IFPE)."
    ),
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

for r in (auth, kyc, vault, billing, checkout, membership, notifications, compliance):
    app.include_router(r.router)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok", "service": "spei-codi-webapp", "version": APP_VERSION}


@app.get("/api/version", tags=["health"])
def version():
    return {"name": "Súper CLABE", "version": APP_VERSION}


# Frontend: landing = index.html ("/"); sistema (login/registro) = app.html
FRONT = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(FRONT):
    @app.get("/app")
    @app.get("/app/")
    def app_entry():
        """Acceso al sistema: login / registro."""
        return RedirectResponse(url="/app.html", status_code=307)

    # "/" sirve index.html (landing); también /app.html, assets/, config.js, etc.
    app.mount("/", StaticFiles(directory=FRONT, html=True), name="frontend")
