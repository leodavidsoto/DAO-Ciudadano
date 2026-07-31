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

from .config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Requirement:
    key: str
    feature: str
    why: str


REQUIREMENTS: List[Requirement] = [
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
        key="SECRET_KEY",
        feature="sesiones de wallet (SIWE)",
        why="firma los JWT de sesión; con el valor de desarrollo cualquiera podría falsificar una sesión",
    ),
]

_DEV_DEFAULTS = {"SECRET_KEY": "dev-secret-key"}


def missing_requirements() -> List[Requirement]:
    missing = []
    for req in REQUIREMENTS:
        value = getattr(settings, req.key, "")
        if not value:
            missing.append(req)
        elif req.key in _DEV_DEFAULTS and value == _DEV_DEFAULTS[req.key] and not settings.DEBUG:
            missing.append(req)
    return missing


def report_at_startup() -> None:
    missing = missing_requirements()
    if not missing:
        logger.info("readiness: toda la configuración requerida está presente")
        return
    for req in missing:
        logger.warning(
            "readiness: falta %s -> %s no va a funcionar (%s)",
            req.key, req.feature, req.why,
        )


def onchain_minting_status() -> dict:
    """Informational only — NO fail-closed. A missing RPC/contrato/llave de
    minter no bloquea el registro de miembros: mint_sbt cae a modo demo
    (off-chain, tx_hash=None, ver blockchain_service.py). Esto solo reporta
    si el minteo REAL está configurado, para que /health no mienta diciendo
    que hay blockchain cuando en realidad es un mock.
    """
    keys = ("SEPOLIA_RPC_URL", "SBT_CONTRACT_ADDRESS", "MINTER_PRIVATE_KEY")
    missing_keys = [k for k in keys if not getattr(settings, k, "")]
    return {"configured": not missing_keys, "missing": missing_keys}


def status() -> dict:
    missing = missing_requirements()
    return {
        "ready": len(missing) == 0,
        "missing": [
            {"key": r.key, "feature": r.feature, "why": r.why} for r in missing
        ],
        "onchain_minting": onchain_minting_status(),
    }


def require(key: str, action: str) -> None:
    """Lanza HTTPException 503 accionable si `key` no está configurado.

    Import local de HTTPException para no forzar una dependencia de
    FastAPI en módulos que solo quieran leer `status()`.
    """
    from fastapi import HTTPException

    req = next((r for r in REQUIREMENTS if r.key == key), None)
    value = getattr(settings, key, "")
    is_dev_default = key in _DEV_DEFAULTS and value == _DEV_DEFAULTS[key] and not settings.DEBUG
    if value and not is_dev_default:
        return

    feature = req.feature if req else action
    raise HTTPException(
        status_code=503,
        detail=(
            f"No se puede {action} todavía: falta configurar {key} en el "
            f"servidor (necesario para {feature}). Contacta al administrador."
        ),
    )
