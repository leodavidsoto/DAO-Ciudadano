"""
Governance endpoints: proposals, voting, delegation and honest treasury reporting.

Since the membership gate (C-3) landed, every mutating governance action
requires an ACTIVE member: tests mint memberships first via the real endpoint.
"""
from datetime import datetime, timedelta, timezone

from app.core.database import members_collection, proposals_collection, votes_collection

ADDR_A = "0x" + "1a" * 20
ADDR_B = "0x" + "2b" * 20
ADDR_C = "0x" + "3c" * 20
ADDR_D = "0x" + "4d" * 20
NON_MEMBER = "0x" + "9f" * 20


async def _mint_member(client, address):
    """Register an active member through the real mint endpoint."""
    response = await client.post("/api/membership/mint", json={
        "wallet_address": address,
        "assurance_level": "AL2",
        "doc_hash": f"0xdoc{address[-8:]}",
    })
    assert response.json()["ok"] is True, f"fixture mint failed: {response.json()}"
    return response


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


# === Proposals ===

async def test_create_proposal(client):
    await _mint_member(client, ADDR_A)
    response = await _create_proposal(client)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["votes_for"] == 0
    assert data["creator_address"] == ADDR_A


async def test_create_proposal_strips_html_tags(client):
    await _mint_member(client, ADDR_A)
    response = await _create_proposal(client, title="Hola <b>mundo</b> grande")
    assert response.json()["title"] == "Hola mundo grande"


async def test_create_proposal_rejects_invalid_address(client):
    response = await _create_proposal(client, creator="not-an-address")
    assert response.status_code == 422


async def test_create_proposal_rejects_short_title(client):
    response = await _create_proposal(client, title="ab")
    assert response.status_code == 422


async def test_create_proposal_rejects_non_member(client):
    response = await _create_proposal(client, creator=NON_MEMBER)
    assert response.status_code == 403
    assert "miembros activos" in response.json()["detail"]


# === Voting ===

async def test_vote_flow(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    vote = await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": ADDR_B, "vote": "for",
    })
    data = vote.json()
    assert data["ok"] is True
    assert data["weight"] == 1
    assert data["vote_hash"] is not None

    proposal = (await client.get(f"/api/governance/proposals/{proposal_id}")).json()
    assert proposal["votes_for"] == 1
    assert proposal["total_votes"] == 1

    duplicate = await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": ADDR_B, "vote": "against",
    })
    data = duplicate.json()
    assert data["ok"] is False
    assert "Already voted" in data["error"]


async def test_vote_rejects_non_member(client):
    await _mint_member(client, ADDR_A)
    proposal_id = (await _create_proposal(client)).json()["id"]

    response = await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": NON_MEMBER, "vote": "for",
    })
    assert response.status_code == 403
    assert NON_MEMBER in response.json()["detail"]


async def test_vote_rejects_revoked_member(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    await members_collection().update_one(
        {"wallet_address": ADDR_B}, {"$set": {"status": "revoked"}}
    )
    response = await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": ADDR_B, "vote": "for",
    })
    assert response.status_code == 403


async def test_vote_on_missing_proposal_fails(client):
    await _mint_member(client, ADDR_A)
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
    await _mint_member(client, ADDR_A)
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


# === Delegated voting power (A-5) ===

async def test_vote_weight_includes_active_delegators(client):
    for addr in (ADDR_A, ADDR_B, ADDR_C):
        await _mint_member(client, addr)
    proposal_id = (await _create_proposal(client, creator=ADDR_A)).json()["id"]

    for delegator in (ADDR_A, ADDR_B):
        response = await client.post("/api/governance/delegate", json={
            "delegator_address": delegator, "delegate_address": ADDR_C,
        })
        assert response.json()["ok"] is True

    vote = await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": ADDR_C, "vote": "for",
    })
    data = vote.json()
    assert data["ok"] is True
    assert data["weight"] == 3  # own vote + two active delegators

    proposal = (await client.get(f"/api/governance/proposals/{proposal_id}")).json()
    assert proposal["votes_for"] == 3
    assert proposal["total_votes"] == 3

    # The applied weight is persisted on the vote record
    record = await votes_collection().find_one({
        "proposal_id": proposal_id, "voter_address": ADDR_C,
    })
    assert record["weight"] == 3


async def test_delegator_cannot_vote_directly(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })

    response = await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": ADDR_A, "vote": "for",
    })
    assert response.status_code == 403
    # The error must say to whom the vote was delegated
    assert ADDR_B in response.json()["detail"]


async def test_revoked_delegator_adds_no_weight(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })
    # Membership revoked AFTER delegating: the delegation stops counting
    await members_collection().update_one(
        {"wallet_address": ADDR_A}, {"$set": {"status": "revoked"}}
    )

    vote = await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": ADDR_B, "vote": "for",
    })
    data = vote.json()
    assert data["ok"] is True
    assert data["weight"] == 1


async def test_vote_after_revoking_delegation(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })
    await client.delete(f"/api/governance/delegate/{ADDR_A}")

    vote = await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": ADDR_A, "vote": "for",
    })
    data = vote.json()
    assert data["ok"] is True
    assert data["weight"] == 1


# === Delegation ===

async def test_delegation_rejects_self(client):
    await _mint_member(client, ADDR_A)
    response = await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_A,
    })
    assert response.json()["ok"] is False


async def test_delegation_rejects_non_member_delegator(client):
    await _mint_member(client, ADDR_B)
    response = await client.post("/api/governance/delegate", json={
        "delegator_address": NON_MEMBER, "delegate_address": ADDR_B,
    })
    assert response.status_code == 403


async def test_delegation_rejects_non_member_delegate(client):
    await _mint_member(client, ADDR_A)
    response = await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": NON_MEMBER,
    })
    data = response.json()
    assert data["ok"] is False
    assert "no es miembro activo" in data["error"]


async def test_delegation_and_voting_power(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    response = await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })
    assert response.json()["ok"] is True

    delegation = (await client.get(f"/api/governance/delegate/{ADDR_A}")).json()
    assert delegation["delegated"] is True
    assert delegation["delegate"] == ADDR_B

    delegators = (await client.get(f"/api/governance/delegations/{ADDR_B}")).json()
    assert delegators["delegators"] == [ADDR_A]
    assert delegators["active_delegators"] == [ADDR_A]
    assert delegators["voting_power"] == 2


async def test_delegation_rejects_two_way_cycle(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })
    circular = await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_B, "delegate_address": ADDR_A,
    })
    data = circular.json()
    assert data["ok"] is False
    assert "circular" in data["error"].lower()


async def test_delegation_rejects_longer_cycle(client):
    """a->b, b->c already stored; c->a must be rejected (audit N-3)."""
    for addr in (ADDR_A, ADDR_B, ADDR_C):
        await _mint_member(client, addr)
    assert (await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })).json()["ok"] is True
    assert (await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_B, "delegate_address": ADDR_C,
    })).json()["ok"] is True

    circular = await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_C, "delegate_address": ADDR_A,
    })
    data = circular.json()
    assert data["ok"] is False
    assert "circular" in data["error"].lower()


async def test_revoke_delegation(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    await client.post("/api/governance/delegate", json={
        "delegator_address": ADDR_A, "delegate_address": ADDR_B,
    })
    revoked = (await client.delete(f"/api/governance/delegate/{ADDR_A}")).json()
    assert revoked["ok"] is True

    again = (await client.delete(f"/api/governance/delegate/{ADDR_A}")).json()
    assert again["ok"] is False


# === Treasury (honest reporting) ===

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
