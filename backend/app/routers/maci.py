"""
MACI Router — registro de llaves públicas de votantes (ADR-001, D-3).

Primera pieza de la gobernanza incoercible: cada ciudadano registra la llave
pública Baby Jubjub con la que cifrará sus papeletas hacia el coordinador.

Este router NO habilita votación privada todavía. Falta cifrar papeletas,
encolar mensajes, desplegar el coordinador y probar el tally on-chain. Los
endpoints de votación actuales siguen siendo los de `governance.py`.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..services import maci_service
from .deps import current_address, ensure_acts_as_self, ensure_active_member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maci", tags=["MACI"])


class MaciPublicKey(BaseModel):
    x: str
    y: str


class RegisterMaciKeyRequest(BaseModel):
    wallet_address: str
    public_key: MaciPublicKey


@router.post("/keys")
async def register_maci_key(
    request: RegisterMaciKeyRequest,
    authenticated: str = Depends(current_address),
):
    """Registra (o reemplaza) la llave MACI del ciudadano.

    Reemplazar es parte del protocolo, no un efecto secundario: cambiar de
    llave es cómo un votante anula en secreto una papeleta emitida bajo
    coacción.
    """
    ensure_acts_as_self(
        request.wallet_address, authenticated, "registrar una llave MACI"
    )
    # Solo miembros activos: una llave de alguien que no puede votar no aporta
    # nada al coordinador y ensuciaría el árbol de votantes.
    await ensure_active_member(request.wallet_address, "registrar una llave MACI")

    try:
        record = await maci_service.register_public_key(
            request.wallet_address,
            request.public_key.x,
            request.public_key.y,
        )
    except maci_service.MaciKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"ok": True, "key": record.as_response()}


@router.get("/keys/{wallet_address}")
async def get_maci_key(wallet_address: str):
    """Llave vigente de una wallet. Pública: no revela nada del votante."""
    record = await maci_service.get_public_key(wallet_address)
    if not record:
        return {"registered": False, "wallet_address": wallet_address.lower()}
    return {"registered": True, "key": record.as_response()}


@router.get("/status")
async def maci_status():
    """Estado honesto de la integración MACI.

    Declara explícitamente que la votación privada todavía no está operativa:
    hay registro de llaves, pero no coordinador ni tally verificable. Sin este
    endpoint, un cliente podría deducir de la existencia de /maci/keys que ya
    puede votar en privado.
    """
    return {
        "key_registry": True,
        "registered_keys": await maci_service.registered_key_count(),
        "private_voting": False,
        "coordinator_configured": False,
        "tally_proof": False,
        "detail": (
            "Solo está operativo el registro de llaves. Cifrado de papeletas, "
            "coordinador y prueba de tally siguen pendientes (ROADMAP fase 3)."
        ),
    }
