"""
Wallet authentication (ROADMAP 1.1, audit findings C-1 and C-6).

Two things are verified here, and they are different:

1. The real SIWE handshake works — a nonce is issued, a genuine signature is
   accepted, and forged, replayed or mismatched ones are not.
2. Mutating endpoints actually refuse anonymous callers. Before this, the
   `voter_address` came from the request body and the backend believed it, so
   a single curl could vote as anyone.
"""
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.services.siwe_service import siwe_service

MEMBER = Account.from_key("0x" + "11" * 32)
OTHER = Account.from_key("0x" + "22" * 32)


async def _challenge(client, address):
    response = await client.post("/api/session/challenge", json={"address": address})
    assert response.status_code == 200
    return response.json()


def _sign(account, message):
    return Account.sign_message(encode_defunct(text=message), account.key).signature.hex()


# === Handshake real ===

async def test_challenge_returns_a_readable_message(anon_client):
    body = await _challenge(anon_client, MEMBER.address)
    assert body["nonce"]
    # The person approving in MetaMask must understand what they are signing.
    assert MEMBER.address.lower() in body["message"].lower()
    assert body["nonce"] in body["message"]
    assert "no autoriza ninguna transacción" in body["message"].lower()


async def test_valid_signature_yields_a_session(anon_client):
    body = await _challenge(anon_client, MEMBER.address)
    response = await anon_client.post("/api/session/verify", json={
        "address": MEMBER.address, "signature": _sign(MEMBER, body["message"]),
    })
    data = response.json()
    assert data["ok"] is True
    assert siwe_service.read_token(data["token"]) == MEMBER.address.lower()


async def test_signature_from_another_wallet_is_rejected(anon_client):
    """The core property: signing with a key you do not own proves nothing."""
    body = await _challenge(anon_client, MEMBER.address)
    response = await anon_client.post("/api/session/verify", json={
        "address": MEMBER.address, "signature": _sign(OTHER, body["message"]),
    })
    assert response.json()["ok"] is False


async def test_garbage_signature_is_rejected(anon_client):
    await _challenge(anon_client, MEMBER.address)
    response = await anon_client.post("/api/session/verify", json={
        "address": MEMBER.address, "signature": "0xdeadbeef",
    })
    assert response.json()["ok"] is False


async def test_a_nonce_cannot_be_replayed(anon_client):
    """A captured signature must not buy a second session."""
    body = await _challenge(anon_client, MEMBER.address)
    signature = _sign(MEMBER, body["message"])

    first = await anon_client.post("/api/session/verify", json={
        "address": MEMBER.address, "signature": signature})
    second = await anon_client.post("/api/session/verify", json={
        "address": MEMBER.address, "signature": signature})

    assert first.json()["ok"] is True
    assert second.json()["ok"] is False


async def test_verify_without_a_challenge_is_rejected(anon_client):
    response = await anon_client.post("/api/session/verify", json={
        "address": MEMBER.address, "signature": "0x" + "00" * 65,
    })
    assert response.json()["ok"] is False


# === Tokens ===

def test_expired_token_is_refused(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1, raising=False)
    assert siwe_service.read_token(siwe_service.issue_token(MEMBER.address)) is None


def test_token_signed_with_another_secret_is_refused(monkeypatch):
    from app.core.config import settings
    token = siwe_service.issue_token(MEMBER.address)
    monkeypatch.setattr(settings, "SECRET_KEY", "a-different-secret", raising=False)
    assert siwe_service.read_token(token) is None


def test_tampered_token_is_refused():
    token = siwe_service.issue_token(MEMBER.address)
    assert siwe_service.read_token(token[:-4] + "AAAA") is None


# === Los endpoints exigen sesión ===

@pytest.mark.parametrize("path,body", [
    ("/api/governance/proposals", {
        "title": "Propuesta", "description": "Descripción suficientemente larga.",
        "category": "general", "creator_address": MEMBER.address, "duration_days": 7}),
    ("/api/governance/vote", {
        "proposal_id": "x", "voter_address": MEMBER.address, "vote": "for"}),
    ("/api/governance/delegate", {
        "delegator_address": MEMBER.address, "delegate_address": OTHER.address}),
    ("/api/membership/mint", {
        "wallet_address": MEMBER.address, "assurance_level": "AL2", "doc_hash": "0xabc"}),
])
async def test_mutating_endpoints_reject_anonymous_callers(anon_client, path, body):
    response = await anon_client.post(path, json=body)
    assert response.status_code == 401, f"{path} aceptó una petición sin sesión"


async def test_cannot_act_on_behalf_of_another_address(anon_client, auth):
    """Holding a session for A must not let you vote as B."""
    response = await anon_client.post(
        "/api/governance/proposals",
        json={"title": "Propuesta", "description": "Descripción suficientemente larga.",
              "category": "general", "creator_address": OTHER.address, "duration_days": 7},
        headers=auth(MEMBER.address),
    )
    assert response.status_code == 403


async def test_reads_stay_public(anon_client):
    """Transparency: anyone can read governance without signing in."""
    assert (await anon_client.get("/api/governance/proposals")).status_code == 200
    assert (await anon_client.get("/api/dashboard/stats")).status_code == 200
