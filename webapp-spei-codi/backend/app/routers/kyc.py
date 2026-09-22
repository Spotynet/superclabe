"""Módulo 1 (cont.): KYC gradual - Regla 72a. Elevación de nivel por documentos."""

# SC-DEV-SIG-v1: WboTbzJE0cNPg4haaTu1wmTVzQUln3wsdQPQ3id_flt-kuNdYOk6VIJOPkyyxwCgJ8-0aj6y3gl87gS-V_HI4pI3F33NvfJlKH44OXfurF7Os8iRWf6q9UgpDGBZN7edVQZbWLY8_Q==
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..notify import notify
from ..config import settings
from ..crypto import encrypt_aes
from ..database import get_db
from ..models import CompanyMetadata, IndividualMetadata, User
from ..schemas import KycUpgradeIn
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/kyc", tags=["1. Perfil Financiero (Regla 72a)"])

# Requisito mínimo de identidad al subir a Nivel 2 (según tipo de cliente).
# Los documentos (INE/pasaporte/residencia, selfie de vida) se capturan en el
# cliente; los niveles superiores no vuelven a exigir el dato base de identidad.
def _required(client_type: str, level: int):
    if level == 2:
        return ["curp"] if client_type == "individual" else ["rfc"]
    return []


@router.get("/limits")
def kyc_limits():
    """Límites mensuales en UDIS por nivel (Regla 72a)."""
    return {"limits_udis": settings.KYC_LIMITS_UDIS}


@router.post("/upgrade")
def upgrade(body: KycUpgradeIn, request: Request,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.target_level <= user.kyc_level:
        raise HTTPException(400, "El nivel objetivo debe ser mayor al actual")
    missing = [f for f in _required(user.client_type, body.target_level) if not getattr(body, f, None)]
    if missing:
        raise HTTPException(422, f"Faltan campos obligatorios para Nivel {body.target_level}: {missing}")

    if user.client_type == "individual":
        meta = db.query(IndividualMetadata).filter(IndividualMetadata.id == user.id).first()
        if not meta:
            meta = IndividualMetadata(id=user.id, curp_encrypted=encrypt_aes(body.curp or ""),
                                      full_name_encrypted=encrypt_aes(body.full_name or ""))
            db.add(meta)
        else:
            if body.curp:
                meta.curp_encrypted = encrypt_aes(body.curp)
            if body.full_name:
                meta.full_name_encrypted = encrypt_aes(body.full_name)
        meta.id_front_path = body.id_front_path or meta.id_front_path
        meta.id_back_path = body.id_back_path or meta.id_back_path
        meta.selfie_liveness_path = body.selfie_liveness_path or meta.selfie_liveness_path
    else:  # company
        meta = db.query(CompanyMetadata).filter(CompanyMetadata.id == user.id).first()
        if not meta:
            meta = CompanyMetadata(id=user.id, rfc_encrypted=encrypt_aes(body.rfc or ""),
                                   business_name=body.business_name or "",
                                   representative_name=body.representative_name or "")
            db.add(meta)
        else:
            if body.rfc:
                meta.rfc_encrypted = encrypt_aes(body.rfc)
        meta.csf_pdf_url = body.csf_pdf_url or meta.csf_pdf_url

    # Refleja el nombre / razón social capturado en el perfil visible del usuario
    if user.client_type == "individual" and body.full_name:
        user.display_name = body.full_name
    if user.client_type == "company":
        if body.business_name:
            user.display_name = body.business_name
        if body.representative_name:
            user.representative_name = body.representative_name

    user.kyc_level = body.target_level
    notify(db, user.id, origin="kyc", kind="KYC_UPGRADE",
           title="Perfil Financiero actualizado",
           body=f"Tu Perfil Financiero pasó a Nivel {body.target_level}.",
           meta={"level": body.target_level})
    db.commit()
    write_audit(db, user.alias, "KYC_VERIFICATION_UPGRADE", "kyc_change",
                request.client.host if request.client else "0.0.0.0",
                details={"new_level": body.target_level})
    return {
        "user_id": user.id,
        "kyc_level": user.kyc_level,
        "monthly_limit_udis": settings.KYC_LIMITS_UDIS[user.kyc_level],
        "kyc_status": "PENDING_VALIDATION",
        "message": "Documentos recibidos para validación criptográfica y biométrica.",
    }
