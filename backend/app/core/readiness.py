"""
Configuration readiness.

A missing production secret used to surface as a generic per-request error
with a correlation id — the operator saw "Ocurrió un error (ref: 7dae…)" on
every login while `/health` cheerfully reported "healthy". The service looked
fine to monitoring and was broken for every user.

Missing configuration is PERMANENT, not transient: no amount of retrying
fixes it. So it is reported once, loudly, at startup, reflected in `/health`,
and turned into an actionable message on the endpoints that depend on it —
instead of an opaque reference the operator cannot act on.
"""
import logging
from dataclasses import dataclass
from typing import Callable, List

from .config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Requirement:
    key: str
    feature: str          # what stops working without it
    why: str              # why it is not optional


# Secrets without which a feature CANNOT run safely. Absent them the code
# already fails closed; this only makes the failure diagnosable.
REQUIREMENTS: List[Requirement] = [
    Requirement(
        key="IDENTITY_PEPPER",
        feature="registro e inicio de sesión de ciudadanos",
        why="sin pepper el hash del RUT sería reversible por fuerza bruta (ADR 0001, D-2)",
    ),
    Requirement(
        key="PII_ENCRYPTION_KEY",
        feature="registro de ciudadanos",
        why="sin ella el RUT, el email y el nombre quedarían en texto plano (hallazgo C-4)",
    ),
    Requirement(
        key="SECRET_KEY",
        feature="sesiones de wallet",
        why="firma los tokens de sesión; con el valor por defecto cualquiera podría emitirlos",
    ),
]


def _is_configured(requirement: Requirement) -> bool:
    value = getattr(settings, requirement.key, "")
    if not value:
        return False
    # The dev default is as good as absent in production.
    if requirement.key == "SECRET_KEY" and value == "dev-secret-key":
        return False
    return True


def missing_requirements() -> List[Requirement]:
    """Required settings that are absent. Empty in development."""
    if settings.DEBUG:
        return []
    return [r for r in REQUIREMENTS if not _is_configured(r)]


def report_at_startup() -> None:
    """Log missing configuration once, in a form the operator can act on."""
    missing = missing_requirements()
    if not missing:
        logger.info("Configuration complete: all required secrets are set")
        return

    logger.error(
        "CONFIGURACIÓN INCOMPLETA — el servicio arranca pero hay funciones caídas:"
    )
    for requirement in missing:
        logger.error(
            f"  falta {requirement.key} → no funciona: {requirement.feature} "
            f"({requirement.why})"
        )
    logger.error("  Defínelas en el panel del proveedor. Ver backend/DEPLOY.md.")


def status() -> dict:
    """Configuration section for /health."""
    missing = missing_requirements()
    return {
        "ready": not missing,
        "missing": [
            {"key": r.key, "breaks": r.feature} for r in missing
        ],
    }


def require(key: str, action: str) -> None:
    """Raise a clear HTTP error when `key` is needed but absent.

    Deliberately explicit about WHICH setting is missing: this is an operator
    error, not a user error, and hiding it behind a generic message is what
    made the original failure take so long to diagnose. It leaks no secret —
    only the name of a variable that is already documented in .env.example.
    """
    from fastapi import HTTPException

    if settings.DEBUG:
        return
    requirement = next((r for r in REQUIREMENTS if r.key == key), None)
    if requirement and not _is_configured(requirement):
        raise HTTPException(
            status_code=503,
            detail=(
                f"El servicio no puede {action} porque falta configuración del "
                f"servidor ({key}). Esto es un problema de despliegue, no de tu "
                f"cuenta; el equipo debe definirla."
            ),
        )
