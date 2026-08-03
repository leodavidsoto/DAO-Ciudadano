"""
Shared FastAPI dependencies for governance routers.

Membership gating (closes audit finding C-3): every mutating governance
action — creating proposals, voting, delegating, running for election and
voting in elections — requires the acting address to be an ACTIVE member.

The check itself lives behind the MembershipVerifier interface
(app/services/membership_verifier.py) so switching between MongoDB and the
on-chain hasMembership() call (ROADMAP 3.1) is configuration, not code.
Cuando la fuente es la cadena y esta no responde, la respuesta es 503: un 403
afirmaría que la persona no es miembro, y eso no es lo que se sabe.

Wallet auth (closes audit finding C-1): `current_address` extrae la
dirección autenticada del JWT de sesión (emitido tras verificar SIWE, ver
services/siwe_service.py). `ensure_acts_as_self` compara esa dirección
contra la que el request dice controlar -- sin esto, cualquiera podía
poner el wallet_address de otra persona en el body y actuar como ella.

El JWT puede llegar como `Authorization: Bearer` (app móvil) o en la cookie
HttpOnly de sesión (web, tarea 1.13). Por cookie se exige además el doble
envío CSRF en los métodos con efectos; ver core/session.py.
"""
from fastapi import HTTPException, Header, Request
from typing import Optional

from ..core import readiness, session
from ..services.membership_verifier import (
    MembershipVerificationUnavailable,
    get_membership_verifier,
)
from ..services import siwe_service


# Un solo texto para las dos rutas por las que puede salir: el gate directo y
# el cálculo de peso por delegación. Deben responder lo mismo.
MEMBERSHIP_UNAVAILABLE_DETAIL = (
    "No se pudo verificar la membresía on-chain en este momento. "
    "Es un problema del servicio, no de tu credencial: intenta de "
    "nuevo en unos minutos."
)


async def is_active_member(address: str) -> bool:
    """True/False según la fuente configurada. 503 si no se pudo consultar."""
    verifier = get_membership_verifier()
    try:
        return await verifier.is_member(address)
    except MembershipVerificationUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=MEMBERSHIP_UNAVAILABLE_DETAIL,
        ) from exc


async def ensure_active_member(address: str, action: str) -> None:
    """Raise 403 (Spanish, user-facing) if `address` is not an active member.

    `action` is the verb phrase for the error message, e.g. "votar".
    """
    if not await is_active_member(address):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Solo los miembros activos de la DAO pueden {action}. "
                f"La dirección {address} no tiene una membresía activa."
            ),
        )


async def current_address(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> str:
    """Dirección (lowercase) autenticada vía el JWT de sesión.

    Acepta `Authorization: Bearer <token>` o la cookie HttpOnly de sesión.
    401 si no hay ninguno, o si el token es inválido o expiró.
    """
    token, source = session.token_from_request(request, authorization)
    if not token:
        raise HTTPException(
            status_code=401,
            detail=(
                "Falta iniciar sesión con tu wallet (cookie de sesión o "
                "encabezado Authorization: Bearer <token>)."
            ),
        )
    # Never decode a caller-controlled JWT with an absent, public or weak
    # signing key. A deployment with unsafe auth configuration fails closed
    # even if an attacker already knows the repository's development key.
    readiness.require("SECRET_KEY", "validar la sesión de wallet")
    readiness.require_siwe_configuration()
    address = siwe_service.read_token(token)
    if not address:
        raise HTTPException(
            status_code=401,
            detail="Tu sesión no es válida o expiró. Vuelve a iniciar sesión con tu wallet.",
        )
    if source == "cookie":
        # Se comprueba DESPUÉS de validar el token para no dar una pista de
        # validez a quien solo prueba tokens, y solo en sesiones por cookie:
        # son las únicas que el navegador adjunta por su cuenta.
        session.verify_csrf(request, token)
    return address


def ensure_acts_as_self(claimed_address: str, authenticated_address: str, action: str) -> None:
    """403 si `claimed_address` (el que viene en el body) no es quien firmó la sesión.

    Evita que Alice actúe "como" Bob solo por escribir su dirección en el
    JSON -- la única dirección que cuenta es la que efectivamente firmó.
    """
    if claimed_address.lower() != authenticated_address.lower():
        raise HTTPException(
            status_code=403,
            detail=(
                f"No puedes {action} en nombre de otra dirección. "
                f"Tu sesión está firmada como {authenticated_address}."
            ),
        )
