#!/usr/bin/env python3
"""Verifica la firma de autoría oculta (SC-DEV-SIG-v1) en los módulos de Súper CLABE.

Uso:
  export SC_DEV_SIG_PASS='<tu contraseña externa>'
  python tools/verify_dev_signature.py

  # o:
  python tools/verify_dev_signature.py --passphrase '...'

Requiere: cryptography
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "dev-signatures.registry.json"
MARKER = "SC-DEV-SIG-v1"
AAD = b"superclabe-dev-sig-v1"


def decrypt(blob: str, passphrase: str) -> str:
    key = hashlib.sha256(passphrase.encode("utf-8")).digest()
    raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, AAD).decode("utf-8")


def extract_from_file(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    # python / js / html comments
    patterns = [
        rf"#\s*{re.escape(MARKER)}:\s*(\S+)",
        rf"/\*\s*{re.escape(MARKER)}:\s*(\S+)\s*\*/",
        rf"<!--\s*{re.escape(MARKER)}:\s*(\S+)\s*-->",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Verificar firmas de autoría cifradas")
    ap.add_argument("--passphrase", default=os.getenv("SC_DEV_SIG_PASS", ""), help="Contraseña externa")
    ap.add_argument("--registry", default=str(REGISTRY))
    args = ap.parse_args()
    if not args.passphrase:
        print("ERROR: indica --passphrase o SC_DEV_SIG_PASS", file=sys.stderr)
        return 2

    reg = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    ok = fail = miss = 0
    print(f"Verificando firmas ({MARKER})…\n")
    for mod, info in reg["modules"].items():
        path = ROOT / info["file"]
        expected = info["sig"]
        found = extract_from_file(path) if path.exists() else None
        if not path.exists():
            print(f"[MISS] {mod}: archivo no existe ({info['file']})")
            miss += 1
            continue
        if not found:
            print(f"[MISS] {mod}: sin marcador en {info['file']}")
            miss += 1
            continue
        if found != expected:
            print(f"[WARN] {mod}: firma en archivo difiere del registry")
        try:
            plain = decrypt(found, args.passphrase)
            print(f"[OK]   {mod}: {plain}")
            ok += 1
        except Exception as e:
            print(f"[FAIL] {mod}: no descifra ({e.__class__.__name__})")
            fail += 1

    print(f"\nResumen: ok={ok} fail={fail} miss={miss}")
    if ok and not fail and not miss:
        print("Autoría verificada: Desarrollado por Christian David Torres Parra")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
