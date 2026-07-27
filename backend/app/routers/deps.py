"""
Shared FastAPI dependencies for governance routers.

Membership gating (closes audit finding C-3): every mutating governance
action — creating proposals, voting, delegating, running for election and
voting in elections — requires the acting address to be an ACTIVE member.

The check itself lives behind the MembershipVerifier interface
(app/services/membership_verifier.py) so switching from MongoDB to the
on-chain hasMembership() call (ROADMAP Fase 1.5) is configuration, not code.
"""
import logging

from fastapi import HTTPException

from ..services.membership_verifier import get_membership_verifier

logger = logging.getLogger(__name__)


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


# Collections whose integrity depends on a unique index existing.
_GUARDED = {
    "membership": ("members.wallet_address", "members.token_id"),
    "vote": ("votes.[('proposal_id', 1), ('voter_address', 1)]",),
    "candidacy": ("candidacies.[('election_id', 1), ('candidate_address', 1)]",),
    "election_vote": ("election_votes.[('election_id', 1), ('voter_address', 1)]",),
    "delegation": ("delegations.delegator",),
}


async def require_integrity_indexes(area: str = "") -> None:
    """Refuse writes while a required unique index is missing.

    Startup is deliberately non-blocking (a cold free-tier cluster must not
    turn a slow first request into a failed deploy), so the guarantee has to
    be enforced here instead: without the unique index, the router pre-checks
    are just friendly messages that two concurrent requests can both pass.

    Returns 503 rather than 500: the condition is temporary while indexes are
    still building, and permanent only if the data already violates them.
    """
    from ..core.database import Database

    if Database.integrity_ready():
        return

    status = Database.integrity_status()
    logger.warning(
        f"Write refused ({area or 'unknown'}): integrity indexes missing "
        f"{status['missing_required_indexes']}"
    )
    raise HTTPException(
        status_code=503,
        detail=(
            "El servicio está iniciando sus garantías de integridad y no puede "
            "aceptar escrituras en este momento. Reintenta en unos segundos."
        ),
    )
