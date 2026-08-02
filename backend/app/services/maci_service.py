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
privada: no cifra papeletas, no encola mensajes, no hay coordinador
desplegado ni prueba de tally. Ver docs/ROADMAP.md fase 3.
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
