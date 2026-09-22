"""Conexión y sesión de SQLAlchemy 2.0."""

# SC-DEV-SIG-v1: H-ofSKW61FtMb3vu7YlLejBGwLYPkVhKRbWOOWCD-hiSocYQHoRCsTXTrUVEdUlYkPZfw52y65g1fZKf6EGCjHZQZnW9cDR5ahNX3L54WN_OJP5bqRX8TYCcZ2783jE56ngUMZr0AT62Rr3r
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
