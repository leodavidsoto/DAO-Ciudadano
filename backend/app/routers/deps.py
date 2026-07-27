"""
Shared FastAPI dependencies for governance routers.

Membership gating (closes audit finding C-3): every mutating governance
action — creating proposals, voting, delegating, running for election and
voting in elections — requires the acting address to be an ACTIVE member.

The check itself lives behind the MembershipVerifier interface
(app/services/membership_verifier.py) so switching from MongoDB to the
on-chain hasMembership() call (ROADMAP Fase 1.5) is configuration, not code.
"""
from fastapi import HTTPException

from ..services.membership_verifier import get_membership_verifier


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
