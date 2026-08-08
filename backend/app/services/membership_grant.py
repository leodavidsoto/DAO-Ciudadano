"""
Grant de membresía: el JWT que autoriza un alta (ROADMAP 1.10, AUDIT P-4).

El problema que cierra: `POST /membership/mint` recibía `assurance_level` y
`doc_hash` del propio cliente. Una sesión SIWE prueba control de una wallet,
no que la persona detrás completó ninguna verificación civil, así que
cualquiera podía darse de alta declarándose "AL2" con el hash de documento que
quisiera. El nivel de aseguramiento lo afirmaba quien pedía la membresía.

A partir de aquí el nivel lo afirma **el servidor**, en un token que él mismo
firmó al terminar un flujo civil real (ClaveÚnica OIDC o Autenticación Pasiva
de la cédula). El cliente ya no lo elige: lo transporta.

Por qué un JWT y no el grant opaco de `identity_grant.py`: aquel es un puntero
a una fila de Mongo y solo dice "hubo una verificación"; su contenido —quién y
con qué nivel— vive en el servidor. Este viaja firmado con lo que el minteo
necesita saber (sujeto y nivel), de modo que el alta no depende de una segunda
lectura y el cliente puede mostrar el nivel alcanzado sin preguntarlo. Son
complementarios y NO intercambiables: el opaco se canjea por una credencial
ZK, este por una membresía.

Sobre PII: `sub` es el `subject_key` —índice ciego del RUN, derivado con el
pepper del servidor—, nunca el RUN. El token no lleva nombre, correo ni
documento; quien lo intercepte no aprende quién es la persona.

=== Un solo uso, sin perder la identidad en un fallo transitorio ============

"Quemar el jti al recibirlo" y "poder reintentar si la cadena falló" se
contradicen si el quemado es un único paso: un timeout de RPC dejaría a la
persona verificada, sin membresía y sin token con el que volver a intentarlo.
Tendría que repetir todo el flujo civil por un problema de red del servidor.

Por eso el consumo tiene dos fases y el jti se persiste en la PRIMERA:

* ``claimed``  — el jti ya existe en Mongo, atado a esta wallet. Nadie más
                 puede usar el token, y tampoco sirve para otra dirección.
                 Un reintento de ESA misma wallet sí lo vuelve a tomar,
                 mientras el JWT no haya expirado.
* ``consumed`` — hay membresía. Estado terminal: ni esa wallet ni ninguna otra
                 vuelven a usar este token.

Es decir: es de un solo uso para todo lo que importa —una identidad, una
membresía—, y a la vez un fallo de red no cuesta una verificación civil.

Y una identidad no se muda de wallet: si el sujeto ya tiene una membresía
emitida, un token nuevo del mismo flujo no da una segunda para otra dirección.
"""

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from pymongo.errors import DuplicateKeyError

from ..core.config import settings
from ..core.database import get_collection

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"

#: `iss`/`aud` fijan para qué sirve este token. Sin `aud` propio, un JWT de
#: sesión SIWE —firmado con la misma llave— se aceptaría como grant de
#: identidad: el atacante ya controla una wallet, así que se autoafirmaría el
#: nivel de aseguramiento otra vez, justo lo que este módulo elimina.
ISSUER = "dao-ciudadana-identity"
AUDIENCE = "dao-membership-mint"

CLAIMED = "claimed"
CONSUMED = "consumed"


class MembershipGrantError(RuntimeError):
    """El grant no es válido, expiró, ya se usó o no corresponde a esta wallet."""


def membership_grants_collection():
    """Ledger de jtis. Es lo que hace que el token sea de un solo uso."""
    return get_collection("membership_grants")


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


# === Emisión ==================================================================


def provider_is_configured() -> bool:
    return bool(settings.IDENTITY_PROVIDER.strip())


def issue(subject_key: str, assurance_level: str, provider: str) -> str:
    """Firma un grant de membresía. Solo lo llama un proveedor civil real.

    Falla cerrado en producción sin `IDENTITY_PROVIDER`: emitir un grant que
    no respalda ninguna verificación es peor que no emitir ninguno — le daría
    al minteo exactamente la garantía falsa que este módulo viene a quitar.
    """
    if not subject_key:
        raise MembershipGrantError("Falta el identificador de sujeto.")
    if not assurance_level:
        raise MembershipGrantError("Un grant debe declarar el nivel alcanzado.")
    if not provider:
        raise MembershipGrantError("Un grant debe declarar qué proveedor lo emitió.")
    if settings.is_production and not provider_is_configured():
        raise MembershipGrantError(
            "No hay proveedor civil configurado; no se pueden emitir grants de "
            "membresía en producción."
        )
    if not settings.SECRET_KEY.strip():
        raise MembershipGrantError("SECRET_KEY no está configurada.")

    now = _now()
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": subject_key,
        "lvl": assurance_level,
        "prv": provider,
        "iat": now,
        "exp": now + timedelta(seconds=settings.MEMBERSHIP_GRANT_TTL_SECONDS),
        "jti": secrets.token_hex(16),
    }
    # Nunca se registra el token ni el sujeto: el log diría quién se identificó.
    logger.info("Membership grant issued by %s (%s)", provider, assurance_level)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


# === Verificación =============================================================


@dataclass(frozen=True)
class GrantClaims:
    """Lo que el servidor certificó. El cliente no aporta nada de esto."""

    jti: str
    subject_key: str
    assurance_level: str
    provider: str
    expires_at: datetime


def verify(token: str) -> GrantClaims:
    """Valida firma, vigencia, emisor y audiencia. No consume nada."""
    if not token or not isinstance(token, str):
        raise MembershipGrantError(
            "Falta el grant de identidad: primero verifica tu identidad."
        )
    if not settings.SECRET_KEY.strip():
        raise MembershipGrantError("SECRET_KEY no está configurada.")

    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            # `sub`/`jti` no están en `require` porque PyJWT no valida su
            # presencia; se comprueban abajo con un mensaje propio.
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise MembershipGrantError(
            "Tu verificación de identidad expiró. Vuelve a identificarte."
        ) from exc
    except jwt.PyJWTError as exc:
        raise MembershipGrantError(
            "El grant de identidad no es válido para el alta de membresías."
        ) from exc

    jti = payload.get("jti")
    subject_key = payload.get("sub")
    assurance_level = payload.get("lvl")
    provider = payload.get("prv")
    if not jti or not subject_key or not assurance_level or not provider:
        # Un token bien firmado pero incompleto no puede acreditar un nivel.
        raise MembershipGrantError(
            "El grant de identidad está incompleto: no acredita un nivel de "
            "verificación."
        )

    return GrantClaims(
        jti=jti,
        subject_key=subject_key,
        assurance_level=assurance_level,
        provider=provider,
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    )


# === Consumo en dos fases =====================================================


@dataclass(frozen=True)
class ClaimResult:
    """Resultado de reclamar el grant. `retry` distingue el primer intento."""

    claims: GrantClaims
    retry: bool


async def claim(claims: GrantClaims, wallet_address: str) -> ClaimResult:
    """Reclama el grant para `wallet_address`, o explica por qué no se puede.

    Persiste el jti (esto es el "quemado": a partir de aquí el token no sirve
    para nadie más) pero deja la operación reintentable por esta misma wallet
    hasta que `finalize` la cierre.

    Atómico por el índice único sobre `jti`: dos peticiones simultáneas con el
    mismo token no crean dos reclamos. Que dos reintentos de la misma wallet
    pasen a la vez es inofensivo — el índice único de `members` deja una sola
    membresía.
    """
    address = wallet_address.lower()

    await _reject_if_subject_already_has_membership(claims.subject_key, address)

    try:
        await membership_grants_collection().insert_one(
            {
                "jti": claims.jti,
                "subject_key": claims.subject_key,
                "wallet_address": address,
                "assurance_level": claims.assurance_level,
                "provider": claims.provider,
                "status": CLAIMED,
                "attempts": 1,
                "created_at": _now(),
                # Se conserva para que el barrido de retención sepa cuándo el
                # token dejó de poder usarse.
                "grant_expires_at": claims.expires_at,
            }
        )
        return ClaimResult(claims=claims, retry=False)
    except DuplicateKeyError:
        pass

    existing = await membership_grants_collection().find_one({"jti": claims.jti})
    if existing is None:
        # Insert duplicado pero el documento no está: otra petición lo borró
        # entre medio. No se adivina.
        raise MembershipGrantError(
            "No se pudo reservar tu verificación de identidad. Reintenta."
        )

    if existing.get("status") == CONSUMED:
        raise MembershipGrantError(
            "Esta verificación de identidad ya se usó para crear una membresía."
        )

    if existing.get("wallet_address") != address:
        # El token está reservado por otra dirección. Aceptarlo aquí
        # convertiría un grant robado en una membresía para el ladrón.
        raise MembershipGrantError(
            "Esta verificación de identidad está reservada para otra wallet."
        )

    # Reintento legítimo de la misma wallet tras un fallo transitorio.
    claimed = await membership_grants_collection().update_one(
        {"jti": claims.jti, "status": CLAIMED, "wallet_address": address},
        {"$inc": {"attempts": 1}, "$set": {"retried_at": _now()}},
    )
    if claimed.matched_count == 0:
        # Se consumió en la carrera: ya hay membresía por este token.
        raise MembershipGrantError(
            "Esta verificación de identidad ya se usó para crear una membresía."
        )
    return ClaimResult(claims=claims, retry=True)


async def _reject_if_subject_already_has_membership(
    subject_key: str, wallet_address: str
) -> None:
    """Una identidad, una membresía — aunque el proveedor emita otro grant.

    Identificarse dos veces con ClaveÚnica produce dos jtis distintos. Sin
    esta comprobación, la misma persona podría darse de alta con tantas
    wallets como veces se identificara, y la DAO tendría un censo inflado con
    identidades todas ellas "verificadas".
    """
    other = await membership_grants_collection().find_one(
        {
            "subject_key": subject_key,
            "status": CONSUMED,
            "wallet_address": {"$ne": wallet_address},
        }
    )
    if other is not None:
        raise MembershipGrantError(
            "Esta identidad ya tiene una membresía asociada a otra wallet."
        )


async def finalize(jti: str, token_id: Optional[int] = None) -> None:
    """Cierra el grant: hay membresía. Estado terminal, nadie lo reabre."""
    await membership_grants_collection().update_one(
        {"jti": jti, "status": CLAIMED},
        {
            "$set": {
                "status": CONSUMED,
                "token_id": token_id,
                "consumed_at": _now(),
            },
            "$unset": {"last_error": ""},
        },
    )


async def release(jti: str, error: str) -> None:
    """El intento falló sin efecto. Deja constancia y NO consume el grant.

    Es lo que permite reintentar sin repetir el flujo civil: el jti sigue
    reservado para esta wallet, y el JWT sigue sirviendo mientras no expire.
    """
    await membership_grants_collection().update_one(
        {"jti": jti, "status": CLAIMED},
        {"$set": {"last_error": error, "failed_at": _now()}},
    )
