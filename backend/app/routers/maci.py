"""
MACI Router — registro de llaves públicas de votantes (ADR-001, D-3).

Primera pieza de la gobernanza incoercible: cada ciudadano registra la llave
pública Baby Jubjub con la que cifrará sus papeletas hacia el coordinador.

Este router NO habilita votación privada todavía. Registra llaves y encola
mensajes cifrados conservando su orden, pero falta desplegar el coordinador y
construir el circuito de tally: sin ellos ningún resultado es verificable, y
por eso /polls/{id}/tally nunca devuelve un conteo. Los endpoints de votación
en vigor siguen siendo los de `governance.py`.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from typing import List

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


# === Votos cifrados y recuento ===============================================


class EncryptedVoteRequest(BaseModel):
    """Un mensaje MACI. El backend no puede leerlo, y no debe intentarlo.

    `poll_id` agrupa los mensajes de una consulta. `ephemeral_public_key` es
    la llave efímera del votante para este mensaje concreto — cambia en cada
    envío, de modo que dos mensajes de la misma persona no se puedan enlazar.
    """

    poll_id: str
    wallet_address: str
    ephemeral_public_key: MaciPublicKey
    ciphertext: List[str]


@router.post("/vote")
async def publish_encrypted_vote(
    request: EncryptedVoteRequest,
    authenticated: str = Depends(current_address),
):
    """Encola un voto cifrado.

    El servidor no distingue un voto de una anulación: ambos son texto
    cifrado con la misma forma. Esa indistinguibilidad ES la garantía
    anti-coerción, no una carencia — si el backend pudiera separarlos, un
    coaccionador podría exigir la prueba de cuál fue cuál.

    Se exige llave MACI registrada: sin ella el coordinador no tiene contra
    qué validar el mensaje y el voto se perdería en el recuento.
    """
    ensure_acts_as_self(request.wallet_address, authenticated, "emitir un voto")
    await ensure_active_member(request.wallet_address, "votar")

    if not await maci_service.get_public_key(request.wallet_address):
        raise HTTPException(
            status_code=409,
            detail=(
                "Registra tu llave MACI antes de votar: sin ella el coordinador "
                "no puede procesar tu papeleta."
            ),
        )

    try:
        result = await maci_service.publish_message(
            poll_id=request.poll_id,
            wallet_address=request.wallet_address,
            ephemeral_x=request.ephemeral_public_key.x,
            ephemeral_y=request.ephemeral_public_key.y,
            ciphertext=request.ciphertext,
        )
    except (maci_service.MaciKeyError, maci_service.MaciMessageError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # No se registra la wallet junto al índice: enlazarlos en los logs
    # reintroduciría exactamente la trazabilidad que MACI elimina.
    logger.info("MACI message queued for poll %s", request.poll_id)
    return {"ok": True, **result}


@router.get("/polls/{poll_id}/tally")
async def get_tally(poll_id: str):
    """Estado del recuento de una consulta.

    Devuelve el acumulador de mensajes —que cualquiera puede recomputar desde
    los eventos on-chain— y declara explícitamente que NO hay resultado.

    No se publica ningún conteo parcial ni estimado. Un recuento sin la prueba
    del coordinador no es un resultado: es justo el número no verificable que
    MACI existe para eliminar, y mostrarlo invitaría a tratarlo como oficial.
    """
    state = await maci_service.poll_state(poll_id)
    return {
        **state,
        "tallied": False,
        "results": None,
        "tally_proof_verified": False,
        "detail": (
            "El circuito de tally todavía no existe, así que ningún resultado "
            "es verificable. El acumulador permite auditar que los mensajes "
            "encolados coinciden con los publicados on-chain."
        ),
    }
