"""Utilidades criptográficas (Regla 58a).

- Cifrado simétrico AES-256 (CBC) de datos sensibles en reposo: CLABE, RFC,
  nombre, teléfono, Constancias.
- Enmascaramiento de CLABE (Regla 71a): se muestra sólo parcialmente.
- Hash SHA-256 encadenado para bitácoras inmutables (AuditLog).
- Hashing de contraseñas con PBKDF2.
"""

# SC-DEV-SIG-v1: mF0JL_GqboGNDEU5pUsB1HnDQjKWRswLrp6ifNV0Zqm3SNjdDdH__tFOfpypvQew9igVZ78goyQJfzAk-oIZPA26RE2ItAw3JFqnECCx8TdUth1njtjrZ0Syl0nnLAOyQT5C6rk7NvqnmQ==
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import base64
import hashlib
import hmac
import os

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .config import settings


def _key() -> bytes:
    raw = settings.AES_SECRET_KEY
    # Aceptar hex de 64 chars -> 32 bytes; si no, derivar 32 bytes.
    try:
        if len(raw) == 64:
            return bytes.fromhex(raw)
    except ValueError:
        pass
    return hashlib.sha256(raw.encode()).digest()


def encrypt_aes(plaintext: str) -> str:
    """Cifra texto y devuelve base64(iv + ciphertext)."""
    if plaintext is None:
        return None
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    data = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(_key()), modes.CBC(iv), backend=default_backend())
    enc = cipher.encryptor()
    ct = enc.update(data) + enc.finalize()
    return base64.b64encode(iv + ct).decode("ascii")


def decrypt_aes(token: str) -> str:
    """Descifra base64(iv + ciphertext) al texto original."""
    if token is None:
        return None
    blob = base64.b64decode(token)
    iv, ct = blob[:16], blob[16:]
    cipher = Cipher(algorithms.AES(_key()), modes.CBC(iv), backend=default_backend())
    dec = cipher.decryptor()
    data = dec.update(ct) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(data) + unpadder.finalize()).decode("utf-8")


def mask_clabe(clabe: str) -> str:
    """Enmascara la CLABE dejando visibles sólo los últimos 4 dígitos."""
    clabe = clabe.strip()
    if len(clabe) < 4:
        return "*" * len(clabe)
    return "*" * (len(clabe) - 4) + clabe[-4:]


def lookup_hash(value: str) -> str:
    """Hash determinista para detectar duplicados sin descifrar (SHA-256)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def chained_hash(prev_hash: str, payload: str) -> str:
    """Hash encadenado para inmutabilidad de bitácoras."""
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return base64.b64encode(salt + dk).decode("ascii")


def verify_password(password: str, stored: str) -> bool:
    try:
        blob = base64.b64decode(stored)
        salt, dk = blob[:16], blob[16:]
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
        return hmac.compare_digest(dk, test)
    except Exception:
        return False


def validate_clabe(clabe: str) -> bool:
    """Valida CLABE de 18 dígitos con el dígito verificador (módulo 10).

    Sección 6 del Manual del SPEI. Pesos 3,7,1 repetidos sobre los 17
    primeros dígitos; el dígito 18 es el control.
    """
    if not clabe or len(clabe) != 18 or not clabe.isdigit():
        return False
    weights = [3, 7, 1] * 6
    total = 0
    for i in range(17):
        total += (int(clabe[i]) * weights[i]) % 10
    control = (10 - (total % 10)) % 10
    return control == int(clabe[17])
