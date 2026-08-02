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

    await maci_messages_collection().insert_one({
        "poll_id": poll_id,
        # Se guarda la wallet para exigir membresía e inscripción, no para
        # vincularla con el contenido: el mensaje es ilegible sin la llave del
        # coordinador, y el emisor de un voto y el de una anulación son
        # indistinguibles.
        "wallet_address": address,
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
