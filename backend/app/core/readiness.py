"""
Diagnóstico de configuración requerida.

Antes de esto, si faltaba un secreto en producción (p.ej. IDENTITY_PEPPER
en Render), el usuario veía "Ocurrió un error procesando la solicitud
(ref: xxxx)" — sin ninguna pista de qué configurar. Este módulo declara
qué variables necesita cada funcionalidad, las reporta al arrancar, las
refleja en /health, y da un mensaje accionable por endpoint en vez de un
error opaco.
"""

import logging
from dataclasses import dataclass
from typing import List
from urllib.parse import urlparse

from cryptography.fernet import Fernet

from .config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Requirement:
    key: str
    feature: str
    why: str
    # Algunos requisitos solo tienen sentido en producción: en demo su ausencia
    # es legítima y el endpoint correspondiente ya falla cerrado por su cuenta.
    production_only: bool = False


REQUIREMENTS: List[Requirement] = [
    Requirement(
        key="MONGO_URL",
        feature="persistencia de producción",
        why="producción debe declarar una URI MongoDB válida y no usar el fallback local",
        production_only=True,
    ),
    Requirement(
        key="IDENTITY_PEPPER",
        feature="registro e inicio de sesión de ciudadanos",
        why="sin esto no se puede calcular el hash de identidad del RUT de forma segura (D-2)",
    ),
    Requirement(
        key="PII_ENCRYPTION_KEY",
        feature="registro de ciudadanos",
        why="sin esto no se puede cifrar el RUT/email/nombre antes de guardarlos",
    ),
    Requirement(
        key="IDENTITY_ISSUER_PRIVATE_KEY",
        feature="emisión de credenciales de identidad ZK",
        why="firma la credencial EIP-191 que el cliente verifica; sin ella no se puede emitir ninguna",
        production_only=True,
    ),
    Requirement(
        key="SECRET_KEY",
        feature="sesiones de wallet (SIWE)",
        why="firma los JWT de sesión; con el valor de desarrollo cualquiera podría falsificar una sesión",
    ),
]

_SECRET_KEY_PLACEHOLDERS = {
    "dev-secret-key",
    "change-me-in-production",
}


def requirement_is_valid(key: str) -> bool:
    """Return whether a required setting is safe enough for its feature.

    Keeping this check in one place prevents `/health/ready` from claiming
    an environment is usable while the endpoint itself accepts an insecure
    secret or crashes when it first tries to construct a Fernet cipher.
    """
    value = getattr(settings, key, "")
    if not isinstance(value, str) or not value.strip():
        return False

    if key == "MONGO_URL":
        try:
            parsed = urlparse(value.strip())
            hostname = parsed.hostname
        except ValueError:
            return False
        if parsed.scheme not in {"mongodb", "mongodb+srv"} or not hostname:
            return False
        if settings.is_production and hostname.lower() in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            return False
        return True

    if key == "SECRET_KEY":
        # The documented development placeholder is convenient only for an
        # explicitly DEBUG-enabled local instance. Everywhere else JWTs need
        # a non-public key with a minimum useful length.
        if settings.DEBUG and settings.APP_ENV in {"development", "test"}:
            return True
        return value not in _SECRET_KEY_PLACEHOLDERS and len(value) >= 32

    if key == "IDENTITY_PEPPER":
        return len(value) >= 32

    if key == "IDENTITY_ISSUER_PRIVATE_KEY":
        # Debe ser una llave Ethereum utilizable, no una cadena cualquiera:
        # si no, el primer intento de emitir falla con un error opaco.
        try:
            from eth_account import Account

            Account.from_key(value.strip())
        except Exception:
            return False
        return True

    if key == "PII_ENCRYPTION_KEY":
        try:
            Fernet(value.encode("utf-8"))
        except (TypeError, ValueError):
            return False

    return True


def _pii_key_is_usable() -> bool:
    """Hay al menos una llave de PII válida, venga de donde venga.

    Se comprueba contra `crypto.key_status()` y no solo contra
    `PII_ENCRYPTION_KEY`: desde la rotación (1.3) las llaves pueden declararse
    en `PII_ENCRYPTION_KEYS`, y un despliegue que solo use esa variable estaba
    perfectamente configurado pero se reportaba como incompleto.
    """
    from . import crypto

    return crypto.key_status()["usable"] > 0


def missing_requirements() -> List[Requirement]:
    # Los requisitos `production_only` se omiten fuera de producción: el
    # fallback local sigue siendo útil para desarrollo, pero nunca debe hacer
    # que un despliegue de producción parezca configurado.
    missing = []
    for req in REQUIREMENTS:
        if req.production_only and not settings.is_production:
            continue
        if req.key == "PII_ENCRYPTION_KEY" and _pii_key_is_usable():
            continue
        if not requirement_is_valid(req.key):
            missing.append(req)
    return missing


def deployment_blockers() -> list[str]:
    """Validate cross-setting invariants that are unsafe in production."""
    blockers: list[str] = []

    if settings.MEMBERSHIP_SOURCE == "onchain":
        # Implementado (ROADMAP 3.1), pero inútil sin cadena que consultar:
        # así configurado, cada verificación respondería 503 en vez de dejar
        # votar a nadie.
        from ..services import chain_service

        if not chain_service.can_read_chain():
            blockers.append(
                "MEMBERSHIP_SOURCE=onchain requiere SEPOLIA_RPC_URL y "
                "SBT_CONTRACT_ADDRESS válidas para consultar hasMembership()"
            )

    # SameSite=None sin Secure lo descarta el navegador: la sesión web dejaría
    # de funcionar sin ningún error visible en pantalla.
    if (
        settings.session_cookie_samesite == "none"
        and not settings.session_cookie_secure
    ):
        blockers.append("SESSION_COOKIE_SAMESITE=none exige SESSION_COOKIE_SECURE=true")

    if not settings.is_production:
        return blockers

    if settings.DEBUG:
        blockers.append("DEBUG debe ser false en producción")
    cors_origins = settings.cors_origins_list
    if not cors_origins or "*" in cors_origins:
        blockers.append("CORS_ORIGINS debe listar orígenes exactos en producción")
    else:
        invalid_origins = []
        for origin in cors_origins:
            parsed_origin = urlparse(origin)
            if (
                parsed_origin.scheme != "https"
                or not parsed_origin.netloc
                or parsed_origin.path not in {"", "/"}
                or parsed_origin.params
                or parsed_origin.query
                or parsed_origin.fragment
            ):
                invalid_origins.append(origin)
        if invalid_origins:
            blockers.append(
                "CORS_ORIGINS debe contener solo orígenes HTTPS exactos, sin rutas"
            )
    if settings.CORS_ORIGIN_REGEX.strip():
        blockers.append(
            "CORS_ORIGIN_REGEX debe quedar vacío en producción; usa orígenes exactos"
        )
    if not settings.SIGNED_BALLOTS_REQUIRED:
        blockers.append("SIGNED_BALLOTS_REQUIRED debe ser true en producción")
    if settings.ENABLE_METRICS and not settings.METRICS_TOKEN.strip():
        # Un /metrics abierto publica el inventario de rutas, el volumen de
        # tráfico y las latencias de toda la API a quien lo pida.
        blockers.append(
            "ENABLE_METRICS=true exige METRICS_TOKEN en producción: /metrics "
            "no puede quedar público"
        )
    if not settings.session_cookie_secure:
        blockers.append(
            "SESSION_COOKIE_SECURE debe ser true en producción: sin él la "
            "cookie de sesión viaja en claro"
        )
    # El recuento dejó de ser un bloqueante incondicional (ROADMAP 3.10):
    # los totales se derivan de las papeletas al leerlos, votar es UNA
    # escritura de un documento, la finalización de elecciones se reconcilia
    # hasta dejar su marca `finalized_at`, y `/audit` recomputa el resultado
    # verificando cada firma. Lo que sí sigue bloqueando es publicar un
    # resultado que nadie puede verificar criptográficamente: sin firmas
    # obligatorias, la auditoría solo puede decir "esto es lo que hay
    # guardado", y eso ya lo cubre el bloqueante de SIGNED_BALLOTS_REQUIRED.
    if settings.MEMBERSHIP_SOURCE == "mongo":
        blockers.append(
            "MEMBERSHIP_SOURCE=mongo sigue provisional hasta reconciliar "
            "membresías verificadas y ratificar la fuente de verdad"
        )

    blockers.extend(siwe_configuration_blockers())
    # Se llega aquí solo en producción: la comprobación de is_production está
    # más arriba en esta misma función.
    blockers.extend(_service_blockers())

    return blockers


def _service_blockers() -> list[str]:
    """Servicios añadidos después de la primera pasada de readiness.

    Sin esto, un despliegue reportaba `ready` mientras la emisión de
    credenciales, el patrocinio de gas o el límite compartido no funcionaban
    — justo el tipo de "listo" que no significa nada.
    """
    from . import config as _config  # evita import circular en tiempo de módulo

    blockers: list[str] = []

    # Proveedor civil: sin él la emisión de credenciales falla cerrada, así que
    # el flujo de alta completo no existe.
    provider = settings.IDENTITY_PROVIDER.strip()
    if not provider:
        blockers.append(
            "IDENTITY_PROVIDER no está configurado: no se pueden emitir grants "
            "civiles y el alta de nuevos ciudadanos queda bloqueada"
        )
    elif provider != "clave-unica":
        # El único proveedor civil real implementado. Un valor distinto
        # significa que algo emite grants sin haber verificado identidad, o
        # que alguien dejó un nombre de sandbox en producción.
        blockers.append(
            f"IDENTITY_PROVIDER='{provider}' no corresponde a ningún proveedor "
            "civil implementado; el único es 'clave-unica'"
        )
    else:
        from ..services import clave_unica as _clave_unica

        missing = _clave_unica.configuration_errors()
        if missing:
            blockers.append(
                "ClaveÚnica está declarada como proveedor pero su configuración "
                "está incompleta: " + ", ".join(sorted(missing))
            )

    # Rate limiter: con varios workers y sin Redis el límite efectivo se
    # multiplica por el número de instancias (ROADMAP 3.8).
    if not settings.REDIS_URL.strip():
        blockers.append(
            "REDIS_URL no está configurada: el rate limiter y el antifraude "
            "cuentan por proceso, así que con más de una instancia el límite "
            "efectivo se multiplica"
        )

    # Contrato de membresía: hace falta para leer scope y aprobar raíces.
    if not settings.SBT_CONTRACT_ADDRESS.strip():
        blockers.append(
            "SBT_CONTRACT_ADDRESS no está configurada: no se puede leer "
            "membershipScope() ni aprobar raíces de identidad"
        )

    return blockers


def feature_status() -> dict:
    """Qué funcionalidades están realmente operativas.

    Un booleano `ready` no le dice a un operador QUÉ puede hacer el
    despliegue. Esto sí, y sin adornos: cada entrada refleja configuración
    real, no intención.
    """
    from ..services import (
        chain_service,
        clave_unica,
        paymaster_service,
        treasury_service,
    )
    from . import crypto, retention

    erc4337 = paymaster_service.status()
    keys = crypto.key_status()
    return {
        "pii_protection": {
            # Huellas, nunca las llaves: este objeto va a /health/ready.
            "keys_usable": keys["usable"],
            "primary_key": keys["primary"],
            "rotation_in_progress": keys["rotation_in_progress"],
            "pepper_rotation_in_progress": bool(
                settings.IDENTITY_PEPPER_PREVIOUS.strip()
            ),
            # Custodia: honestidad explícita. Las llaves viven en variables de
            # entorno, no en un KMS; la rotación existe, la custodia no.
            "key_custody": "environment",
            "retention_policy": retention.describe(),
        },
        "treasury": {
            # Configuración, no sonda: el health check no debe golpear el RPC
            # ni la API de precios en cada llamada.
            "available": treasury_service.is_configured(),
            "missing": sorted(treasury_service.configuration_errors()),
            "price_provider": settings.ETH_PRICE_PROVIDER.strip() or "none",
        },
        "membership_verification": {
            "source": settings.MEMBERSHIP_SOURCE,
            # Solo comprueba configuración: no se golpea el RPC en cada
            # health check. La sonda real vive en `minting.onchain.runtime`.
            "available": (
                settings.MEMBERSHIP_SOURCE == "mongo" or chain_service.can_read_chain()
            ),
            "cache_ttl_seconds": settings.MEMBERSHIP_CACHE_TTL_SECONDS,
        },
        "clave_unica": {
            # Configuración, no sonda: /health/ready no debe golpear al
            # proveedor del Estado en cada llamada.
            "available": clave_unica.is_configured(),
            "missing": sorted(clave_unica.configuration_errors()),
            "id_token_algorithm": settings.CLAVE_UNICA_ID_TOKEN_ALG.strip().upper(),
        },
        "identity_issuance": {
            "available": bool(
                settings.IDENTITY_ISSUER_PRIVATE_KEY.strip()
                and settings.IDENTITY_PROVIDER.strip()
            ),
            "issuer_configured": bool(settings.IDENTITY_ISSUER_PRIVATE_KEY.strip()),
            "civil_provider": settings.IDENTITY_PROVIDER.strip() or None,
        },
        "sponsored_minting": {
            # Habilitado no significa probado: la sonda del bundler vive en
            # /health/ready bajo `erc4337`.
            "available": erc4337["enabled"],
            "custodial": False,
            "missing": erc4337["missing"],
        },
        "shared_rate_limiting": {
            "available": bool(settings.REDIS_URL.strip()),
        },
        "maci": {
            # El registro de llaves funciona siempre; la votación privada no.
            "key_registry": True,
            "coordinator_configured": bool(settings.MACI_COORDINATOR_ADDRESS.strip()),
            "private_voting": False,
            "why": (
                "falta el circuito de tally con ceremonia multiparte y el "
                "anclaje verificable entre propuesta y poll"
            ),
        },
    }


def siwe_configuration_blockers() -> list[str]:
    """Return production-only EIP-4361 configuration errors.

    This helper is shared by readiness and the wallet endpoints: a red health
    check must not be the only thing preventing a mis-bound SIWE session.
    """
    if not settings.is_production:
        return []

    blockers: list[str] = []
    parsed_siwe_uri = urlparse(settings.SIWE_URI)
    if (
        not settings.SIWE_DOMAIN
        or settings.SIWE_DOMAIN in {"localhost", "dao-ciudadana"}
        or "://" in settings.SIWE_DOMAIN
    ):
        blockers.append("SIWE_DOMAIN debe ser el dominio público exacto")
    if (
        parsed_siwe_uri.scheme != "https"
        or parsed_siwe_uri.hostname != settings.SIWE_DOMAIN
    ):
        blockers.append("SIWE_URI debe ser HTTPS y coincidir con SIWE_DOMAIN")
    if settings.SIWE_CHAIN_ID != 11155111:
        blockers.append("SIWE_CHAIN_ID debe ser 11155111 mientras la red sea Sepolia")

    return blockers


def require_siwe_configuration() -> None:
    """Fail closed inside challenge/verify, not only in `/health/ready`."""
    from fastapi import HTTPException

    blockers = siwe_configuration_blockers()
    if blockers:
        raise HTTPException(
            status_code=503,
            detail="La sesión SIWE no está disponible: " + "; ".join(blockers),
        )


def report_at_startup() -> None:
    missing = missing_requirements()
    minting = minting_status()
    config_blockers = deployment_blockers()
    logger.info(
        "readiness: APP_ENV=%s MINT_MODE=%s",
        settings.APP_ENV,
        settings.MINT_MODE,
    )
    for req in missing:
        logger.warning(
            "readiness: falta o es inválida %s -> %s no va a funcionar (%s)",
            req.key,
            req.feature,
            req.why,
        )
    for blocker in minting["blockers"]:
        logger.warning("readiness: minteo bloqueado -> %s", blocker)
    for blocker in config_blockers:
        logger.warning("readiness: configuración bloqueada -> %s", blocker)
    if not missing and minting["available"] and not config_blockers:
        logger.info("readiness: el entorno seleccionado está listo")


def onchain_minting_status(runtime: dict | None = None) -> dict:
    """Report static config and the optional read-only chain probe."""
    from ..services import chain_service

    errors = chain_service.configuration_errors()
    missing_keys = [key for key, reason in errors.items() if reason == "falta"]
    invalid = {key: reason for key, reason in errors.items() if reason != "falta"}
    return {
        "configured": not errors,
        "missing": missing_keys,
        "invalid": invalid,
        "runtime": runtime,
    }


def minting_status(onchain_runtime: dict | None = None) -> dict:
    """Operational state of the explicitly selected membership mode.

    Production is deliberately unavailable until the API consumes a
    server-issued verification grant. This prevents SIWE (wallet ownership)
    from being confused with verified civil identity.
    """
    onchain = onchain_minting_status(onchain_runtime)
    blockers = []

    if settings.MINT_MODE == "disabled":
        blockers.append("MINT_MODE=disabled")
    elif settings.MINT_MODE == "demo" and settings.is_production:
        blockers.append("MINT_MODE=demo no está permitido con APP_ENV=production")
    elif settings.MINT_MODE == "onchain":
        if not onchain["configured"]:
            invalid_keys = list(onchain["invalid"])
            affected = onchain["missing"] + invalid_keys
            blockers.append(
                "configuración on-chain ausente o inválida: " + ", ".join(affected)
            )
        elif not onchain_runtime:
            blockers.append("validación operativa on-chain pendiente")
        elif not onchain_runtime.get("ready"):
            blockers.extend(
                onchain_runtime.get("errors")
                or ["la validación operativa on-chain falló"]
            )

    if settings.is_production:
        blockers.append(
            "el minteo aún no consume una verificación de identidad de un solo uso"
        )

    return {
        "mode": settings.MINT_MODE,
        "available": not blockers,
        "blockers": blockers,
        "onchain": onchain,
    }


def status(onchain_runtime: dict | None = None) -> dict:
    missing = missing_requirements()
    minting = minting_status(onchain_runtime)
    config_blockers = deployment_blockers()
    ready = not missing and minting["available"] and not config_blockers
    return {
        "environment": settings.APP_ENV,
        "ready": ready,
        "production_ready": settings.is_production and ready,
        "missing": [
            {"key": r.key, "feature": r.feature, "why": r.why} for r in missing
        ],
        "blockers": config_blockers,
        "minting": minting,
        "features": feature_status(),
        # Backwards-compatible field for existing monitors.
        "onchain_minting": minting["onchain"],
    }


def require(key: str, action: str) -> None:
    """Lanza HTTPException 503 si `key` está ausente o es inseguro/inválido.

    Import local de HTTPException para no forzar una dependencia de
    FastAPI en módulos que solo quieran leer `status()`.
    """
    from fastapi import HTTPException

    req = next((r for r in REQUIREMENTS if r.key == key), None)
    if requirement_is_valid(key):
        return

    feature = req.feature if req else action
    raise HTTPException(
        status_code=503,
        detail=(
            f"No se puede {action} todavía: {key} falta o no es válida en el "
            f"servidor (necesario para {feature}). Contacta al administrador."
        ),
    )
