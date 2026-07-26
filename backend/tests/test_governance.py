"""
Governance endpoints: proposals, voting, delegation and honest treasury reporting.
"""
from datetime import datetime, timedelta, timezone

from app.core.database import proposals_collection

ADDR_A = "0x" + "1a" * 20
ADDR_B = "0x" + "2b" * 20


async def _create_proposal(client, title="Propuesta de prueba",
                           description="Una descripción suficientemente larga para validar.",
                           creator=ADDR_A, duration_days=7):
    return await client.post("/api/governance/proposals", json={
        "title": title,
        "description": description,
        "category": "general",
        "creator_address": creator,
        "duration_days": duration_days,
    })


async def test_create_proposal(client):
    response = await _create_proposal(client)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["votes_for"] == 0
    assert data["creator_address"] == ADDR_A


async def test_create_proposal_strips_html_tags(client):
    response = await _create_proposal(client, title="Hola <b>mundo</b> grande")
    assert response.json()["title"] == "Hola mundo grande"


async def test_create_proposal_rejects_invalid_address(client):
    response = await _create_proposal(client, creator="not-an-address")
    assert response.status_code == 422


async def test_create_proposal_rejects_short_title(client):
    response = await _create_proposal(client, title="ab")
    assert response.status_code == 422


async def test_vote_flow(client):
    proposal_id = (await _create_proposal(client)).json()["id"]

    vote = await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": ADDR_B, "vote": "for",
    })
    assert vote.json()["ok"] is True

    proposal = (await client.get(f"/api/governance/proposals/{proposal_id}")).json()
    assert proposal["votes_for"] == 1
    assert proposal["total_votes"] == 1

    duplicate = await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": ADDR_B, "vote": "against",
    })
    data = duplicate.json()
    assert data["ok"] is False
    assert "Already voted" in data["error"]


async def test_vote_on_missing_proposal_fails(client):
    response = await client.post("/api/governance/vote", json={
        "proposal_id": "no-existe", "voter_address": ADDR_A, "vote": "for",
    })
    assert response.json()["ok"] is False


async def test_vote_rejects_invalid_choice(client):
    response = await client.post("/api/governance/vote", json={
        "proposal_id": "x", "voter_address": ADDR_A, "vote": "maybe",
    })
    assert response.status_code == 422


async def test_expired_proposals_are_resolved(client):
    passed_id = (await _create_proposal(client, title="Debe pasar")).json()["id"]
    expired_id = (await _create_proposal(client, title="Debe expirar")).json()["id"]

    past = datetime.now(timezone.utc) - timedelta(days=1)
    # Reached quorum with majority in favor -> passed
    await proposals_collection().update_one(
        {"id": passed_id},
        {"$set": {"ends_at": past, "votes_for": 7, "votes_against": 3, "total_votes": 10}},
    )
    # No quorum -> expired
    await proposals_collection().update_one(
        {"id": expired_id},
        {"$set": {"ends_at": past, "votes_for": 1, "total_votes": 1}},
    )

    listing = (await client.get("/api/governance/proposals")).json()
    by_id = {p["id"]: p["status"] for p in listing}
    assert by_id[passed_id] == "passed"
    assert by_id[expired_id] == "expired"


async def test_delegation_rejects_self(client):
    response = await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_A,
    })
    assert response.json()["ok"] is False


async def test_delegation_and_voting_power(client):
    response = await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })
    assert response.json()["ok"] is True

    delegation = (await client.get(f"/api/governance/delegate/{ADDR_A}")).json()
    assert delegation["delegated"] is True
    assert delegation["delegate"] == ADDR_B

    delegators = (await client.get(f"/api/governance/delegations/{ADDR_B}")).json()
    assert delegators["delegators"] == [ADDR_A]
    assert delegators["voting_power"] == 2


async def test_delegation_rejects_two_way_cycle(client):
    await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })
    circular = await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_B, "delegate_address": ADDR_A,
    })
    data = circular.json()
    assert data["ok"] is False
    assert "circular" in data["error"].lower()


async def test_revoke_delegation(client):
    await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })
    revoked = (await client.delete(f"/api/governance/delegate/{ADDR_A}")).json()
    assert revoked["ok"] is True

    again = (await client.delete(f"/api/governance/delegate/{ADDR_A}")).json()
    assert again["ok"] is False


async def test_treasury_reports_unconfigured_not_fabricated(client):
    treasury = (await client.get("/api/governance/treasury")).json()
    assert treasury["configured"] is False
    assert treasury["balances"] is None
    assert treasury["total_usd_value"] is None
    assert treasury["transaction_count"] == 0


async def test_treasury_analytics_with_no_transactions(client):
    analytics = (await client.get("/api/governance/treasury/analytics")).json()
    assert analytics["total_income"] == 0
    assert analytics["total_expenses"] == 0
    assert analytics["runway_months"] is None


async def test_stats_have_no_magic_numbers_when_empty(client):
    stats = (await client.get("/api/governance/stats")).json()
    assert stats["total_proposals"] == 0
    assert stats["total_votes_cast"] == 0
    assert stats["participation_rate"] is None
