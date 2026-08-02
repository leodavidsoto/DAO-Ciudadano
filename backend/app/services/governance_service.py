"""
Governance Service

Business logic shared by the governance and elections routers:
delegated voting power, delegation cycle detection against the database,
and election state transitions/results.

Design decisions (documented here on purpose):

* Voting power = 1 (own vote) + number of ACTIVE members that delegated to
  the address. Delegations are NOT transitive: if A delegates to B and B
  delegates to C, C's power counts B but not A. Rationale: transitive chains
  concentrate power in ways the delegator never consented to, make the weight
  of a single vote unbounded, and turn every cycle check into a graph
  traversal on the hot path. One hop is auditable and cheap to compute.

* An address that delegated its vote cannot vote directly while the
  delegation is active (it must revoke first). Its weight travels with the
  delegate; allowing both would double-count.

* Delegators that are not active members do not add weight. Membership can
  be revoked after delegating, so this is enforced at vote time, not at
  delegation time.
"""
import calendar
from datetime import datetime, timezone
import logging
from typing import Optional

from ..core.database import (
    delegations_collection,
    members_collection,
    elections_collection,
    candidacies_collection,
    election_votes_collection,
    representatives_collection,
)

logger = logging.getLogger(__name__)


def add_months(dt: datetime, months: int) -> datetime:
    """Calendar-aware month addition (stdlib only; no dateutil dependency).

    Clamps the day to the target month's length (Jan 31 + 1 month = Feb 28/29).
    """
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# Profundidad máxima admitida de una cadena de delegación. Antes vivía en el
# FraudDetector en memoria (MAX_CHAIN_DEPTH = 3) sobre una copia del grafo que
# se vaciaba en cada reinicio; ahora se evalúa contra el grafo real (ROADMAP
# 3.8). Las delegaciones no son transitivas para el peso, así que una cadena
# larga no concentra poder — pero sí es una estructura anómala que conviene
# frenar.
MAX_DELEGATION_DEPTH = 3

# Tope duro del recorrido, por si el grafo contuviera un ciclo largo que la
# comprobación de dos nodos no detecta.
MAX_DELEGATION_WALK = 10


class GovernanceService:
    """Delegation weight and election lifecycle logic."""

    # === Delegation / voting power ===

    @staticmethod
    async def get_delegate_of(address: str) -> Optional[str]:
        """Address this member delegated to, or None."""
        delegation = await delegations_collection().find_one(
            {"delegator": address.lower()}
        )
        return delegation["delegate"] if delegation else None

    @staticmethod
    async def get_active_delegators(address: str) -> list[str]:
        """Delegators of `address` that are currently ACTIVE members.

        Non-member (or revoked) delegators are excluded: delegating does not
        create voting rights that the delegator does not have.
        """
        cursor = delegations_collection().find({"delegate": address.lower()})
        delegations = await cursor.to_list(length=1000)
        delegators = [d["delegator"] for d in delegations]
        if not delegators:
            return []

        active_cursor = members_collection().find({
            "wallet_address": {"$in": delegators},
            "status": "active",
        })
        active_members = await active_cursor.to_list(length=1000)
        active_set = {m["wallet_address"] for m in active_members}
        return [d for d in delegators if d in active_set]

    @classmethod
    async def voting_power(cls, address: str) -> int:
        """1 (own vote) + active-member delegators. No transitive chains."""
        return 1 + len(await cls.get_active_delegators(address))

    @staticmethod
    async def find_delegation_cycle(delegator: str, delegate: str) -> bool:
        """True if `delegator -> delegate` would close a cycle in the stored graph.

        Walks the delegate's OUTGOING delegations in MongoDB (the direction a
        vote would travel). This is the authoritative check: the in-memory
        FraudDetector complements it but loses its state on restart (M-2).
        """
        seen = {delegator.lower()}
        current = delegate.lower()
        for depth in range(MAX_DELEGATION_WALK):
            if current in seen:
                return True
            seen.add(current)
            # Cadena demasiado profunda: se trata como sospechosa igual que un
            # ciclo. Esta es la heurística que antes aportaba el detector en
            # memoria, ahora sobre el grafo autoritativo.
            if depth >= MAX_DELEGATION_DEPTH:
                return True
            nxt = await delegations_collection().find_one({"delegator": current})
            if not nxt:
                return False
            current = nxt["delegate"]
        # Chain longer than the cap: treat as suspicious rather than looping
        return True

    # === Elections ===

    # Tie-break criterion (documented decision): candidates with equal vote
    # weight are ordered by earlier candidacy (created_at ascending) — first
    # to step up wins the seat — with the candidate address as a final
    # deterministic fallback. No randomness: anyone can recompute the result
    # from the stored votes and candidacies.

    @staticmethod
    def derive_election_status(election: dict, now: Optional[datetime] = None) -> str:
        """Status derived from dates, mirroring how expired proposals work."""
        now = now or datetime.now(timezone.utc)
        nominations_end = election["nominations_end_at"]
        voting_end = election["voting_end_at"]
        # Mongo returns naive UTC datetimes; normalize for comparison
        if nominations_end.tzinfo is None:
            nominations_end = nominations_end.replace(tzinfo=timezone.utc)
        if voting_end.tzinfo is None:
            voting_end = voting_end.replace(tzinfo=timezone.utc)

        if now < nominations_end:
            return "nominations"
        if now < voting_end:
            return "voting"
        return "closed"

    @classmethod
    async def sync_election_status(cls, election: dict) -> dict:
        """Persist the date-derived status; finalize results on close."""
        derived = cls.derive_election_status(election)
        if derived != election.get("status"):
            await elections_collection().update_one(
                {"id": election["id"]},
                {"$set": {"status": derived}}
            )
            election["status"] = derived
            if derived == "closed":
                await cls.finalize_election(election)
        return election

    @classmethod
    async def compute_results(cls, election_id: str) -> list[dict]:
        """Per-candidate weighted totals, ordered by the documented criterion."""
        candidacies = await candidacies_collection().find(
            {"election_id": election_id}
        ).to_list(length=1000)

        totals_pipeline = [
            {"$match": {"election_id": election_id}},
            {"$group": {
                "_id": "$candidate_address",
                "votes": {"$sum": "$weight"},
            }},
        ]
        totals_raw = await election_votes_collection().aggregate(
            totals_pipeline
        ).to_list(length=1000)
        totals = {t["_id"]: t["votes"] for t in totals_raw}

        results = [
            {
                "candidate_address": c["candidate_address"],
                "statement": c.get("statement", ""),
                "votes": totals.get(c["candidate_address"], 0),
                "candidacy_created_at": c["created_at"],
            }
            for c in candidacies
        ]
        # Order: votes desc, earlier candidacy first (tie-break), address last
        results.sort(key=lambda r: (
            -r["votes"],
            r["candidacy_created_at"],
            r["candidate_address"],
        ))
        return results

    @classmethod
    async def finalize_election(cls, election: dict) -> None:
        """Write Representative records for the top `seats` candidates.

        Idempotent: skips if representatives for this election already exist.
        Candidates with zero votes do not get a seat — an election nobody
        voted in elects nobody (no fabricated legitimacy).
        """
        existing = await representatives_collection().count_documents(
            {"election_id": election["id"]}
        )
        if existing > 0:
            return

        results = await cls.compute_results(election["id"])
        winners = [r for r in results if r["votes"] > 0][: election["seats"]]
        if not winners:
            logger.info(f"Election {election['id']} closed with no votes; no seats filled")
            return

        term_start = election["voting_end_at"]
        if term_start.tzinfo is None:
            term_start = term_start.replace(tzinfo=timezone.utc)
        term_end = add_months(term_start, election["term_months"])

        docs = [
            {
                "election_id": election["id"],
                "address": w["candidate_address"],
                "votes": w["votes"],
                "term_start": term_start,
                "term_end": term_end,
            }
            for w in winners
        ]
        await representatives_collection().insert_many(docs)
        logger.info(
            f"Election {election['id']} finalized: {len(docs)} representative(s) seated"
        )


governance_service = GovernanceService()
