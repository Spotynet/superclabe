"""Módulo 1 (cont.): KYC gradual - Regla 72a. Elevación de nivel por documentos."""

# SC-DEV-SIG-v1: WboTbzJE0cNPg4haaTu1wmTVzQUln3wsdQPQ3id_flt-kuNdYOk6VIJOPkyyxwCgJ8-0aj6y3gl87gS-V_HI4pI3F33NvfJlKH44OXfurF7Os8iRWf6q9UgpDGBZN7edVQZbWLY8_Q==
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..notify import notify
from ..config import settings
from ..crypto import decrypt_aes, encrypt_aes
from ..database import get_db
from ..models import CompanyMetadata, IndividualMetadata, KycDossier, User
from ..schemas import KycFileIn, KycUpgradeIn
from ..security import get_current_user

# Adjuntos que sí se guardan en el expediente. La contraseña de la e.firma no.
_FILE_IDS = {"kFront", "kBack", "kSelfie", "kProof", "kActa", "kCsf", "kCer", "kKey"}
_DATA_URL = re.compile(r"^data:([a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*);base64,[a-z0-9+/=\s]+$", re.I)
_MIME_OK = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "application/pdf", "application/octet-stream",
    "application/pkix-cert", "application/x-x509-ca-cert",
}
_TEXT_FIELDS = (
    "curp", "rfc", "full_name", "business_name", "representative_name",
    "birth_date", "gender", "address", "id_doc_type",
)

router = APIRouter(prefix="/api/v1/kyc", tags=["1. Perfil Financiero (Regla 72a)"])

# Requisito mínimo de identidad al subir a Nivel 2 (según tipo de cliente).
# Los documentos (INE/pasaporte/residencia, selfie de vida) se capturan en el
# cliente; los niveles superiores no vuelven a exigir el dato base de identidad.
def _required(client_type: str, level: int):
    if level == 2:
        return ["curp"] if client_type == "individual" else ["rfc"]
    return []


def _check_file(f: KycFileIn) -> dict:
    if f.id not in _FILE_IDS:
        raise HTTPException(422, "Tipo de adjunto no permitido")
    match = _DATA_URL.match(f.data.strip())
    if not match:
        raise HTTPException(422, f"El archivo {f.label} no es un adjunto válido")
    mime = match.group(1).lower()
    if mime not in _MIME_OK:
        raise HTTPException(422, f"Formato no permitido en {f.label}")
    name = f.name.replace("\\", "/").split("/")[-1].strip() or "adjunto"
    return {"id": f.id, "label": f.label.strip(), "name": name[:180], "mime": mime, "data": f.data.strip()}


def merge_dossier(prev: dict | None, fields: dict, files: list) -> dict:
    """Conserva lo ya capturado y sustituye solo los campos y archivos nuevos."""
    base = prev if isinstance(prev, dict) else {}
    stored = dict(base.get("fields") or {})
    for key, value in fields.items():
        if value:
            stored[key] = value
    by_id = {item["id"]: item for item in (base.get("files") or []) if item.get("id") in _FILE_IDS}
    for item in files:
        by_id[item["id"]] = item
    return {"fields": stored, "files": list(by_id.values())}


def _load_dossier(db: Session, user_id) -> tuple[KycDossier | None, dict]:
    row = db.query(KycDossier).filter(KycDossier.user_id == user_id).first()
    if not row:
        return None, {}
    try:
        data = json.loads(decrypt_aes(row.payload_encrypted) or "{}")
    except Exception:
        data = {}
    return row, data if isinstance(data, dict) else {}


def _save_dossier(db: Session, user: User, body: KycUpgradeIn) -> None:
    fields = {}
    for key in _TEXT_FIELDS:
        value = getattr(body, key, None)
        if isinstance(value, str) and value.strip():
            fields[key] = value.strip()
    files = [_check_file(f) for f in (body.files or [])]
    row, prev = _load_dossier(db, user.id)
    payload = json.dumps(merge_dossier(prev, fields, files), ensure_ascii=False)
    blob = encrypt_aes(payload)
    if row:
        row.payload_encrypted = blob
        row.updated_at = datetime.utcnow()
    else:
        db.add(KycDossier(user_id=user.id, payload_encrypted=blob))


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
    _save_dossier(db, user, body)
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
