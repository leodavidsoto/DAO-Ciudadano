"""
Grants civiles de un solo uso (ADR-001, D-2).

Un grant es la prueba —opaca y efímera— de que un proveedor civil real
completó todas sus comprobaciones sobre una persona. Es lo único que autoriza
a insertar un commitment en el árbol de identidades.

Reglas que impone este módulo:

* **Solo un proveedor real lo emite.** Los simuladores de ClaveÚnica, NFC y
  liveness no pueden crear grants: si pudieran, cualquiera obtendría una
  credencial ZK válida sin haberse identificado, y toda la arquitectura de
  privacidad estaría protegiendo una identidad inventada.
* **Se guarda el digest, nunca el valor.** Quien lea la base de datos no puede
  canjear un grant ajeno.
* **Un solo uso, atómico.** El canje es un `find_one_and_update` condicional:
  si dos peticiones compiten, exactamente una gana.
* **Sin PII.** El grant referencia a la persona por `subject_key`, un
  identificador ciego derivado por el proveedor.

Falla cerrado: sin `IDENTITY_PROVIDER` configurado, `issue` se niega a crear
grants en producción en vez de emitir uno que no respalda ninguna verificación.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..core.config import settings
from ..core.database import get_collection

logger = logging.getLogger(__name__)

# 256 bits, como exige el contrato de API acordado con el frontend.
GRANT_BYTES = 32


class IdentityGrantError(RuntimeError):
    """El grant no existe, expiró, ya se usó o no corresponde al sujeto."""


def identity_grants_collection():
    return get_collection("identity_grants")


def digest(grant: str) -> str:
    """SHA-256 del grant. Es lo único que se persiste."""
    return hashlib.sha256(grant.encode("utf-8")).hexdigest()


def provider_is_configured() -> bool:
    return bool(settings.IDENTITY_PROVIDER.strip())


async def issue(
    subject_key: str, provider: str, browser_binding: Optional[str] = None
) -> str:
    """Emite un grant para `subject_key`. Solo lo llama un proveedor real.

    Devuelve el valor en claro una única vez: no se puede recuperar después.
    """
    if not subject_key:
        raise IdentityGrantError("Falta el identificador de sujeto.")
    if not provider:
        raise IdentityGrantError("Un grant debe declarar qué proveedor lo emitió.")
    if settings.is_production and not provider_is_configured():
        raise IdentityGrantError(
            "No hay proveedor civil configurado; no se pueden emitir grants en producción."
        )

    grant = secrets.token_urlsafe(GRANT_BYTES)
    now = datetime.now(timezone.utc)
    await identity_grants_collection().insert_one(
        {
            "digest": digest(grant),
            "subject_key": subject_key,
            "provider": provider,
            # Hash del binding de navegador que autorizó este grant. Copiar el
            # grant a otro navegador no sirve: el canje lo vuelve a exigir.
            "browser_binding": browser_binding,
            "created_at": now,
            "expires_at": now + timedelta(seconds=settings.IDENTITY_GRANT_TTL_SECONDS),
            "consumed": False,
        }
    )
    # Nunca se registra el valor del grant ni el sujeto completo.
    logger.info("Identity grant issued by %s", provider)
    return grant


async def consume(grant: str, browser_binding: Optional[str] = None) -> str:
    """Canjea el grant y devuelve su `subject_key`.

    Atómico: el filtro exige `consumed: False` y no expirado, así que dos
    peticiones simultáneas con el mismo grant producen exactamente una
    credencial.

    Si el grant se emitió ligado a un navegador, ese binding entra EN EL
    FILTRO: canjearlo desde otro navegador no encuentra documento y falla
    antes de emitir nada. Robar el grant (o el bearer de sesión) no basta.
    """
    if not grant or not isinstance(grant, str):
        raise IdentityGrantError("Falta el grant de verificación civil.")

    query = {
        "digest": digest(grant),
        "consumed": False,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    }
    stored = await identity_grants_collection().find_one({"digest": digest(grant)})
    if stored is not None and stored.get("browser_binding"):
        if not browser_binding:
            raise IdentityGrantError(
                "Falta la cookie de sesión de ClaveÚnica: este grant solo se "
                "puede canjear desde el navegador que se identificó."
            )
        query["browser_binding"] = browser_binding

    record = await identity_grants_collection().find_one_and_update(
        query,
        {"$set": {"consumed": True, "consumed_at": datetime.now(timezone.utc)}},
    )
    if not record:
        raise IdentityGrantError(
            "El grant de verificación civil no es válido, expiró o ya fue usado."
        )
    return record["subject_key"]


async def peek_subject(grant: str) -> Optional[str]:
    """Sujeto de un grant YA canjeado, para reintentos idempotentes.

    Un timeout de red puede dejar al cliente sin respuesta con el grant ya
    gastado. Sin esto, reintentar daría "grant inválido" y la persona quedaría
    sin credencial y sin forma de obtener otra.
    """
    if not grant:
        return None
    record = await identity_grants_collection().find_one({"digest": digest(grant)})
    return record["subject_key"] if record else None
