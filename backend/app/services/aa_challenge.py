"""
Desafíos de Autenticación Activa: aleatorios, del servidor y de un solo uso.

Por qué el desafío NO lo elige el teléfono
------------------------------------------
Toda la garantía de la Autenticación Activa está en que el chip firme algo que
no pudo conocer de antemano. Si el desafío lo eligiera el cliente, quien
capturó unos bytes de una lectura ajena capturaría también la firma que los
acompaña, y podría reenviar el par entero: el servidor comprobaría una firma
correcta sobre un desafío correcto y no habría cerrado nada. El anti-replay no
lo da la firma, lo da que el desafío sea nuestro y no se repita.

De ahí las tres propiedades que impone este módulo, y ninguna sobra:

* **Aleatorio del servidor** — 8 bytes de `secrets`, el tamaño que ICAO 9303-11
  §6.1 fija para el campo de datos de INTERNAL AUTHENTICATE.
* **De un solo uso** — el consumo es un `find_one_and_update` condicional sobre
  el estado. Si dos peticiones llegan con el mismo desafío, exactamente una
  gana; la otra ve un desafío ya quemado. La atomicidad la da Mongo, no una
  comprobación previa en Python que otra petición podría adelantar.
* **De vida corta** — entre pedir el desafío y apoyar la cédula pasan segundos.
  Una ventana larga solo amplía el rato durante el cual una firma capturada
  sigue sirviendo.

Se guarda en claro, a diferencia de `identity_grant`
----------------------------------------------------
El desafío no es un secreto: viaja al cliente, y de ahí al chip, en claro. Su
valor no está en que nadie lo conozca sino en que nadie pudiera predecirlo y en
que solo valga una vez. Guardar un digest en vez del valor no protegería nada y
haría imposible verificar la firma, que es exactamente sobre esos bytes.

Qué NO es un desafío consumido
------------------------------
Quemar el desafío no es "el alta ya se hizo". Un intento fallido gasta el
desafío y la app tiene que pedir otro: es barato, no cuesta una verificación
civil, y el fallo cerrado va en la dirección correcta. Es lo contrario del
grant de membresía, donde perder el token por un timeout de red obligaría a
repetir todo el flujo y por eso el consumo tiene dos fases.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..core.config import settings
from ..core.database import get_collection

logger = logging.getLogger(__name__)

#: 8 bytes: lo que el chip espera en INTERNAL AUTHENTICATE (ICAO 9303-11 §6.1).
CHALLENGE_BYTES = 8

PENDING = "pending"
CONSUMED = "consumed"


class ActiveAuthChallengeError(RuntimeError):
    """El desafío no existe, expiró o ya se usó."""


def aa_challenges_collection():
    """Ledger de desafíos. Es lo que hace que cada uno valga una sola vez."""
    return get_collection("cedula_aa_challenges")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value) -> Optional[datetime]:
    """Normaliza una fecha de Mongo a UTC con zona.

    El driver devuelve datetimes sin `tzinfo`; compararlas con `now(utc)`
    revienta. No es un detalle de los tests: pasaría igual en producción.
    """
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def ttl_seconds() -> int:
    return max(30, settings.CEDULA_AA_CHALLENGE_TTL_SECONDS)


@dataclass(frozen=True)
class IssuedChallenge:
    #: Referencia opaca que el cliente devuelve. El desafío en sí no vuelve a
    #: entrar por la API: lo recuerda el servidor, así que el cliente no puede
    #: sustituirlo por uno que ya tenga firmado.
    challenge_id: str
    challenge: bytes
    expires_at: datetime


async def issue() -> IssuedChallenge:
    """Emite un desafío nuevo y lo deja anotado como pendiente."""
    now = _now()
    issued = IssuedChallenge(
        challenge_id=secrets.token_hex(16),
        challenge=secrets.token_bytes(CHALLENGE_BYTES),
        expires_at=now + timedelta(seconds=ttl_seconds()),
    )
    await aa_challenges_collection().insert_one(
        {
            "challenge_id": issued.challenge_id,
            "challenge": issued.challenge,
            "status": PENDING,
            "created_at": now,
            "expires_at": issued.expires_at,
        }
    )
    # Ni el identificador ni el desafío entran en el log: juntos son la mitad
    # de una sesión de Autenticación Activa.
    logger.info("Desafío de Autenticación Activa emitido (TTL %ss)", ttl_seconds())
    return issued


async def consume(challenge_id: str) -> bytes:
    """Quema el desafío y devuelve sus bytes. Segunda vez: `ActiveAuthChallengeError`.

    El cambio de estado y la lectura son la MISMA operación. Comprobar primero
    y actualizar después dejaría una ventana en la que dos peticiones con la
    misma captura leerían las dos un desafío pendiente — que es justo el ataque
    que este módulo cierra.
    """
    if not challenge_id or not isinstance(challenge_id, str):
        raise ActiveAuthChallengeError(
            "Falta el identificador del desafío de Autenticación Activa."
        )

    document = await aa_challenges_collection().find_one_and_update(
        {"challenge_id": challenge_id, "status": PENDING},
        {"$set": {"status": CONSUMED, "consumed_at": _now()}},
    )
    if document is None:
        # Un desafío desconocido y uno ya quemado se responden igual: decir
        # cuál de los dos es le confirmaría a quien reenvía una captura que el
        # identificador era bueno.
        raise ActiveAuthChallengeError(
            "El desafío de Autenticación Activa no existe o ya se usó. Pide uno "
            "nuevo y vuelve a leer la cédula."
        )

    expires_at = _as_utc(document.get("expires_at"))
    if expires_at is None or expires_at <= _now():
        raise ActiveAuthChallengeError(
            "El desafío de Autenticación Activa expiró. Pide uno nuevo y vuelve "
            "a leer la cédula."
        )

    challenge = document.get("challenge")
    if isinstance(challenge, bytes):
        raw = challenge
    elif isinstance(challenge, (bytearray, memoryview)):
        raw = bytes(challenge)
    else:
        # `Binary` de PyMongo es subclase de bytes, así que llegar aquí
        # significa que la fila está corrupta. No se reconstruye a ojo.
        raise ActiveAuthChallengeError(
            "El desafío de Autenticación Activa almacenado no es utilizable."
        )
    if len(raw) != CHALLENGE_BYTES:
        raise ActiveAuthChallengeError(
            "El desafío de Autenticación Activa almacenado no es utilizable."
        )
    return raw
