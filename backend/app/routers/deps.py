"""
Shared FastAPI dependencies for governance routers.

Membership gating (closes audit finding C-3): every mutating governance
action — creating proposals, voting, delegating, running for election and
voting in elections — requires the acting address to be an ACTIVE member.

The check itself lives behind the MembershipVerifier interface
(app/services/membership_verifier.py) so switching from MongoDB to the
on-chain hasMembership() call (ROADMAP Fase 1.5) is configuration, not code.

Wallet auth (closes audit finding C-1): `current_address` extrae la
dirección autenticada del JWT de sesión (emitido tras verificar SIWE, ver
services/siwe_service.py). `ensure_acts_as_self` compara esa dirección
contra la que el request dice controlar -- sin esto, cualquiera podía
poner el wallet_address de otra persona en el body y actuar como ella.
"""
from fastapi import HTTPException, Header
from typing import Optional

from ..core import readiness
from ..services.membership_verifier import get_membership_verifier
from ..services import siwe_service


async def ensure_active_member(address: str, action: str) -> None:
    """Raise 403 (Spanish, user-facing) if `address` is not an active member.

    `action` is the verb phrase for the error message, e.g. "votar".
    """
    verifier = get_membership_verifier()
    if not await verifier.is_member(address):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Solo los miembros activos de la DAO pueden {action}. "
                f"La dirección {address} no tiene una membresía activa."
            ),
        )


async def current_address(authorization: Optional[str] = Header(default=None)) -> str:
    """Dirección (lowercase) autenticada vía el JWT de sesión Bearer.

    401 si no hay header, el esquema no es Bearer, o el token es inválido
    o expiró.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Falta iniciar sesión con tu wallet (encabezado Authorization: Bearer <token>).",
        )
    # Never decode a caller-controlled JWT with an absent, public or weak
    # signing key. A deployment with unsafe auth configuration fails closed
    # even if an attacker already knows the repository's development key.
    readiness.require("SECRET_KEY", "validar la sesión de wallet")
    readiness.require_siwe_configuration()
    token = authorization.split(" ", 1)[1].strip()
    address = siwe_service.read_token(token)
    if not address:
        raise HTTPException(
            status_code=401,
            detail="Tu sesión no es válida o expiró. Vuelve a iniciar sesión con tu wallet.",
        )
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
