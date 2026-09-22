"""Autenticación: JWT de sesión, 2FA TOTP y dependencia de usuario actual."""

# SC-DEV-SIG-v1: ZHR6XtmBabITYagK-rGe50FLjezQnBnow7RfJMmKF66hegPV8JmXUS9SNLXZvM5A_ppWP1Ejqn9pD6JgM6fzz1jHvRPR_cccZGMV8UFluFFABJOIdeEY8JZbpyzbNBgFUqqL5m0BOOR0mZw2
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import base64
import hashlib
import hmac
import struct
import time
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MIN)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    cred_err = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas o sesión expirada",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise cred_err
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
        uid = payload.get("sub")
    except JWTError:
        raise cred_err
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise cred_err
    return user


# ---- TOTP (RFC 6238) minimal para 2FA sin dependencias extra ----
def generate_totp_secret() -> str:
    import os
    return base64.b32encode(os.urandom(10)).decode("ascii").replace("=", "")


def totp_now(secret: str, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    counter = int(time.time() // step)
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return hmac.compare_digest(totp_now(secret), str(code).zfill(6))
