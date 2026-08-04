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

from pydantic import BaseModel, ConfigDict

from ..core.config import settings
from ..services import chain_service, maci_service
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
        # Cuatro garantías del PROTOCOLO que la auditoría cruzada encontró
        # ausentes (REQUEST_TO_CLAUDE.md, TAREA 5). Van en false porque hoy no
        # se cumplen, y solo pueden subir tras pruebas negativas contra el
        # circuito, el verifier y el contrato REALES — no contra un mock.
        # Publicarlas en true sin eso sería afirmar privacidad que no existe.
        #
        # 1. El pollId no entra en el comando firmado ni en messageHash, y
        #    stateIndex no se compara con pathIndices: un mensaje de un poll
        #    puede repetirse en otro.
        "poll_bound_messages": False,
        # 2. currentNonce es entrada privada libre y el nonce no forma parte
        #    de StateLeaf: nada demuestra la transición.
        "stateful_nonces": False,
        # 3. maci_tally acepta la misma hoja repetida en las cinco posiciones
        #    del batch y la suma cinco veces.
        "unique_tally_leaves": False,
        # 4. processMessages produce raíces por mensaje sin enlace verificable
        #    hasta el stateRoot del tally, y las señales públicas del circuito
        #    no coinciden con las que espera publishTally.
        "process_tally_linked": False,
        "detail": (
            "Solo está operativo el registro de llaves. El transporte anónimo "
            "existe pero no acredita anonimato (correlación por IP y tiempo), "
            "y el protocolo tiene cuatro garantías sin cumplir: replay entre "
            "polls, nonces sin estado, hojas duplicadas en el tally y falta de "
            "enlace verificable entre processMessages y el recuento."
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


# === Poll anclado y transporte anónimo (REQUEST_TO_CLAUDE.md) ===============


@router.get("/proposals/{proposal_id}/poll")
async def get_poll_for_proposal(
    proposal_id: str,
    authenticated: str = Depends(current_address),
):
    """Parámetros que el votante necesita para cifrar su papeleta.

    Este endpoint SÍ lleva sesión SIWE: asignar el `state_index` requiere
    saber quién es. El transporte del mensaje cifrado, en cambio, no la lleva
    — separarlos es lo que impide enlazar el ciphertext con la identidad.

    La llave del coordinador se lee de la CADENA, no de la configuración: el
    cliente la contrasta contra `REACT_APP_MACI_COORDINATOR_ADDRESS` y
    recalcula `Poseidon(x,y)`, así que anunciar una llave que no esté anclada
    on-chain solo conseguiría que el navegador rechace la operación.
    """
    await ensure_active_member(authenticated, "votar en esta consulta")

    coordinator_address = settings.MACI_COORDINATOR_ADDRESS.strip()
    if not coordinator_address:
        raise HTTPException(
            status_code=503,
            detail="El coordinador MACI no está configurado en el servidor.",
        )

    key = await maci_service.read_coordinator_key_onchain()
    if key is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No se pudo leer la llave del coordinador desde la cadena. No se "
                "anuncia una llave sin anclaje: cifrar hacia la equivocada "
                "perdería el voto en silencio."
            ),
        )
    pub_x, pub_y = key

    poll_id = await maci_service.poll_id_for_proposal(proposal_id)
    state_index = await maci_service.assign_state_index(poll_id, authenticated)
    nonce = await maci_service.next_nonce(poll_id, authenticated)

    return {
        "protocol_version": maci_service.MACI_PROTOCOL_VERSION,
        "proposal_id": proposal_id,
        "poll_id": poll_id,
        "state_index": str(state_index),
        "nonce": str(nonce),
        "vote_weight": "1",
        "vote_options": {"for": "0", "against": "1", "abstain": "2"},
        "coordinator_contract": coordinator_address,
        "coordinator_public_key": {"x": str(pub_x), "y": str(pub_y)},
        "coordinator_key_hash": maci_service.coordinator_key_hash(pub_x, pub_y),
        "chain_id": str(settings.SIWE_CHAIN_ID),
        # Sigue en false: falta el anclaje verificable entre proposal_id,
        # poll_id y deadline que exige REQUEST_TO_CLAUDE.md.
        "accepting_messages": False,
        "deadline": None,
    }


class AnonymousMessage(BaseModel):
    # `forbid` también aquí: un campo extra dentro del mensaje es igual de
    # capaz de transportar identidad que uno de primer nivel.
    model_config = ConfigDict(extra="forbid")

    data: List[str]


class AnonymousMessageRequest(BaseModel):
    """Frontera anónima. NO acepta wallet_address, choice, comando, firma,
    salt, shared key ni llave privada: cualquiera de esos campos volvería a
    enlazar el texto cifrado con una persona.

    `extra="forbid"` es la diferencia entre decir eso y cumplirlo. Antes, un
    cliente que enviara `wallet_address` recibía 200: Pydantic descartaba el
    campo en silencio y nadie se enteraba de que el frontend estaba filtrando
    identidad en cada voto. Ahora se rechaza con 422 y el nombre del campo.
    """

    model_config = ConfigDict(extra="forbid")

    protocol_version: str
    proposal_id: str
    poll_id: str
    message: AnonymousMessage
    encryption_public_key: MaciPublicKey
    coordinator_key_hash: str
    idempotency_key: str


@router.post("/polls/{poll_id}/messages")
async def publish_anonymous_message(poll_id: str, request: AnonymousMessageRequest):
    """Transporte anónimo: SIN bearer SIWE, a propósito.

    Llevar la sesión aquí reconstruiría el enlace entre el ciphertext y la
    identidad del votante, que es justo lo que MACI elimina.

    ADVERTENCIA HONESTA: quitar el bearer elimina el identificador directo,
    pero NO resuelve la correlación por IP ni por tiempo. Mientras no exista
    una prueba de elegibilidad anónima o un relay, este transporte no basta
    para afirmar anonimato — y por eso `/maci/status` mantiene
    `private_voting: false`.
    """
    if request.protocol_version != maci_service.MACI_PROTOCOL_VERSION:
        raise HTTPException(
            status_code=422,
            detail=f"Versión de protocolo no soportada: {request.protocol_version}",
        )
    if request.poll_id != poll_id:
        raise HTTPException(status_code=422, detail="poll_id inconsistente.")

    # El poll tiene que existir, estar abierto y ser el de esta propuesta.
    # Antes `proposal_id` llegaba y no se miraba: un mensaje podía encolarse
    # contra un poll inexistente o cerrado, creando un acumulador nuevo desde
    # cero que nadie podría reconciliar.
    expected_poll = await maci_service.poll_id_for_proposal(request.proposal_id)
    if expected_poll != poll_id:
        raise HTTPException(
            status_code=422,
            detail="El poll indicado no corresponde a esa propuesta.",
        )

    if not await maci_service.poll_is_open(request.proposal_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "La propuesta de esta urna no existe o su plazo ya terminó. "
                "Un mensaje encolado ahora no lo contaría nadie."
            ),
        )

    key = await maci_service.read_coordinator_key_onchain()
    if key is None:
        raise HTTPException(
            status_code=503, detail="No se pudo verificar la llave del coordinador."
        )
    expected_hash = maci_service.coordinator_key_hash(*key)
    if request.coordinator_key_hash.lower() != expected_hash.lower():
        # El cliente cifró hacia otra llave: aceptarlo produciría un voto que
        # el coordinador no puede descifrar y que se perdería en silencio.
        raise HTTPException(
            status_code=409,
            detail=(
                "El mensaje se cifró hacia una llave de coordinador distinta de "
                "la anclada on-chain. No se acepta: el voto sería ilegible."
            ),
        )

    try:
        result = await maci_service.publish_anonymous_message(
            poll_id=poll_id,
            ephemeral_x=request.encryption_public_key.x,
            ephemeral_y=request.encryption_public_key.y,
            ciphertext=request.message.data,
            idempotency_key=request.idempotency_key,
        )
    except (maci_service.MaciKeyError, maci_service.MaciMessageError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # No se registra nada que identifique al remitente.
    logger.info("Anonymous MACI message queued for poll %s", poll_id)
    return {"ok": True, **result}
