"""Módulo 2: Bóveda bancaria cifrada AES-256 (Regla 58a)."""

# SC-DEV-SIG-v1: FJAH0zZNhCjTSJEYTOQg7JPaOKRImSsiwcNJwW5cgmH3dpZ02qRIHNLnyqLJpsdERbNFESapJWNo14DOiNW2VNDABInzJ7uzFqjJH3PH5SN538DAfhG12J2pwNSXtyT_Ujgkwgwf6a2j
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..notify import notify
from ..crypto import encrypt_aes, lookup_hash, mask_clabe, validate_clabe
from ..database import get_db
from ..models import User, VaultAccount
from ..schemas import VaultAccountIn, VaultAccountOut
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/vault", tags=["2. Bóveda (Regla 58a)"])


def _to_out(a: VaultAccount) -> VaultAccountOut:
    return VaultAccountOut(account_id=a.id, clabe_masked=a.clabe_masked,
                           account_holder=a.account_holder, bank_name=a.bank_name,
                           alias=a.alias, is_validated=a.is_validated, created_at=a.created_at)


@router.post("/accounts", response_model=VaultAccountOut)
def add_account(body: VaultAccountIn, request: Request,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    clabe = body.clabe.strip()
    if not validate_clabe(clabe):
        raise HTTPException(422, "CLABE inválida: debe tener 18 dígitos y dígito de control correcto (módulo 10)")
    h = lookup_hash(clabe)
    if db.query(VaultAccount).filter(VaultAccount.clabe_hash == h).first():
        raise HTTPException(409, "Esta CLABE ya está registrada en la bóveda")
    acc = VaultAccount(
        user_id=user.id, clabe_encrypted=encrypt_aes(clabe), clabe_masked=mask_clabe(clabe),
        clabe_hash=h, account_holder=body.account_holder, bank_name=body.bank_name,
        swift_code=body.swift_code, alias=body.alias, is_validated=True,
    )
    db.add(acc)
    notify(db, user.id, origin="vault", kind="VAULT_ACCOUNT_ADDED",
           title="Cuenta agregada a la bóveda",
           body=f"{body.bank_name} · {mask_clabe(clabe)}"
                + (f" · {body.alias}" if body.alias else ""),
           meta={"bank": body.bank_name})
    db.commit()
    db.refresh(acc)
    write_audit(db, user.alias, "VAULT_CLABE_REGISTER_SUCCESS", "vault_access",
                request.client.host if request.client else "0.0.0.0")
    return _to_out(acc)


@router.get("/accounts", response_model=list[VaultAccountOut])
def list_accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    accs = db.query(VaultAccount).filter(VaultAccount.user_id == user.id).all()
    return [_to_out(a) for a in accs]
