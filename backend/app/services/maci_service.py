"""
Registro de llaves públicas MACI (ADR-001, D-3).

MACI (Minimal Anti-Collusion Infrastructure) hace que un voto no se pueda
vender ni coaccionar: el votante cifra su papeleta con la llave pública del
coordinador, y puede reemplazarla enviando otra con una llave nueva. Como
nadie salvo el coordinador puede descifrar, un comprador de votos no puede
comprobar qué votó realmente la persona, y la persona siempre puede anular en
secreto lo que prometió.

Este módulo cubre la primera pieza: el registro de la llave pública MACI de
cada ciudadano.

Detalles que importan y no son evidentes:

* Una llave MACI es un punto de la curva **Baby Jubjub**, no una clave
  Ethereum. Se representa como el par (x, y), ambos elementos del campo
  escalar de BN254. Aceptar cualquier par de enteros dejaría entrar puntos
  que no están en la curva, y el coordinador no podría operar con ellos.
* Solo un miembro activo puede registrar llave, y solo la suya: la sesión
  SIWE debe pertenecer a la misma wallet.
* Registrar de nuevo **reemplaza** la llave anterior. Eso no es un descuido:
  es el mecanismo de anti-coerción de MACI (key change). Se conserva el
  historial para que el coordinador pueda reconstruir el orden.

Lo que este módulo NO hace todavía, y por eso no se anuncia como votación
privada: no cifra ni descifra nada (el cifrado ocurre en el cliente y solo el
coordinador puede revertirlo), no hay coordinador desplegado y no existe el
circuito de tally. Encola mensajes y conserva su orden, que es todo lo que un
servidor puede hacer sin poder leerlos. Ver docs/ROADMAP.md fase 3.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..core.database import get_collection

logger = logging.getLogger(__name__)

# Campo escalar de BN254: el mismo en el que vive Baby Jubjub.
BN254_FIELD = (
    21888242871839275222246405745257275088548364400416034343698204186575808495617
)

# Baby Jubjub en forma de Edwards retorcida:  a·x² + y² = 1 + d·x²·y²
# Constantes del estándar (EIP-2494), las mismas que usa circomlib.
BABYJUB_A = 168700
BABYJUB_D = 168696

# Orden del subgrupo primo de Baby Jubjub (EIP-2494). El cofactor es 8, así
# que la curva contiene puntos de orden 1, 2, 4 y 8 que están EN la curva pero
# no en el subgrupo útil. Aceptarlos permite ataques de subgrupo pequeño: el
# coordinador filtraría información de su clave privada al operar con ellos.
BABYJUB_SUBORDER = (
    2736030358979909402780800718157159386076813972158567259200215660948447373041
)

# Punto identidad del grupo (elemento neutro en forma de Edwards retorcida).
IDENTITY_POINT = (0, 1)

# Generador del subgrupo de orden primo (EIP-2494 / circomlib).
BASE8 = (
    5299619240641551281634865583518297030282874472190772894086521144482721001553,
    16950150798460657717958625567821834550301663161624707787222815936182638968203,
)


def _point_add(p1: tuple[int, int], p2: tuple[int, int]) -> tuple[int, int]:
    """Suma en Edwards retorcida (fórmula completa, sin casos especiales)."""
    x1, y1 = p1
    x2, y2 = p2
    x1x2 = x1 * x2 % BN254_FIELD
    y1y2 = y1 * y2 % BN254_FIELD
    dprod = BABYJUB_D * x1x2 % BN254_FIELD * y1y2 % BN254_FIELD

    x3 = (x1 * y2 + y1 * x2) % BN254_FIELD * pow(1 + dprod, -1, BN254_FIELD)
    y3 = (y1y2 - BABYJUB_A * x1x2) % BN254_FIELD * pow(1 - dprod, -1, BN254_FIELD)
    return (x3 % BN254_FIELD, y3 % BN254_FIELD)


def _scalar_mul(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    """Multiplicación escalar por duplicación y suma."""
    result = IDENTITY_POINT
    addend = point
    while scalar > 0:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def is_in_prime_subgroup(x: int, y: int) -> bool:
    """True si [subOrder]P == identidad, es decir, si P tiene orden primo.

    Sin esta comprobación entran puntos de orden bajo (orden 2, 4 u 8). Están
    en la curva y pasan la ecuación, pero cifrar hacia ellos degenera el
    espacio de claves: el resultado toma muy pocos valores posibles y filtra
    la clave privada del coordinador.
    """
    return _scalar_mul((x, y), BABYJUB_SUBORDER) == IDENTITY_POINT


class MaciKeyError(ValueError):
    """La llave pública no es un punto válido de Baby Jubjub."""


def maci_keys_collection():
    return get_collection("maci_keys")


def maci_key_history_collection():
    return get_collection("maci_key_history")


def _parse_coordinate(value, label: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise MaciKeyError(f"{label} debe ser un entero decimal.")
    if parsed < 0 or parsed >= BN254_FIELD:
        raise MaciKeyError(f"{label} está fuera del campo escalar BN254.")
    return parsed


def is_on_babyjub_curve(x: int, y: int) -> bool:
    """Comprueba a·x² + y² == 1 + d·x²·y² (mod p).

    Sin esto, cualquier par de enteros pasaría por llave. Un punto fuera de la
    curva no sirve para cifrar hacia el coordinador: la papeleta quedaría
    ilegible y el voto se perdería en silencio, que es exactamente el fallo
    más difícil de diagnosticar en un sistema electoral.
    """
    x2 = (x * x) % BN254_FIELD
    y2 = (y * y) % BN254_FIELD
    left = (BABYJUB_A * x2 + y2) % BN254_FIELD
    right = (1 + BABYJUB_D * x2 % BN254_FIELD * y2) % BN254_FIELD
    return left == right


def validate_public_key(x, y) -> tuple[int, int]:
    """Normaliza y valida la llave. Lanza MaciKeyError si no es válida."""
    parsed_x = _parse_coordinate(x, "La coordenada x")
    parsed_y = _parse_coordinate(y, "La coordenada y")

    # El punto identidad (0, 1) es válido en la curva pero no es una llave
    # utilizable: corresponde a la clave privada cero.
    if parsed_x == 0 and parsed_y == 1:
        raise MaciKeyError("El punto identidad no es una llave pública válida.")

    if not is_on_babyjub_curve(parsed_x, parsed_y):
        raise MaciKeyError("La llave pública no pertenece a la curva Baby Jubjub.")

    # Estar en la curva NO basta: el cofactor 8 deja puntos de orden bajo que
    # satisfacen la ecuación pero degeneran el cifrado.
    if not is_in_prime_subgroup(parsed_x, parsed_y):
        raise MaciKeyError(
            "La llave pública tiene orden bajo: no pertenece al subgrupo primo "
            "de Baby Jubjub."
        )

    return parsed_x, parsed_y


@dataclass(frozen=True)
class MaciKeyRecord:
    wallet_address: str
    x: int
    y: int
    version: int
    registered_at: datetime

    def as_response(self) -> dict:
        return {
            "wallet_address": self.wallet_address,
            "public_key": {"x": str(self.x), "y": str(self.y)},
            "version": self.version,
            "registered_at": self.registered_at.isoformat(),
        }


async def register_public_key(wallet_address: str, x, y) -> MaciKeyRecord:
    """Registra o reemplaza la llave MACI de una wallet.

    El reemplazo es deliberado: en MACI cambiar de llave es cómo un votante
    anula en secreto una papeleta emitida bajo coacción. Se guarda el
    historial porque el coordinador necesita el orden de los cambios para
    procesar los mensajes.
    """
    address = wallet_address.lower()
    parsed_x, parsed_y = validate_public_key(x, y)
    now = datetime.now(timezone.utc)

    previous = await maci_keys_collection().find_one({"wallet_address": address})
    version = (int(previous["version"]) + 1) if previous else 1

    if previous and int(previous["x"]) == parsed_x and int(previous["y"]) == parsed_y:
        # Reenviar la misma llave no genera una versión nueva: un reintento por
        # timeout no debe parecerle al coordinador un cambio de llave.
        return MaciKeyRecord(
            wallet_address=address,
            x=parsed_x,
            y=parsed_y,
            version=int(previous["version"]),
            registered_at=previous["registered_at"],
        )

    await maci_keys_collection().update_one(
        {"wallet_address": address},
        {
            "$set": {
                "wallet_address": address,
                "x": str(parsed_x),
                "y": str(parsed_y),
                "version": version,
                "registered_at": now,
            }
        },
        upsert=True,
    )
    await maci_key_history_collection().insert_one({
        "wallet_address": address,
        "x": str(parsed_x),
        "y": str(parsed_y),
        "version": version,
        "registered_at": now,
    })

    logger.info("MACI key registered for %s (version %s)", address[:10], version)
    return MaciKeyRecord(
        wallet_address=address,
        x=parsed_x,
        y=parsed_y,
        version=version,
        registered_at=now,
    )


async def get_public_key(wallet_address: str) -> Optional[MaciKeyRecord]:
    record = await maci_keys_collection().find_one(
        {"wallet_address": wallet_address.lower()}
    )
    if not record:
        return None
    return MaciKeyRecord(
        wallet_address=record["wallet_address"],
        x=int(record["x"]),
        y=int(record["y"]),
        version=int(record["version"]),
        registered_at=record["registered_at"],
    )


async def registered_key_count() -> int:
    return await maci_keys_collection().count_documents({})


# === Mensajes cifrados y recuento (ADR-001, D-3) ===============================
#
# Un mensaje MACI es texto cifrado hacia la llave del coordinador. El backend
# NO puede leerlo — ese es justamente el punto — así que su papel se limita a:
# validar la forma, conservar el ORDEN y exponer el acumulador.
#
# El orden decide el resultado: en MACI vale el último mensaje válido de cada
# llave, y así es como un votante coaccionado anula en secreto lo prometido.

# El tamaño lo fija el circuito de MACI: 10 elementos de campo por mensaje.
CIPHERTEXT_LENGTH = 10


def maci_messages_collection():
    return get_collection("maci_messages")


def maci_polls_collection():
    return get_collection("maci_polls")


class MaciMessageError(ValueError):
    """El mensaje cifrado no tiene la forma que espera el circuito."""


def validate_ciphertext(ciphertext) -> list[int]:
    """Cada elemento debe caber en el campo escalar. No se lee el contenido."""
    if not isinstance(ciphertext, (list, tuple)):
        raise MaciMessageError("El texto cifrado debe ser una lista.")
    if len(ciphertext) != CIPHERTEXT_LENGTH:
        raise MaciMessageError(
            f"El texto cifrado debe tener {CIPHERTEXT_LENGTH} elementos."
        )
    parsed = []
    for index, value in enumerate(ciphertext):
        try:
            element = int(str(value).strip())
        except (TypeError, ValueError):
            raise MaciMessageError(f"El elemento {index} no es un entero decimal.")
        if element < 0 or element >= BN254_FIELD:
            raise MaciMessageError(f"El elemento {index} está fuera del campo BN254.")
        parsed.append(element)
    return parsed


async def publish_message(
    poll_id: str,
    wallet_address: str,
    ephemeral_x,
    ephemeral_y,
    ciphertext,
) -> dict:
    """Encola un mensaje cifrado y devuelve su posición y el acumulador.

    El acumulador encadena el hash anterior con el mensaje, igual que
    MACICoordinator.publishMessage on-chain, para que ambos puedan
    contrastarse. Se guarda `index` porque el orden es parte del resultado.
    """
    import hashlib

    address = wallet_address.lower()
    eph_x, eph_y = validate_public_key(ephemeral_x, ephemeral_y)
    parsed = validate_ciphertext(ciphertext)

    poll = await maci_polls_collection().find_one({"poll_id": poll_id})
    previous_chain = poll["message_chain"] if poll else "0" * 64
    index = int(poll["message_count"]) if poll else 0

    payload = ":".join(
        [previous_chain, str(eph_x), str(eph_y)] + [str(v) for v in parsed]
    )
    chain = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    import uuid as _uuid

    await maci_messages_collection().insert_one({
        "poll_id": poll_id,
        # Se guarda la wallet para exigir membresía e inscripción, no para
        # vincularla con el contenido: el mensaje es ilegible sin la llave del
        # coordinador, y el emisor de un voto y el de una anulación son
        # indistinguibles.
        "wallet_address": address,
        # Clave propia para que el índice único de idempotencia tenga siempre
        # valor. Un índice compuesto `sparse` NO omite el documento cuando solo
        # falta uno de sus campos, así que dejarla nula hacía colisionar dos
        # mensajes autenticados cualesquiera.
        "idempotency_key": _uuid.uuid4().hex,
        "index": index,
        "ephemeral_x": str(eph_x),
        "ephemeral_y": str(eph_y),
        "ciphertext": [str(v) for v in parsed],
        "message_chain": chain,
        "published_at": datetime.now(timezone.utc),
    })
    await maci_polls_collection().update_one(
        {"poll_id": poll_id},
        {"$set": {"message_chain": chain, "message_count": index + 1}},
        upsert=True,
    )

    return {"index": index, "message_chain": chain}


async def poll_state(poll_id: str) -> dict:
    poll = await maci_polls_collection().find_one({"poll_id": poll_id})
    return {
        "poll_id": poll_id,
        "message_count": int(poll["message_count"]) if poll else 0,
        "message_chain": poll["message_chain"] if poll else "0" * 64,
    }


# === Polls anclados y transporte anónimo (REQUEST_TO_CLAUDE.md) ==============

MACI_PROTOCOL_VERSION = "maci-v2.5.0"

# MACI reserva el índice 0 del state tree: un votante real empieza en 1.
FIRST_STATE_INDEX = 1

# Los enteros empaquetados en un comando deben caber en 50 bits.
MAX_PACKED_INT = 1 << 50


def maci_poll_registry_collection():
    return get_collection("maci_poll_registry")


def coordinator_key_hash(x: int, y: int) -> str:
    """Poseidon(x, y) como bytes32. El cliente lo recalcula y compara.

    Sirve para que el navegador detecte que el backend le anunció una llave
    distinta de la que está anclada on-chain, sin tener que confiar en él.
    """
    from ..core.poseidon import poseidon

    return "0x" + poseidon([x, y]).to_bytes(32, "big").hex()


async def assign_state_index(poll_id: str, wallet_address: str) -> int:
    """Índice del votante en el state tree de esta consulta.

    Empieza en 1 porque MACI reserva el 0. Es estable por wallet y consulta:
    reasignarlo en un reintento rompería el nonce del votante.
    """
    address = wallet_address.lower()
    existing = await maci_poll_registry_collection().find_one(
        {"poll_id": poll_id, "wallet_address": address}
    )
    if existing:
        return int(existing["state_index"])

    assigned = await maci_poll_registry_collection().count_documents(
        {"poll_id": poll_id}
    )
    state_index = FIRST_STATE_INDEX + assigned
    await maci_poll_registry_collection().insert_one({
        "poll_id": poll_id,
        "wallet_address": address,
        "state_index": state_index,
        "nonce": 0,
        "assigned_at": datetime.now(timezone.utc),
    })
    return state_index


async def next_nonce(poll_id: str, wallet_address: str) -> int:
    record = await maci_poll_registry_collection().find_one(
        {"poll_id": poll_id, "wallet_address": wallet_address.lower()}
    )
    return (int(record["nonce"]) + 1) if record else 1


async def publish_anonymous_message(
    poll_id: str,
    ephemeral_x,
    ephemeral_y,
    ciphertext,
    idempotency_key: str,
) -> dict:
    """Encola un mensaje SIN identificar al remitente.

    A diferencia de `publish_message`, aquí no hay `wallet_address`: el
    transporte anónimo no puede recibirla, porque guardarla junto al texto
    cifrado reconstruiría exactamente el enlace que MACI elimina.

    La idempotencia es por `idempotency_key` que aporta el cliente, no por
    wallet: es la única forma de deduplicar un reintento sin identificarlo.
    """
    import hashlib

    if not idempotency_key or len(str(idempotency_key)) < 8:
        raise MaciMessageError("Falta una idempotency_key utilizable.")

    eph_x, eph_y = validate_public_key(ephemeral_x, ephemeral_y)
    parsed = validate_ciphertext(ciphertext)

    duplicate = await maci_messages_collection().find_one(
        {"poll_id": poll_id, "idempotency_key": idempotency_key}
    )
    if duplicate:
        return {
            "index": int(duplicate["index"]),
            "message_chain": duplicate["message_chain"],
            "duplicate": True,
        }

    poll = await maci_polls_collection().find_one({"poll_id": poll_id})
    previous_chain = poll["message_chain"] if poll else "0" * 64
    index = int(poll["message_count"]) if poll else 0

    payload = ":".join(
        [previous_chain, str(eph_x), str(eph_y)] + [str(v) for v in parsed]
    )
    chain = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    await maci_messages_collection().insert_one({
        "poll_id": poll_id,
        # Sin wallet_address: es la diferencia con el transporte autenticado.
        "index": index,
        "ephemeral_x": str(eph_x),
        "ephemeral_y": str(eph_y),
        "ciphertext": [str(v) for v in parsed],
        "message_chain": chain,
        "idempotency_key": idempotency_key,
        "published_at": datetime.now(timezone.utc),
    })
    await maci_polls_collection().update_one(
        {"poll_id": poll_id},
        {"$set": {"message_chain": chain, "message_count": index + 1}},
        upsert=True,
    )
    return {"index": index, "message_chain": chain, "duplicate": False}


async def poll_id_for_proposal(proposal_id: str) -> str:
    """Poll estable por propuesta.

    ADVERTENCIA: este vínculo hoy solo existe en la base de datos. Hasta que el
    contrato exponga un anclaje verificable entre proposal_id, poll_id y
    deadline, el cliente no puede comprobar que el backend anunció el poll
    correcto — por eso `accepting_messages` y `private_voting` van en false.
    """
    record = await maci_poll_registry_collection().find_one(
        {"proposal_id": proposal_id, "kind": "poll"}
    )
    if record:
        return str(record["poll_id"])

    assigned = await maci_poll_registry_collection().count_documents({"kind": "poll"})
    poll_id = str(assigned + 1)
    await maci_poll_registry_collection().insert_one({
        "kind": "poll",
        "proposal_id": proposal_id,
        "poll_id": poll_id,
        "created_at": datetime.now(timezone.utc),
    })
    return poll_id


async def read_coordinator_key_onchain():
    """Llave del coordinador leída del contrato. None si no se puede.

    Se lee de la cadena y no de la configuración a propósito: es lo que el
    cliente puede contrastar por su cuenta.
    """
    import asyncio

    from . import chain_service

    return await asyncio.to_thread(chain_service.maci_coordinator_key)


def derive_public_key(private_key: int) -> tuple[int, int]:
    """pub = priv · Base8. La inversa es intratable: es lo que protege el voto."""
    if not isinstance(private_key, int) or isinstance(private_key, bool):
        raise MaciKeyError("La llave privada debe ser un entero.")
    if private_key <= 0 or private_key >= BABYJUB_SUBORDER:
        raise MaciKeyError(
            "La llave privada debe estar en [1, subOrder): fuera de ese rango "
            "el punto resultante no pertenece al subgrupo primo."
        )
    return _scalar_mul(BASE8, private_key)


def generate_coordinator_keypair() -> tuple[int, tuple[int, int]]:
    """Genera un par de llaves del coordinador. Devuelve (privada, pública).

    ADVERTENCIA: la llave privada descifra TODOS los votos de la consulta.
    Esta función existe para que la ejecute quien vaya a custodiarla, en su
    propia máquina — no un proceso automatizado cuyo entorno es efímero. El
    resultado se valida antes de devolverlo, así que una llave publicada con
    esto está garantizadamente en el subgrupo primo.
    """
    import secrets

    private_key = secrets.randbelow(BABYJUB_SUBORDER - 1) + 1
    public_key = derive_public_key(private_key)
    # Se valida con la MISMA función que filtra las llaves de los votantes.
    validate_public_key(*public_key)
    return private_key, public_key
