"""
Representative elections: nomination window, weighted voting, results,
tie-breaking and seated representatives. Statuses derive from dates, so the
tests move the stored dates to force phase transitions (same technique the
proposal-expiry tests use).
"""
from datetime import datetime, timedelta, timezone

from app.core.database import (
    candidacies_collection,
    elections_collection,
    representatives_collection,
)

ADDR_A = "0x" + "1a" * 20
ADDR_B = "0x" + "2b" * 20
ADDR_C = "0x" + "3c" * 20
ADDR_D = "0x" + "4d" * 20
NON_MEMBER = "0x" + "9f" * 20


async def _mint_member(client, address):
    response = await client.post("/api/membership/mint", json={
        "wallet_address": address,
        "assurance_level": "AL2",
        "doc_hash": f"0xdoc{address[-8:]}",
    })
    assert response.json()["ok"] is True
    return response


async def _create_election(client, title="Elección de prueba",
                           description="Elegimos representantes para el próximo período.",
                           seats=1, nominations_days=7, voting_days=7, term_months=12):
    return await client.post("/api/governance/elections", json={
        "title": title,
        "description": description,
        "seats": seats,
        "nominations_days": nominations_days,
        "voting_days": voting_days,
        "term_months": term_months,
    })


async def _nominate(client, election_id, address, statement=None):
    return await client.post(f"/api/governance/elections/{election_id}/candidacies", json={
        "candidate_address": address,
        "statement": statement or "Mi programa: participación, transparencia y rendición de cuentas.",
    })


async def _vote(client, election_id, voter, candidate):
    return await client.post(f"/api/governance/elections/{election_id}/vote", json={
        "voter_address": voter,
        "candidate_address": candidate,
    })


async def _open_voting(election_id):
    """Move nominations_end_at to the past so the derived status is `voting`."""
    await elections_collection().update_one(
        {"id": election_id},
        {"$set": {"nominations_end_at": datetime.now(timezone.utc) - timedelta(hours=1)}},
    )


async def _close_election(election_id):
    """Move both dates to the past so the derived status is `closed`."""
    now = datetime.now(timezone.utc)
    await elections_collection().update_one(
        {"id": election_id},
        {"$set": {
            "nominations_end_at": now - timedelta(hours=2),
            "voting_end_at": now - timedelta(hours=1),
        }},
    )


# === Creation and listing ===

async def test_create_election(client):
    response = await _create_election(client, seats=3)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "nominations"
    assert data["seats"] == 3
    assert data["candidacy_count"] == 0
    assert data["nominations_end_at"] < data["voting_end_at"]

    listing = (await client.get("/api/governance/elections")).json()
    assert len(listing) == 1
    assert listing[0]["id"] == data["id"]


async def test_create_election_rejects_invalid_seats(client):
    response = await _create_election(client, seats=0)
    assert response.status_code == 422


async def test_get_missing_election_returns_404(client):
    response = await client.get("/api/governance/elections/no-existe")
    assert response.status_code == 404


# === Candidacies ===

async def test_candidacy_rejects_non_member(client):
    election_id = (await _create_election(client)).json()["id"]
    response = await _nominate(client, election_id, NON_MEMBER)
    assert response.status_code == 403
    assert "miembros activos" in response.json()["detail"]


async def test_candidacy_flow_and_duplicate(client):
    await _mint_member(client, ADDR_A)
    election_id = (await _create_election(client)).json()["id"]

    first = await _nominate(client, election_id, ADDR_A)
    assert first.status_code == 200
    assert first.json()["candidate_address"] == ADDR_A

    duplicate = await _nominate(client, election_id, ADDR_A)
    assert duplicate.status_code == 409

    listing = (await client.get(
        f"/api/governance/elections/{election_id}/candidacies"
    )).json()
    assert len(listing) == 1


async def test_candidacy_rejected_outside_nominations(client):
    await _mint_member(client, ADDR_A)
    election_id = (await _create_election(client)).json()["id"]
    await _open_voting(election_id)

    response = await _nominate(client, election_id, ADDR_A)
    assert response.status_code == 409
    assert "postulaciones" in response.json()["detail"]

    election = (await client.get(f"/api/governance/elections/{election_id}")).json()
    assert election["status"] == "voting"


# === Voting ===

async def test_election_vote_rejects_non_member(client):
    await _mint_member(client, ADDR_A)
    election_id = (await _create_election(client)).json()["id"]
    await _nominate(client, election_id, ADDR_A)
    await _open_voting(election_id)

    response = await _vote(client, election_id, NON_MEMBER, ADDR_A)
    assert response.status_code == 403


async def test_election_vote_rejected_outside_voting(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    election_id = (await _create_election(client)).json()["id"]
    await _nominate(client, election_id, ADDR_A)

    # Still in nominations
    response = await _vote(client, election_id, ADDR_B, ADDR_A)
    assert response.status_code == 409

    # Already closed
    await _close_election(election_id)
    response = await _vote(client, election_id, ADDR_B, ADDR_A)
    assert response.status_code == 409


async def test_election_vote_rejects_double_vote(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    election_id = (await _create_election(client)).json()["id"]
    await _nominate(client, election_id, ADDR_A)
    await _open_voting(election_id)

    first = await _vote(client, election_id, ADDR_B, ADDR_A)
    assert first.json()["ok"] is True

    second = await _vote(client, election_id, ADDR_B, ADDR_A)
    data = second.json()
    assert data["ok"] is False
    assert "Ya votaste" in data["error"]


async def test_election_vote_rejects_non_candidate(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    election_id = (await _create_election(client)).json()["id"]
    await _open_voting(election_id)

    response = await _vote(client, election_id, ADDR_B, ADDR_A)
    data = response.json()
    assert data["ok"] is False
    assert "no es candidata" in data["error"]


async def test_election_vote_uses_delegated_weight(client):
    for addr in (ADDR_A, ADDR_B, ADDR_C, ADDR_D):
        await _mint_member(client, addr)
    election_id = (await _create_election(client)).json()["id"]
    await _nominate(client, election_id, ADDR_D)
    await _open_voting(election_id)

    # A and B delegate to C -> C votes with weight 3
    for delegator in (ADDR_A, ADDR_B):
        assert (await client.post("/api/governance/delegate", json={
            "delegator_address": delegator, "delegate_address": ADDR_C,
        })).json()["ok"] is True

    vote = await _vote(client, election_id, ADDR_C, ADDR_D)
    data = vote.json()
    assert data["ok"] is True
    assert data["weight"] == 3

    results = (await client.get(
        f"/api/governance/elections/{election_id}/results"
    )).json()
    assert results["results"][0]["votes"] == 3
    assert results["total_votes_cast"] == 1  # one ballot
    assert results["total_weight_cast"] == 3


async def test_delegator_cannot_vote_in_election(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    await _mint_member(client, ADDR_C)
    election_id = (await _create_election(client)).json()["id"]
    await _nominate(client, election_id, ADDR_C)
    await _open_voting(election_id)

    await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })
    response = await _vote(client, election_id, ADDR_A, ADDR_C)
    assert response.status_code == 403
    assert ADDR_B in response.json()["detail"]


# === Full cycle, results and representatives ===

async def test_full_election_cycle(client):
    for addr in (ADDR_A, ADDR_B, ADDR_C, ADDR_D):
        await _mint_member(client, addr)

    election_id = (await _create_election(
        client, seats=1, term_months=6
    )).json()["id"]

    # Nominations
    await _nominate(client, election_id, ADDR_A, "Programa A: abrir los datos de la DAO.")
    await _nominate(client, election_id, ADDR_B, "Programa B: descentralizar la tesorería.")

    # Voting: A gets 2 ballots, B gets 1
    await _open_voting(election_id)
    assert (await _vote(client, election_id, ADDR_C, ADDR_A)).json()["ok"] is True
    assert (await _vote(client, election_id, ADDR_D, ADDR_A)).json()["ok"] is True
    assert (await _vote(client, election_id, ADDR_B, ADDR_B)).json()["ok"] is True

    # Close and read final results
    await _close_election(election_id)
    results = (await client.get(
        f"/api/governance/elections/{election_id}/results"
    )).json()
    assert results["final"] is True
    assert results["status"] == "closed"
    by_addr = {r["candidate_address"]: r for r in results["results"]}
    assert by_addr[ADDR_A]["votes"] == 2
    assert by_addr[ADDR_A]["elected"] is True
    assert by_addr[ADDR_B]["votes"] == 1
    assert by_addr[ADDR_B]["elected"] is False

    # The winner is seated with the configured term
    reps = (await client.get("/api/governance/representatives")).json()
    assert len(reps) == 1
    rep = reps[0]
    assert rep["address"] == ADDR_A
    assert rep["votes"] == 2
    assert rep["election_id"] == election_id
    term_start = datetime.fromisoformat(rep["term_start"])
    term_end = datetime.fromisoformat(rep["term_end"])
    assert (term_end.year - term_start.year) * 12 + (term_end.month - term_start.month) == 6

    # Finalization is idempotent: reading again does not duplicate seats
    await client.get(f"/api/governance/elections/{election_id}/results")
    assert await representatives_collection().count_documents({}) == 1


async def test_tie_breaks_by_earlier_candidacy(client):
    for addr in (ADDR_A, ADDR_B, ADDR_C, ADDR_D):
        await _mint_member(client, addr)
    election_id = (await _create_election(client, seats=1)).json()["id"]

    await _nominate(client, election_id, ADDR_A)
    await _nominate(client, election_id, ADDR_B)
    # Make the registration order unambiguous regardless of clock resolution
    base = datetime.now(timezone.utc)
    await candidacies_collection().update_one(
        {"election_id": election_id, "candidate_address": ADDR_A},
        {"$set": {"created_at": base - timedelta(minutes=10)}},
    )
    await candidacies_collection().update_one(
        {"election_id": election_id, "candidate_address": ADDR_B},
        {"$set": {"created_at": base - timedelta(minutes=5)}},
    )

    await _open_voting(election_id)
    assert (await _vote(client, election_id, ADDR_C, ADDR_A)).json()["ok"] is True
    assert (await _vote(client, election_id, ADDR_D, ADDR_B)).json()["ok"] is True

    await _close_election(election_id)
    results = (await client.get(
        f"/api/governance/elections/{election_id}/results"
    )).json()
    # 1-1 tie: the earlier candidacy (ADDR_A) takes the single seat
    assert results["results"][0]["candidate_address"] == ADDR_A
    assert results["results"][0]["elected"] is True
    assert results["results"][1]["elected"] is False


async def test_closed_election_without_votes_seats_nobody(client):
    await _mint_member(client, ADDR_A)
    election_id = (await _create_election(client)).json()["id"]
    await _nominate(client, election_id, ADDR_A)
    await _close_election(election_id)

    results = (await client.get(
        f"/api/governance/elections/{election_id}/results"
    )).json()
    assert results["final"] is True
    assert all(r["elected"] is False for r in results["results"])

    reps = (await client.get("/api/governance/representatives")).json()
    assert reps == []
