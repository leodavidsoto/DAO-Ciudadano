"""
Membership Verifier Service

Single source of truth for "is this address an active DAO member?".
Governance endpoints (proposals, votes, delegation, elections) depend on this
check to close audit finding C-3 (zero-cost Sybil voting).

Two implementations behind one interface so the swap to on-chain verification
(ROADMAP Fase 1.5) is a configuration change, not a rewrite:

- MongoMembershipVerifier: checks the `members` collection. Source of truth
  while minting is off-chain (totalSupply() on Sepolia is still 0).
- OnChainMembershipVerifier: will call hasMembership() on the SBT contract.
  Deliberately NOT implemented yet — it must never be simulated.

Selection is driven by settings.MEMBERSHIP_SOURCE ("mongo" | "onchain").
"""
from abc import ABC, abstractmethod
import logging

from ..core.config import settings
from ..core.database import members_collection

logger = logging.getLogger(__name__)


class MembershipVerifier(ABC):
    """Interface for membership checks used by governance endpoints."""

    @abstractmethod
    async def is_member(self, address: str) -> bool:
        """Return True if `address` holds an active DAO membership."""
        raise NotImplementedError


class MongoMembershipVerifier(MembershipVerifier):
    """Checks the members collection. Source of truth until on-chain minting exists.

    A member counts as active only when its document has status == "active"
    (revoked memberships must not grant governance rights).
    """

    async def is_member(self, address: str) -> bool:
        if not address:
            return False
        query = {
            "wallet_address": address.lower(),
            "status": "active",
        }
        if settings.is_production:
            # Legacy documents have neither field and are therefore
            # quarantined automatically. Demo rows also remain ineligible even
            # if the same MongoDB database is promoted to production.
            query.update({
                "issuance_mode": "onchain",
                "identity_verified": True,
                "tx_hash": {"$type": "string", "$ne": ""},
            })
        member = await members_collection().find_one(query)
        return member is not None


def membership_is_onchain(member: dict) -> bool:
    """True only for explicit on-chain provenance with a stored transaction."""
    return member.get("issuance_mode") == "onchain" and bool(member.get("tx_hash"))


def membership_is_valid(member: dict) -> bool:
    """Whether a stored membership is eligible in the current environment.

    Non-production environments retain pilot behavior for active demo rows.
    Production uses the same provenance requirements as the governance gate.
    Missing fields are intentionally treated as legacy/unverified.
    """
    if member.get("status") != "active":
        return False
    if not settings.is_production:
        return True
    return (
        membership_is_onchain(member)
        and member.get("identity_verified") is True
    )


class OnChainMembershipVerifier(MembershipVerifier):
    """Calls hasMembership() on the SBT contract. ROADMAP Fase 1.5.

    NOT implemented on purpose. Wiring it requires:
      - web3.py as a backend dependency (not installed yet),
      - an RPC endpoint (SEPOLIA_RPC_URL) and the contract ABI,
      - the contract to actually have minted members (totalSupply() > 0,
        which itself depends on decisions D-1/D-2 and task 1.5),
      - a short-lived cache so governance endpoints do not hit the RPC
        on every request (ROADMAP 3.1).

    It must fail loudly instead of pretending: returning True here would
    reintroduce exactly the kind of simulated capability this project is
    trying to eliminate (see docs/AUDIT.md).
    """

    async def is_member(self, address: str) -> bool:
        raise NotImplementedError(
            "On-chain membership verification is not implemented yet "
            "(ROADMAP Fase 1.5). Set MEMBERSHIP_SOURCE=mongo until real "
            "on-chain minting exists."
        )


def get_membership_verifier() -> MembershipVerifier:
    """Factory: choose the verifier from settings.MEMBERSHIP_SOURCE.

    Defaults to "mongo". Unknown values fail loudly at call time rather
    than silently falling back to a weaker check.
    """
    source = (settings.MEMBERSHIP_SOURCE or "mongo").strip().lower()
    if source == "mongo":
        return MongoMembershipVerifier()
    if source == "onchain":
        return OnChainMembershipVerifier()
    raise ValueError(
        f"Invalid MEMBERSHIP_SOURCE '{settings.MEMBERSHIP_SOURCE}'. "
        "Expected 'mongo' or 'onchain'."
    )
