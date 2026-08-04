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
    elections_collection,
    candidacies_collection,
    election_votes_collection,
    representatives_collection,
)
from .membership_verifier import get_membership_verifier

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

        La comprobación pasa por el MembershipVerifier configurado, igual que
        el gate de votar. La consulta directa que había aquí (`status:
        "active"` a secas) era más débil que ese gate: en producción sumaba
        peso de filas demo/legacy que jamás habrían podido votar, y con
        MEMBERSHIP_SOURCE=onchain habría sumado peso de direcciones sin SBT.
        """
        cursor = delegations_collection().find({"delegate": address.lower()})
        delegations = await cursor.to_list(length=1000)
        delegators = [d["delegator"] for d in delegations]
        if not delegators:
            return []

        verifier = get_membership_verifier()
        active_set = await verifier.filter_members(delegators)
        return [d for d in delegators if d in active_set]

    @classmethod
    async def voting_power(cls, address: str) -> int:
        """Peso POTENCIAL: 1 (voto propio) + delegantes miembros activos.

        Es lo que se muestra en `/delegations/{address}`. El peso realmente
        aplicado a una papeleta lo calcula `contest_vote_weight`, que además
        descuenta a quien ya votó por su cuenta en esa misma consulta.
        """
        return 1 + len(await cls.get_active_delegators(address))

    @classmethod
    async def contest_vote_weight(
        cls,
        address: str,
        collection,
        contest_field: str,
        contest_id: str,
    ) -> tuple[int, list[str]]:
        """Peso aplicable en UNA consulta y los delegantes que lo componen.

        Excluye a los delegantes que ya votaron por su cuenta en esa misma
        consulta. Sin esta exclusión, delegar DESPUÉS de haber votado contaba
        el mismo peso dos veces: una en la papeleta propia y otra dentro del
        peso del delegado (P-61).

        Devuelve también la lista de delegantes contados para persistirla en
        la papeleta: sin ella el `weight` es un número que nadie puede
        recomputar, y es la mitad de lo que hace falta para detectar el orden
        inverso (el delegado vota, el delegante revoca y vota).
        """
        delegators = await cls.get_active_delegators(address)
        if not delegators:
            return 1, []

        cursor = collection().find(
            {
                contest_field: contest_id,
                "voter_address": {"$in": delegators},
            }
        )
        already_voted = {
            v["voter_address"] for v in await cursor.to_list(length=len(delegators))
        }
        counted = [d for d in delegators if d not in already_voted]
        return 1 + len(counted), counted

    @staticmethod
    async def weight_already_delegated_away(
        address: str,
        collection,
        contest_field: str,
        contest_id: str,
    ) -> Optional[str]:
        """Delegado que ya emitió el peso de `address` en esta consulta, o None.

        Cubre el orden que la comprobación de `get_delegate_of` no alcanza: el
        delegado vota, el delegante revoca la delegación y vota por su cuenta.
        Al revocar se borra el vínculo, así que la única evidencia que queda de
        que ese peso ya se gastó es la propia papeleta del delegado.
        """
        ballot = await collection().find_one(
            {
                contest_field: contest_id,
                "delegators": address.lower(),
            }
        )
        return ballot["voter_address"] if ballot else None

    @staticmethod
    async def delegation_block_reason(delegator: str, delegate: str) -> Optional[str]:
        """`None` si `delegator -> delegate` es admisible; si no, POR QUÉ no.

        Devuelve `"cycle"` o `"depth"`. Son cosas distintas y el router lo dice
        distinto: decirle "delegación circular" a quien solo eligió a alguien
        con una cadena larga por detrás es una afirmación falsa sobre lo que
        hizo, y quien la lee no puede corregir el problema real.

        Recorre las delegaciones SALIENTES del delegado en MongoDB (la
        dirección en la que viajaría el voto). Es la comprobación
        autoritativa: sustituye a la copia en memoria del FraudDetector, que
        se vaciaba en cada reinicio (M-2, ROADMAP 3.8).
        """
        seen = {delegator.lower()}
        current = delegate.lower()
        for depth in range(MAX_DELEGATION_WALK):
            if current in seen:
                return "cycle"
            seen.add(current)
            # Cadena demasiado profunda: sospechosa aunque no cierre ciclo.
            # Esta es la heurística que antes aportaba el detector en memoria,
            # ahora sobre el grafo real.
            if depth >= MAX_DELEGATION_DEPTH:
                return "depth"
            nxt = await delegations_collection().find_one({"delegator": current})
            if not nxt:
                return None
            current = nxt["delegate"]
        # Más larga que el tope del recorrido: se trata como sospechosa en vez
        # de seguir caminando indefinidamente.
        return "depth"

    @classmethod
    async def find_delegation_cycle(cls, delegator: str, delegate: str) -> bool:
        """Compatibilidad: `True` si la delegación debe rechazarse."""
        return (await cls.delegation_block_reason(delegator, delegate)) is not None

    @classmethod
    async def compute_proposals_tallies(
        cls, proposal_ids: list[str], votes_collection
    ) -> dict[str, dict[str, int]]:
        """Dynamically compute vote tallies for a list of proposals.

        This prevents divergence between individual ballots and the total tally
        if a crash occurs between inserting the vote and updating the proposal (ROADMAP 3.10).
        """
        if not proposal_ids:
            return {}

        pipeline = [
            {"$match": {"proposal_id": {"$in": proposal_ids}}},
            {
                "$group": {
                    "_id": {"proposal_id": "$proposal_id", "vote": "$vote"},
                    "total_weight": {"$sum": "$weight"},
                }
            },
        ]

        results = (
            await votes_collection()
            .aggregate(pipeline)
            .to_list(length=len(proposal_ids) * 3)
        )

        tallies = {
            pid: {
                "votes_for": 0,
                "votes_against": 0,
                "votes_abstain": 0,
                "total_votes": 0,
            }
            for pid in proposal_ids
        }

        for r in results:
            pid = r["_id"]["proposal_id"]
            vote_type = r["_id"]["vote"]
            weight = r["total_weight"]

            if vote_type == "for":
                tallies[pid]["votes_for"] += weight
            elif vote_type == "against":
                tallies[pid]["votes_against"] += weight
            elif vote_type == "abstain":
                tallies[pid]["votes_abstain"] += weight

            tallies[pid]["total_votes"] += weight

        return tallies

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
                {"id": election["id"]}, {"$set": {"status": derived}}
            )
            election["status"] = derived

        # La finalización se reintenta hasta que deja su marca, no solo en la
        # transición de estado. Antes se llamaba ÚNICAMENTE al pasar a
        # `closed`: si el proceso moría a mitad de escribir los escaños, esa
        # transición ya no volvía a ocurrir y el parlamento se quedaba
        # incompleto para siempre. `finalized_at` se escribe al final, después
        # de reconciliar, así que su ausencia significa exactamente "esto no
        # terminó" (ROADMAP 3.10).
        if derived == "closed" and not election.get("finalized_at"):
            await cls.finalize_election(election)
            election["finalized_at"] = datetime.now(timezone.utc)
        return election

    @classmethod
    async def compute_results(cls, election_id: str) -> list[dict]:
        """Per-candidate weighted totals, ordered by the documented criterion."""
        candidacies = (
            await candidacies_collection()
            .find({"election_id": election_id})
            .to_list(length=1000)
        )

        totals_pipeline = [
            {"$match": {"election_id": election_id}},
            {
                "$group": {
                    "_id": "$candidate_address",
                    "votes": {"$sum": "$weight"},
                }
            },
        ]
        totals_raw = (
            await election_votes_collection()
            .aggregate(totals_pipeline)
            .to_list(length=1000)
        )
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
        results.sort(
            key=lambda r: (
                -r["votes"],
                r["candidacy_created_at"],
                r["candidate_address"],
            )
        )
        return results

    @classmethod
    async def finalize_election(cls, election: dict) -> None:
        """Reconcilia los escaños con el resultado derivado de las papeletas.

        Antes: si ya existía CUALQUIER representante de esta elección, se
        salía sin hacer nada. `insert_many` no es atómico entre documentos, así
        que una caída a mitad de la escritura dejaba un parlamento incompleto
        —tres escaños de cinco— y ese `return` temprano impedía completarlo
        para siempre. Nadie lo habría notado: la lista de representantes se ve
        perfectamente normal, solo que le faltan personas.

        Ahora es una reconciliación idempotente contra el resultado calculado:
        cada ganador se hace `upsert` por (election_id, address) y se borra
        cualquier representante que ya no salga elegido. Reejecutarla no
        cambia nada; ejecutarla tras una caída la termina. No hace falta una
        transacción de MongoDB —que exigiría replica set y no existe en el
        despliegue actual— porque el estado correcto se puede recalcular
        entero desde las papeletas cuantas veces haga falta (ROADMAP 3.10).
        """
        results = await cls.compute_results(election["id"])
        winners = [r for r in results if r["votes"] > 0][: election["seats"]]

        term_start = election["voting_end_at"]
        if term_start.tzinfo is None:
            term_start = term_start.replace(tzinfo=timezone.utc)
        term_end = add_months(term_start, election["term_months"])

        elected = []
        for winner in winners:
            address = winner["candidate_address"]
            elected.append(address)
            # Upsert por (election_id, address): con el índice único, dos
            # finalizaciones simultáneas convergen al mismo estado en vez de
            # duplicar escaños.
            await representatives_collection().update_one(
                {"election_id": election["id"], "address": address},
                {
                    "$set": {
                        "election_id": election["id"],
                        "address": address,
                        "votes": winner["votes"],
                        "term_start": term_start,
                        "term_end": term_end,
                    }
                },
                upsert=True,
            )

        # Cualquier representante que ya no salga elegido sobra: puede venir de
        # una finalización previa interrumpida o de un recuento que cambió al
        # anularse una papeleta. El estado publicado debe ser el derivado.
        removed = await representatives_collection().delete_many(
            {
                "election_id": election["id"],
                "address": {"$nin": elected},
            }
        )

        # ÚLTIMA escritura, y por eso es la que vale: si el proceso muere en
        # cualquier punto anterior, la marca no está y la siguiente lectura
        # vuelve a reconciliar. Escribirla antes convertiría una finalización
        # a medias en una finalización "hecha".
        await elections_collection().update_one(
            {"id": election["id"]},
            {"$set": {"finalized_at": datetime.now(timezone.utc)}},
        )

        if not elected:
            logger.info(
                f"Election {election['id']} closed with no votes; no seats filled"
            )
        else:
            logger.info(
                f"Election {election['id']} reconciled: {len(elected)} seat(s), "
                f"{removed.deleted_count} stale record(s) removed"
            )


governance_service = GovernanceService()
