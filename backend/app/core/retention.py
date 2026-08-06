"""
Política de retención de datos (ROADMAP 1.4).

Cifrar la PII responde a "si alguien roba el volcado, ¿qué ve?". No responde
a la pregunta anterior: **¿por qué seguimos guardando esto?** Un dato que ya
no se necesita es riesgo puro — no aporta nada y sigue estando ahí cuando
haya una filtración.

Este módulo declara la política como datos, en un solo sitio, para que sea
auditable sin leer los routers. Cada regla dice qué se borra, cuándo y por
qué, y las que se pueden aplicar solas se convierten en índices TTL de
MongoDB (`Database.ensure_indexes`).

Dos decisiones que conviene no revertir sin pensarlo
────────────────────────────────────────────────────

1. **Los registros de ciudadanos NO se borran automáticamente.**
   `INACTIVE_USER_RETENTION_DAYS` viene en 0 (desactivado). Borrar el
   registro civil de una persona es una decisión con consecuencias legales y
   de gobernanza, no un efecto secundario de un TTL que alguien configuró un
   martes. La regla existe y el script la puede ejecutar, pero hay que
   activarla explícitamente.

2. **Lo que protege contra repetición no se purga por antigüedad.**
   `ballot_nonces` y `mint_operations` son justamente la memoria de "esto ya
   pasó". Borrarlos por viejos reabre la ventana de repetición que cierran.
"""

from dataclasses import dataclass
from typing import List, Optional

from .config import settings

SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class RetentionRule:
    collection: str
    # Campo de fecha sobre el que se mide la antigüedad.
    field: str
    # None = se conserva indefinidamente y se explica por qué en `reason`.
    ttl_seconds: Optional[int]
    reason: str
    # True: MongoDB lo aplica solo con un índice TTL.
    # False: requiere ejecutar `scripts/pii_maintenance.py purge --apply`.
    automatic: bool = True


def rules() -> List[RetentionRule]:
    """Política vigente, resuelta contra la configuración actual."""
    grant_days = max(0, settings.IDENTITY_GRANT_RETENTION_DAYS)
    inactive_days = max(0, settings.INACTIVE_USER_RETENTION_DAYS)

    return [
        RetentionRule(
            collection="siwe_nonces",
            field="created_at",
            ttl_seconds=600,
            reason=(
                "Un desafío SIWE solo sirve durante su ventana de firma; "
                "conservarlo después no aporta nada."
            ),
        ),
        RetentionRule(
            collection="oidc_login_sessions",
            field="created_at",
            ttl_seconds=max(60, settings.CLAVE_UNICA_LOGIN_TTL_SECONDS),
            reason=(
                "Un intento de login OIDC guarda el verificador PKCE y el "
                "nonce. Pasada su ventana no sirven para nada y son material "
                "sensible: se borran solos."
            ),
        ),
        RetentionRule(
            collection="identity_grants",
            field="created_at",
            ttl_seconds=grant_days * SECONDS_PER_DAY if grant_days else None,
            reason=(
                "Solo se guarda el digest, nunca el grant. Se conserva un "
                "tiempo tras expirar para poder investigar un canje anómalo, "
                "y después deja de existir."
            ),
        ),
        RetentionRule(
            collection="users",
            field="created_at",
            ttl_seconds=inactive_days * SECONDS_PER_DAY if inactive_days else None,
            reason=(
                "Registro civil de una persona. Borrarlo es una decisión de "
                "gobernanza, no un efecto secundario de un TTL: desactivado "
                "por defecto y solo vía script con --apply."
            ),
            automatic=False,
        ),
        RetentionRule(
            collection="ballot_nonces",
            field="created_at",
            ttl_seconds=None,
            reason=(
                "Es la memoria anti-repetición de las papeletas firmadas. "
                "Purgarla por antigüedad reabriría la ventana que cierra."
            ),
        ),
        RetentionRule(
            collection="mint_operations",
            field="created_at",
            ttl_seconds=None,
            reason=(
                "Idempotencia del relayer y rastro de reconciliación entre "
                "cadena y base de datos. Sin esto, un reintento vuelve a "
                "gastar gas."
            ),
        ),
        RetentionRule(
            collection="revoked_tokens",
            field="created_at",
            ttl_seconds=settings.SESSION_TOKEN_EXPIRE_SECONDS,
            reason=(
                "Un token revocado solo necesita ser recordado hasta su fecha "
                "de expiración natural."
            ),
        ),
    ]


def automatic_rules() -> List[RetentionRule]:
    """Reglas que se convierten en un índice TTL."""
    return [r for r in rules() if r.automatic and r.ttl_seconds]


def manual_rules() -> List[RetentionRule]:
    """Reglas que exigen una ejecución explícita del script."""
    return [r for r in rules() if not r.automatic and r.ttl_seconds]


def describe() -> List[dict]:
    """Política en formato serializable, para `/health/ready` y auditoría."""
    return [
        {
            "collection": r.collection,
            "field": r.field,
            "retention_days": (
                round(r.ttl_seconds / SECONDS_PER_DAY, 2) if r.ttl_seconds else None
            ),
            "enforced": (
                "ttl-index"
                if (r.automatic and r.ttl_seconds)
                else ("script" if r.ttl_seconds else "indefinite")
            ),
            "reason": r.reason,
        }
        for r in rules()
    ]
