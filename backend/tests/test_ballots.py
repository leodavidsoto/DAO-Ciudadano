"""
Signed ballots (ROADMAP 3.2/3.3, ADR 0001 decision D-3).

Requiring a session token settled WHO may vote. These tests are about
something else: whether the recorded tally can be trusted by someone who does
not trust the server. A stored signature means a third party can recover each
signer and recount independently.
"""
import pytest
from eth_account import Account

from app.core.config import settings
from app.core.database import Database
from app.services.ballot_service import ballot_service

VOTER = Account.from_key("0x" + "33" * 32)
IMPOSTOR = Account.from_key("0x" + "44" * 32)


def _sign(account, proposal_id, voter, choice, nonce):
    from eth_account.messages import encode_typed_data
    data = ballot_service.typed_data(proposal_id, voter, choice, nonce)
    return Account.sign_message(
        encode_typed_data(full_message=data), account.key
    ).signature.hex()


async def _member(client, address):
    return await client.post("/api/membership/mint", json={
        "wallet_address": address, "assurance_level": "AL2",
        "doc_hash": "0x" + "ee" * 32,
    })


async def _proposal(client, creator):
    return (await client.post("/api/governance/proposals", json={
        "title": "Propuesta firmada",
        "description": "Descripción suficientemente larga para pasar la validación.",
        "category": "general", "creator_address": creator, "duration_days": 7,
    })).json()["id"]


# === Recuperación de firma ===

def test_recovers_the_signer():
    sig = _sign(VOTER, "p1", VOTER.address, "for", "n1")
    assert ballot_service.recover_signer(
        "p1", VOTER.address, "for", "n1", sig
    ) == VOTER.address.lower()


def test_changing_the_choice_invalidates_the_signature():
    """A ballot signed 'for' must not count as 'against'."""
    sig = _sign(VOTER, "p1", VOTER.address, "for", "n1")
    assert ballot_service.recover_signer(
        "p1", VOTER.address, "against", "n1", sig
    ) != VOTER.address.lower()


def test_changing_the_proposal_invalidates_the_signature():
    """A ballot for one proposal must not be reusable on another."""
    sig = _sign(VOTER, "p1", VOTER.address, "for", "n1")
    assert ballot_service.recover_signer(
        "p2", VOTER.address, "for", "n1", sig
    ) != VOTER.address.lower()


def test_domain_is_chain_bound(monkeypatch):
    """A ballot signed for Sepolia must not be valid on another network."""
    monkeypatch.setattr(settings, "SBT_CHAIN_ID", 11155111, raising=False)
    sepolia = ballot_service.domain()
    monkeypatch.setattr(settings, "SBT_CHAIN_ID", 1, raising=False)
    assert ballot_service.domain() != sepolia


# === Extremo a extremo ===

async def test_signed_vote_is_accepted_and_stored_with_its_signature(client):
    await _member(client, VOTER.address)
    pid = await _proposal(client, VOTER.address)
    sig = _sign(VOTER, pid, VOTER.address.lower(), "for", "nonce-1")

    response = await client.post("/api/governance/vote", json={
        "proposal_id": pid, "voter_address": VOTER.address,
        "vote": "for", "nonce": "nonce-1", "signature": sig,
    })
    assert response.json()["ok"] is True

    ballot = await Database.get_db()["votes"].find_one({"proposal_id": pid})
    assert ballot["signature"] == sig, "la firma no se guardó para reverificación"


async def test_a_ballot_signed_by_someone_else_is_rejected(client):
    """The core property: you cannot vote on another member's behalf."""
    await _member(client, VOTER.address)
    pid = await _proposal(client, VOTER.address)
    forged = _sign(IMPOSTOR, pid, VOTER.address.lower(), "for", "nonce-2")

    response = await client.post("/api/governance/vote", json={
        "proposal_id": pid, "voter_address": VOTER.address,
        "vote": "for", "nonce": "nonce-2", "signature": forged,
    })
    body = response.json()
    assert body["ok"] is False
    assert "firma" in body["error"].lower()


async def test_a_captured_ballot_cannot_be_replayed(client):
    """Replay protection is the nonce, consumed against a unique index (3.3)."""
    await _member(client, VOTER.address)
    pid_a = await _proposal(client, VOTER.address)
    sig = _sign(VOTER, pid_a, VOTER.address.lower(), "for", "nonce-3")

    first = await client.post("/api/governance/vote", json={
        "proposal_id": pid_a, "voter_address": VOTER.address,
        "vote": "for", "nonce": "nonce-3", "signature": sig})
    assert first.json()["ok"] is True

    # Same nonce again, even on a different proposal
    pid_b = await _proposal(client, VOTER.address)
    sig_b = _sign(VOTER, pid_b, VOTER.address.lower(), "for", "nonce-3")
    second = await client.post("/api/governance/vote", json={
        "proposal_id": pid_b, "voter_address": VOTER.address,
        "vote": "for", "nonce": "nonce-3", "signature": sig_b})

    assert second.json()["ok"] is False
    assert "ya fue utilizada" in second.json()["error"].lower()


async def test_unsigned_ballots_are_refused_when_required(client, monkeypatch):
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", True, raising=False)
    await _member(client, VOTER.address)
    pid = await _proposal(client, VOTER.address)

    response = await client.post("/api/governance/vote", json={
        "proposal_id": pid, "voter_address": VOTER.address, "vote": "for"})
    assert response.json()["ok"] is False
    assert "firmada" in response.json()["error"].lower()


async def test_a_third_party_can_recount_without_trusting_the_server(client):
    """The point of D-3: recompute the tally from the stored ballots alone."""
    await _member(client, VOTER.address)
    pid = await _proposal(client, VOTER.address)
    sig = _sign(VOTER, pid, VOTER.address.lower(), "for", "nonce-audit")
    await client.post("/api/governance/vote", json={
        "proposal_id": pid, "voter_address": VOTER.address,
        "vote": "for", "nonce": "nonce-audit", "signature": sig})

    ballots = [b async for b in Database.get_db()["votes"].find({"proposal_id": pid})]
    recounted = 0
    for ballot in ballots:
        signer = ballot_service.recover_signer(
            ballot["proposal_id"], ballot["voter_address"],
            ballot["vote"], ballot["nonce"], ballot["signature"],
        )
        assert signer == ballot["voter_address"].lower(), "papeleta no verificable"
        recounted += ballot["weight"]

    proposal = await Database.get_db()["proposals"].find_one({"id": pid})
    assert recounted == proposal["votes_for"]
