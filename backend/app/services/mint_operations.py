"""
Ciclo de vida y reconciliación de las operaciones de minteo ZK (ROADMAP 1/3).

El problema que resuelve: entre "el relayer difunde la transacción" y "Mongo
sabe cómo acabó" hay hasta 120 segundos de espera de recibo. Si el proceso se
cae dentro de esa ventana, la cadena y la base de datos quedan diciendo cosas
distintas, y ninguna de las dos puede arreglarse sola.

Los estados son el diseño, no una etiqueta:

* ``pending``      — la operación está reclamada, pero NADA se ha difundido.
                     Si se queda atrás, no pasó nada on-chain y se puede
                     reintentar sin coste.
* ``submitted``    — la transacción SÍ salió a la red. Su suerte la decide la
                     cadena, nunca un temporizador de este proceso. Antes esto
                     no existía: un timeout marcaba ``failed`` y el reintento
                     enviaba una SEGUNDA transacción que revertía por nullifier
                     repetido, quemando gas de la DAO para nada.
* ``confirmed``    — hay tokenId. Se refleja en ``members`` en el mismo paso.
* ``failed``       — se comprobó contra la cadena que no hubo efecto. Es el
                     único estado desde el que se puede reintentar.
* ``needs_review`` — la cadena contradice nuestro registro (por ejemplo, el
                     nullifier está consumido pero esta wallet no tiene SBT).
                     No se adivina: lo mira una persona.

Regla que atraviesa todo el módulo: **un RPC que no responde nunca se lee como
"no pasó nada"**. Todas las lecturas de cadena devuelven ``None``/``unknown``
ante un fallo, y eso mantiene la operación en vuelo. Traducir un corte de red a
"puedes reintentar" es justo lo que hace que se gaste gas dos veces.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

from ..core.config import settings
from ..core.database import get_collection
from . import chain_service, membership_records

logger = logging.getLogger(__name__)

PENDING = "pending"
SUBMITTED = "submitted"
CONFIRMED = "confirmed"
FAILED = "failed"
NEEDS_REVIEW = "needs_review"

#: Estados desde los que la operación puede seguir avanzando sola.
OPEN_STATES = (PENDING, SUBMITTED)


def mint_operations_collection():
    """Operaciones de minteo, para idempotencia y reconciliación."""
    return get_collection("mint_operations")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value) -> Optional[datetime]:
    """Normaliza una fecha leída de Mongo a UTC con zona.

    El driver devuelve datetimes SIN tzinfo, así que compararlas con
    `datetime.now(timezone.utc)` revienta. No es un detalle de los tests:
    pasaría igual en producción.
    """
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def is_stale(operation: dict, now: Optional[datetime] = None) -> bool:
    """¿Lleva la operación tanto tiempo abierta que hay que ir a la cadena?

    Se mide desde el último momento en que se supo algo de ella. Sin esta
    ventana, cada reintento del cliente golpearía el RPC; con ella, el 409 de
    "hay un minteo en curso" sigue siendo una respuesta local e inmediata
    mientras la operación es reciente.
    """
    reference = (
        _as_utc(operation.get("submitted_at"))
        or _as_utc(operation.get("retried_at"))
        or _as_utc(operation.get("created_at"))
    )
    if reference is None:
        # Sin fecha no se puede afirmar que sea reciente, y dejar una operación
        # bloqueada para siempre es peor que consultar la cadena una vez.
        return True
    threshold = timedelta(seconds=settings.MINT_PENDING_STALE_SECONDS)
    return (now or _now()) - reference >= threshold


# === Decisión de entrada ======================================================


@dataclass(frozen=True)
class MintDecision:
    """Qué debe hacer el router con esta petición de minteo."""

    action: str  # "proceed" | "confirmed" | "in_flight" | "needs_review"
    token_id: Optional[int] = None
    tx_hash: Optional[str] = None
    detail: Optional[str] = None


IN_FLIGHT_DETAIL = (
    "Ya hay un minteo en curso para esta credencial. Espera a que confirme."
)

# El motivo técnico se guarda y se registra, pero no se le devuelve al
# ciudadano: no es accionable para él y describe el estado interno.
NEEDS_REVIEW_DETAIL = (
    "Esta credencial quedó en un estado que requiere revisión manual. "
    "Contacta al equipo antes de reintentar."
)


async def begin(nullifier_hash: str, wallet_address: str) -> MintDecision:
    """Reclama el derecho a enviar la transacción, o explica por qué no.

    El nullifier es el identificador natural de la operación: el contrato
    rechazaría un duplicado, pero para entonces el gas ya se gastó.

    Una operación abierta ya no produce un 409 automático. Primero se le
    pregunta a la cadena qué pasó: así una caída del worker deja de convertir
    la credencial en un 409 permanente sin salida.
    """
    nullifier = nullifier_hash.lower()
    address = wallet_address.lower()

    existing = await mint_operations_collection().find_one(
        {"nullifier_hash": nullifier}
    )

    if existing is None:
        try:
            await mint_operations_collection().insert_one(
                {
                    "nullifier_hash": nullifier,
                    "wallet_address": address,
                    "status": PENDING,
                    "attempts": 1,
                    "created_at": _now(),
                }
            )
        except DuplicateKeyError:
            # Otra petición idéntica entró en el mismo instante.
            return MintDecision(action="in_flight", detail=IN_FLIGHT_DETAIL)
        return MintDecision(action="proceed")

    status = existing.get("status")

    if status == CONFIRMED:
        return MintDecision(
            action="confirmed",
            token_id=existing.get("token_id"),
            tx_hash=existing.get("tx_hash"),
        )

    if status == NEEDS_REVIEW:
        return MintDecision(action="needs_review", detail=NEEDS_REVIEW_DETAIL)

    if status in OPEN_STATES:
        resolution = await resolve(existing)
        if resolution.status == CONFIRMED:
            return MintDecision(
                action="confirmed",
                token_id=resolution.token_id,
                tx_hash=resolution.tx_hash,
            )
        if resolution.status == NEEDS_REVIEW:
            return MintDecision(action="needs_review", detail=NEEDS_REVIEW_DETAIL)
        if resolution.status != FAILED:
            return MintDecision(
                action="in_flight", detail=resolution.detail or IN_FLIGHT_DETAIL
            )
        # Resuelta como fallida: cae al reclamo de abajo y se reintenta.

    return await _claim_failed(nullifier)


async def _claim_failed(nullifier: str) -> MintDecision:
    """Transición `failed -> pending`, condicional y por tanto atómica.

    El índice único hacía que un `failed` fuera un 409 permanente: el
    ciudadano se quedaba sin credencial y sin forma de pedir otra. Al ser
    condicional, dos reintentos simultáneos no envían dos transacciones.
    """
    claimed = await mint_operations_collection().update_one(
        {"nullifier_hash": nullifier, "status": FAILED},
        {
            "$set": {"status": PENDING, "retried_at": _now()},
            "$unset": {"tx_hash": "", "submitted_at": "", "error": ""},
            "$inc": {"attempts": 1},
        },
    )
    if claimed.modified_count == 0:
        return MintDecision(
            action="in_flight",
            detail="Otro reintento tomó esta operación. Espera a que confirme.",
        )
    return MintDecision(action="proceed")


# === Transiciones =============================================================


async def mark_submitted(nullifier_hash: str, tx_hash: str) -> None:
    """La transacción salió a la red. A partir de aquí decide la cadena.

    Se escribe ANTES de esperar el recibo: es lo único que permite reconciliar
    una transacción real cuyo proceso murió durante la espera.
    """
    await mint_operations_collection().update_one(
        {"nullifier_hash": nullifier_hash.lower()},
        {"$set": {"status": SUBMITTED, "tx_hash": tx_hash, "submitted_at": _now()}},
    )


async def mark_confirmed(
    nullifier_hash: str,
    wallet_address: str,
    tx_hash: Optional[str],
    token_id: int,
) -> None:
    """Cierra la operación y refleja el SBT en `members`, en ese orden.

    La reconciliación de `members` va aquí y no en el router porque es la
    diferencia entre "el ciudadano tiene su SBT on-chain" y "la API y el gate
    de gobernanza lo saben". Tenerlo suelto en cada llamador fue exactamente
    cómo el camino ERC-4337 se quedó sin escribirlo (AUDIT P-70).
    """
    await mint_operations_collection().update_one(
        {"nullifier_hash": nullifier_hash.lower()},
        {
            "$set": {
                "status": CONFIRMED,
                "tx_hash": tx_hash,
                "token_id": token_id,
                "confirmed_at": _now(),
            }
        },
    )
    await membership_records.reconcile_onchain_membership(
        wallet_address=wallet_address,
        token_id=token_id,
        tx_hash=tx_hash,
        nullifier_hash=nullifier_hash.lower(),
    )


async def mark_failed(nullifier_hash: str, error: str) -> None:
    """Sin efecto on-chain comprobado. Es el único estado reintentable."""
    await mint_operations_collection().update_one(
        {"nullifier_hash": nullifier_hash.lower()},
        {"$set": {"status": FAILED, "error": error, "failed_at": _now()}},
    )


async def mark_needs_review(nullifier_hash: str, reason: str) -> None:
    """La cadena contradice el registro. No se adivina; lo mira una persona."""
    logger.error(
        "Operación de minteo en estado inconsistente (%s): %s",
        nullifier_hash.lower(),
        reason,
    )
    await mint_operations_collection().update_one(
        {"nullifier_hash": nullifier_hash.lower()},
        {
            "$set": {
                "status": NEEDS_REVIEW,
                "review_reason": reason,
                "flagged_at": _now(),
            }
        },
    )


# === Reconciliación contra la cadena ==========================================


@dataclass(frozen=True)
class Resolution:
    status: str  # CONFIRMED | FAILED | NEEDS_REVIEW | "in_flight"
    token_id: Optional[int] = None
    tx_hash: Optional[str] = None
    detail: Optional[str] = None


IN_FLIGHT = "in_flight"


async def resolve(operation: dict) -> Resolution:
    """Decide el destino de una operación abierta preguntándole a la cadena.

    Orden deliberado: primero el recibo (respuesta directa sobre ESTA
    transacción), y solo después el nullifier (respuesta sobre la credencial,
    haya salido por la transacción que haya salido). Al revés se perdería la
    distinción entre "revirtió" y "nunca llegó".
    """
    nullifier = operation["nullifier_hash"]
    wallet = operation["wallet_address"]
    tx_hash = operation.get("tx_hash")

    if tx_hash:
        outcome, token_id = await asyncio.to_thread(
            chain_service.transaction_outcome, tx_hash
        )
        if outcome == "confirmed":
            return await _confirm(nullifier, wallet, tx_hash, token_id)
        if outcome == "reverted":
            # Un revert no cierra el caso: el motivo pudo ser "nullifier ya
            # usado", y entonces la credencial sí existe. Se comprueba antes de
            # declarar que no pasó nada.
            return await _resolve_by_nullifier(
                nullifier, wallet, tx_hash, revert_seen=True
            )
        # "unknown": sigue en el mempool o se cayó de él. Indistinguible.

    if not is_stale(operation):
        return Resolution(status=IN_FLIGHT)

    return await _resolve_by_nullifier(nullifier, wallet, tx_hash, revert_seen=False)


async def _resolve_by_nullifier(
    nullifier: str, wallet: str, tx_hash: Optional[str], revert_seen: bool
) -> Resolution:
    """Fuente de verdad última: ¿está el nullifier consumido en el contrato?"""
    used = await asyncio.to_thread(chain_service.nullifier_is_used, nullifier)

    if used is None:
        # La cadena no respondió. Se mantiene en vuelo a propósito.
        return Resolution(
            status=IN_FLIGHT,
            detail=(
                "No se pudo consultar la cadena para saber si el minteo se "
                "completó. Reintenta en unos minutos."
            ),
        )

    if used:
        token_id = await asyncio.to_thread(chain_service.membership_token_of, wallet)
        if token_id:
            return await _confirm(nullifier, wallet, tx_hash, token_id)
        reason = (
            "el nullifier está consumido en el contrato pero la wallet no "
            "tiene SBT: la credencial se emitió a otra dirección o el token "
            "fue revocado"
        )
        await mark_needs_review(nullifier, reason)
        return Resolution(status=NEEDS_REVIEW, detail=reason)

    error = "revirtió on-chain" if revert_seen else "sin efecto on-chain"
    await mark_failed(nullifier, error)
    return Resolution(status=FAILED, detail=error)


async def _confirm(
    nullifier: str, wallet: str, tx_hash: Optional[str], token_id: Optional[int]
) -> Resolution:
    """Cierra como confirmada, resolviendo el tokenId si el recibo no lo dio."""
    if not token_id:
        token_id = await asyncio.to_thread(chain_service.membership_token_of, wallet)
    if not token_id:
        # Confirmada pero sin tokenId resoluble. No se inventa uno: se deja en
        # vuelo para que el siguiente barrido lo resuelva.
        return Resolution(
            status=IN_FLIGHT,
            detail=(
                "La transacción se confirmó pero aún no se pudo leer el "
                "tokenId. Reintenta en unos minutos."
            ),
        )
    await mark_confirmed(nullifier, wallet, tx_hash, token_id)
    return Resolution(status=CONFIRMED, token_id=token_id, tx_hash=tx_hash)


# === Barrido de operaciones olvidadas =========================================


async def sweep(limit: int = 100) -> dict:
    """Reconcilia las operaciones abiertas y devuelve el recuento por destino.

    Pensado para ejecutarse desde `scripts/reconcile_mints.py`. No hay barrido
    automático en segundo plano: con varias instancias, cada una correría el
    suyo y multiplicaría las llamadas al RPC sin coordinación. Cuando exista el
    coordinador distribuido que ya exige el nonce del relayer, este es el sitio
    donde engancharlo.
    """
    summary = {
        CONFIRMED: 0,
        FAILED: 0,
        NEEDS_REVIEW: 0,
        IN_FLIGHT: 0,
        "scanned": 0,
    }

    cursor = (
        mint_operations_collection()
        .find({"status": {"$in": list(OPEN_STATES)}})
        .sort("created_at", 1)
        .limit(limit)
    )
    async for operation in cursor:
        summary["scanned"] += 1
        try:
            resolution = await resolve(operation)
        except Exception:
            logger.error(
                "Fallo reconciliando la operación %s",
                operation.get("nullifier_hash"),
                exc_info=True,
            )
            summary[IN_FLIGHT] += 1
            continue
        summary[resolution.status] = summary.get(resolution.status, 0) + 1

    return summary
