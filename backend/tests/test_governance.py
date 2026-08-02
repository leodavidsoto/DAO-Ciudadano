"""
Governance endpoints: proposals, voting, delegation and honest treasury reporting.

Since the membership gate (C-3) landed, every mutating governance action
requires an ACTIVE member: tests mint memberships first via the real endpoint.

Since the wallet-session gate (C-1) landed, every mutating governance action
ALSO requires the caller to be authenticated (SIWE) as the exact address it
claims to act as: tests sign in with real eth_account keypairs and attach
the resulting Bearer token.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data

from app.core.config import settings
from app.core.database import members_collection, proposals_collection, votes_collection
from app.services import ballot_service

# Wallets reales derivadas de llaves privadas fijas de prueba (NO producción).
ACCOUNT_A = Account.from_key("0x" + "1a" * 32)
ACCOUNT_B = Account.from_key("0x" + "2b" * 32)
ACCOUNT_C = Account.from_key("0x" + "3c" * 32)
ACCOUNT_D = Account.from_key("0x" + "4d" * 32)
NON_MEMBER_ACCOUNT = Account.from_key("0x" + "9f" * 32)

# Todos los endpoints normalizan direcciones a minúsculas antes de guardarlas
# o devolverlas, así que estas constantes ya están en minúsculas para poder
# comparar directamente contra las respuestas.
ADDR_A = ACCOUNT_A.address.lower()
ADDR_B = ACCOUNT_B.address.lower()
ADDR_C = ACCOUNT_C.address.lower()
ADDR_D = ACCOUNT_D.address.lower()
NON_MEMBER = NON_MEMBER_ACCOUNT.address.lower()

_ACCOUNTS_BY_ADDRESS = {
    a.address.lower(): a for a in (ACCOUNT_A, ACCOUNT_B, ACCOUNT_C, ACCOUNT_D, NON_MEMBER_ACCOUNT)
}


async def _sign_in(client, account):
    """Ejecuta el flujo SIWE real (challenge + firma + verify) y devuelve
    los headers de Authorization para autenticar como esa cuenta."""
    challenge = await client.post("/api/wallet/challenge", json={"address": account.address})
    challenge.raise_for_status()
    body = challenge.json()
    signed = Account.sign_message(encode_defunct(text=body["message"]), private_key=account.key)
    verify = await client.post("/api/wallet/verify", json={
        "address": account.address,
        "nonce": body["nonce"],
        "signature": signed.signature.hex(),
    })
    verify.raise_for_status()
    return {"Authorization": f"Bearer {verify.json()['token']}"}


async def _headers_for(client, address):
    """Resuelve la Account registrada para `address` y firma la sesión."""
    account = _ACCOUNTS_BY_ADDRESS[address]
    return await _sign_in(client, account)


async def _mint_member(client, address):
    """Register an active member through the real mint endpoint (self-auth)."""
    headers = await _headers_for(client, address)
    response = await client.post("/api/membership/mint", json={
        "wallet_address": address,
        "assurance_level": "AL2",
        "doc_hash": f"0xdoc{address[-8:]}",
    }, headers=headers)
    assert response.json()["ok"] is True, f"fixture mint failed: {response.json()}"
    return response


async def _create_proposal(client, title="Propuesta de prueba",
                           description="Una descripción suficientemente larga para validar.",
                           creator=ADDR_A, duration_days=7, headers=None):
    if headers is None and creator in _ACCOUNTS_BY_ADDRESS:
        headers = await _headers_for(client, creator)
    return await client.post("/api/governance/proposals", json={
        "title": title,
        "description": description,
        "category": "general",
        "creator_address": creator,
        "duration_days": duration_days,
    }, headers=headers)


async def _vote(client, voter, proposal_id, choice, headers=None):
    if headers is None and voter in _ACCOUNTS_BY_ADDRESS:
        headers = await _headers_for(client, voter)
    return await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id, "voter_address": voter, "vote": choice,
    }, headers=headers)


async def _delegate(client, delegator, delegate, headers=None):
    if headers is None and delegator in _ACCOUNTS_BY_ADDRESS:
        headers = await _headers_for(client, delegator)
    return await client.post("/api/governance/delegate", json={
        "delegator_address": delegator, "delegate_address": delegate,
    }, headers=headers)


async def _revoke_delegation(client, delegator, headers=None):
    if headers is None and delegator in _ACCOUNTS_BY_ADDRESS:
        headers = await _headers_for(client, delegator)
    return await client.delete(f"/api/governance/delegate/{delegator}", headers=headers)


# === Proposals ===

async def test_create_proposal(client):
    await _mint_member(client, ADDR_A)
    response = await _create_proposal(client)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert data["votes_for"] == 0
    assert data["creator_address"] == ADDR_A.lower()


async def test_create_proposal_strips_html_tags(client):
    await _mint_member(client, ADDR_A)
    response = await _create_proposal(client, title="Hola <b>mundo</b> grande")
    assert response.json()["title"] == "Hola mundo grande"


async def test_create_proposal_rejects_invalid_address(client):
    """Con sesión válida (de cualquier cuenta), un creator_address con
    formato inválido en el body se rechaza con 422 -- se prueba con una
    sesión real porque current_address (C-1) corre antes que la
    validación del body, así que sin Authorization el resultado sería 401,
    no 422."""
    headers = await _headers_for(client, ADDR_A)
    response = await _create_proposal(client, creator="not-an-address", headers=headers)
    assert response.status_code == 422


async def test_create_proposal_rejects_short_title(client):
    headers = await _headers_for(client, ADDR_A)
    response = await _create_proposal(client, title="ab", headers=headers)
    assert response.status_code == 422


async def test_create_proposal_rejects_non_member(client):
    headers = await _headers_for(client, NON_MEMBER)
    response = await _create_proposal(client, creator=NON_MEMBER, headers=headers)
    assert response.status_code == 403
    assert "miembros activos" in response.json()["detail"]


async def test_create_proposal_rejects_acting_as_another_address(client):
    """Autenticado como B pero reclamando ser el creador A: 403 (cierra C-1)."""
    await _mint_member(client, ADDR_A)
    headers = await _headers_for(client, ADDR_B)
    response = await _create_proposal(client, creator=ADDR_A, headers=headers)
    assert response.status_code == 403


# === Voting ===

async def test_vote_flow(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    vote = await _vote(client, ADDR_B, proposal_id, "for")
    data = vote.json()
    assert data["ok"] is True
    assert data["weight"] == 1
    assert data["vote_hash"] is not None

    proposal = (await client.get(f"/api/governance/proposals/{proposal_id}")).json()
    assert proposal["votes_for"] == 1
    assert proposal["total_votes"] == 1

    duplicate = await _vote(client, ADDR_B, proposal_id, "against")
    data = duplicate.json()
    assert data["ok"] is False
    assert "Already voted" in data["error"]


async def test_simultaneous_votes_are_counted_once(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]
    headers = await _headers_for(client, ADDR_B)

    first, second = await asyncio.gather(
        _vote(client, ADDR_B, proposal_id, "for", headers=headers),
        _vote(client, ADDR_B, proposal_id, "for", headers=headers),
    )
    payloads = [first.json(), second.json()]

    assert sum(payload.get("ok") is True for payload in payloads) == 1
    assert await votes_collection().count_documents(
        {"proposal_id": proposal_id, "voter_address": ADDR_B}
    ) == 1
    proposal = (await client.get(f"/api/governance/proposals/{proposal_id}")).json()
    assert proposal["votes_for"] == 1
    assert proposal["total_votes"] == 1


async def test_signed_ballot_is_persisted_and_publicly_verifiable(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", True)
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]
    headers = await _headers_for(client, ADDR_B)
    nonce = "audit-ballot-nonce"
    encoded = encode_typed_data(full_message=ballot_service.typed_data(
        proposal_id,
        ADDR_B,
        "for",
        nonce,
    ))
    signature = ACCOUNT_B.sign_message(encoded).signature.hex()

    response = await client.post(
        "/api/governance/vote",
        json={
            "proposal_id": proposal_id,
            "voter_address": ADDR_B,
            "vote": "for",
            "nonce": nonce,
            "signature": signature,
        },
        headers=headers,
    )
    evidence = (
        await client.get(f"/api/governance/proposals/{proposal_id}/ballots")
    ).json()

    assert response.json()["ok"] is True
    assert len(evidence) == 1
    assert evidence[0]["signature"] == signature
    assert evidence[0]["signature_scheme"] == "EIP-712"
    assert evidence[0]["chain_id"] == settings.SIWE_CHAIN_ID
    assert evidence[0]["signature_valid"] is True
    assert evidence[0]["integrity_hash_valid"] is True


async def test_vote_endpoint_rejects_expired_proposal_without_listing_first(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]
    await proposals_collection().update_one(
        {"id": proposal_id},
        {"$set": {"ends_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )

    response = await _vote(client, ADDR_B, proposal_id, "for")
    proposal = (await client.get(f"/api/governance/proposals/{proposal_id}")).json()

    assert response.json()["ok"] is False
    assert proposal["status"] == "expired"
    assert await votes_collection().count_documents({"proposal_id": proposal_id}) == 0


async def test_production_never_accepts_unsigned_proposal_vote_when_flag_is_off(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SIWE_DOMAIN", "estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_URI", "https://estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_CHAIN_ID", 11155111)
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", False)
    await members_collection().insert_one({
        "wallet_address": ADDR_B,
        "token_id": 99,
        "status": "active",
        "issuance_mode": "onchain",
        "identity_verified": True,
        "tx_hash": "0x" + "ab" * 32,
    })
    now = datetime.now(timezone.utc)
    await proposals_collection().insert_one({
        "id": "prod-proposal",
        "title": "Producción segura",
        "description": "Una propuesta que exige papeleta firmada en producción.",
        "category": "general",
        "creator_address": ADDR_B,
        "status": "active",
        "votes_for": 0,
        "votes_against": 0,
        "votes_abstain": 0,
        "total_votes": 0,
        "quorum_required": 10,
        "created_at": now,
        "ends_at": now + timedelta(days=1),
    })
    headers = await _headers_for(client, ADDR_B)

    response = await _vote(
        client,
        ADDR_B,
        "prod-proposal",
        "for",
        headers=headers,
    )

    assert response.status_code == 503
    assert await votes_collection().count_documents({}) == 0


async def test_vote_rejects_non_member(client):
    await _mint_member(client, ADDR_A)
    proposal_id = (await _create_proposal(client)).json()["id"]

    response = await _vote(client, NON_MEMBER, proposal_id, "for")
    assert response.status_code == 403
    assert NON_MEMBER.lower() in response.json()["detail"]


async def test_vote_rejects_revoked_member(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    await members_collection().update_one(
        {"wallet_address": ADDR_B.lower()}, {"$set": {"status": "revoked"}}
    )
    response = await _vote(client, ADDR_B, proposal_id, "for")
    assert response.status_code == 403


async def test_vote_on_missing_proposal_fails(client):
    await _mint_member(client, ADDR_A)
    response = await _vote(client, ADDR_A, "no-existe", "for")
    assert response.json()["ok"] is False


async def test_vote_rejects_invalid_choice(client):
    """current_address (C-1) corre antes que la validación del body, así
    que se necesita una sesión válida para que un `vote` inválido
    produzca 422 en vez de 401."""
    headers = await _headers_for(client, ADDR_A)
    response = await client.post("/api/governance/vote", json={
        "proposal_id": "x", "voter_address": ADDR_A, "vote": "maybe",
    }, headers=headers)
    assert response.status_code == 422


async def test_vote_rejects_acting_as_another_address(client):
    """Autenticado como A pero reclamando votar como B: 403 (cierra C-1)."""
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    headers = await _headers_for(client, ADDR_A)
    response = await _vote(client, ADDR_B, proposal_id, "for", headers=headers)
    assert response.status_code == 403


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
        response = await _delegate(client, delegator, ADDR_C)
        assert response.json()["ok"] is True

    vote = await _vote(client, ADDR_C, proposal_id, "for")
    data = vote.json()
    assert data["ok"] is True
    assert data["weight"] == 3  # own vote + two active delegators

    proposal = (await client.get(f"/api/governance/proposals/{proposal_id}")).json()
    assert proposal["votes_for"] == 3
    assert proposal["total_votes"] == 3

    # The applied weight is persisted on the vote record
    record = await votes_collection().find_one({
        "proposal_id": proposal_id, "voter_address": ADDR_C.lower(),
    })
    assert record["weight"] == 3


async def test_delegator_cannot_vote_directly(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    await _delegate(client, ADDR_A, ADDR_B)

    response = await _vote(client, ADDR_A, proposal_id, "for")
    assert response.status_code == 403
    # The error must say to whom the vote was delegated
    assert ADDR_B.lower() in response.json()["detail"]


async def test_revoked_delegator_adds_no_weight(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    await _delegate(client, ADDR_A, ADDR_B)
    # Membership revoked AFTER delegating: the delegation stops counting
    await members_collection().update_one(
        {"wallet_address": ADDR_A.lower()}, {"$set": {"status": "revoked"}}
    )

    vote = await _vote(client, ADDR_B, proposal_id, "for")
    data = vote.json()
    assert data["ok"] is True
    assert data["weight"] == 1


async def test_vote_after_revoking_delegation(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]

    await _delegate(client, ADDR_A, ADDR_B)
    await _revoke_delegation(client, ADDR_A)

    vote = await _vote(client, ADDR_A, proposal_id, "for")
    data = vote.json()
    assert data["ok"] is True
    assert data["weight"] == 1


# === Delegation ===

async def test_delegation_rejects_self(client):
    await _mint_member(client, ADDR_A)
    response = await _delegate(client, ADDR_A, ADDR_A)
    assert response.json()["ok"] is False


async def test_delegation_rejects_non_member_delegator(client):
    await _mint_member(client, ADDR_B)
    response = await _delegate(client, NON_MEMBER, ADDR_B)
    assert response.status_code == 403


async def test_delegation_rejects_non_member_delegate(client):
    await _mint_member(client, ADDR_A)
    response = await _delegate(client, ADDR_A, NON_MEMBER)
    data = response.json()
    assert data["ok"] is False
    assert "no es miembro activo" in data["error"]


async def test_delegation_rejects_acting_as_another_address(client):
    """Autenticado como B pero reclamando delegar en nombre de A: 403 (cierra C-1)."""
    await _mint_member(client, ADDR_A)
    headers = await _headers_for(client, ADDR_B)
    response = await _delegate(client, ADDR_A, ADDR_B, headers=headers)
    assert response.status_code == 403


async def test_delegation_and_voting_power(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    response = await _delegate(client, ADDR_A, ADDR_B)
    assert response.json()["ok"] is True

    delegation = (await client.get(f"/api/governance/delegate/{ADDR_A}")).json()
    assert delegation["delegated"] is True
    assert delegation["delegate"] == ADDR_B.lower()

    delegators = (await client.get(f"/api/governance/delegations/{ADDR_B}")).json()
    assert delegators["delegators"] == [ADDR_A.lower()]
    assert delegators["active_delegators"] == [ADDR_A.lower()]
    assert delegators["voting_power"] == 2


async def test_delegation_rejects_two_way_cycle(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    await _delegate(client, ADDR_A, ADDR_B)
    circular = await _delegate(client, ADDR_B, ADDR_A)
    data = circular.json()
    assert data["ok"] is False
    assert "circular" in data["error"].lower()


async def test_delegation_rejects_longer_cycle(client):
    """a->b, b->c already stored; c->a must be rejected (audit N-3)."""
    for addr in (ADDR_A, ADDR_B, ADDR_C):
        await _mint_member(client, addr)
    assert (await _delegate(client, ADDR_A, ADDR_B)).json()["ok"] is True
    assert (await _delegate(client, ADDR_B, ADDR_C)).json()["ok"] is True

    circular = await _delegate(client, ADDR_C, ADDR_A)
    data = circular.json()
    assert data["ok"] is False
    assert "circular" in data["error"].lower()


async def test_revoke_delegation(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    await _delegate(client, ADDR_A, ADDR_B)
    revoked = (await _revoke_delegation(client, ADDR_A)).json()
    assert revoked["ok"] is True

    again = (await _revoke_delegation(client, ADDR_A)).json()
    assert again["ok"] is False


async def test_revoke_delegation_rejects_acting_as_another_address(client):
    """Autenticado como B pero reclamando revocar la delegación de A: 403 (cierra C-1)."""
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    await _delegate(client, ADDR_A, ADDR_B)

    headers = await _headers_for(client, ADDR_B)
    response = await _revoke_delegation(client, ADDR_A, headers=headers)
    assert response.status_code == 403


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


async def test_treasury_transactions_serialize_stored_records(client):
    """A stored transaction must not turn the endpoint into a 500.

    The handler returned raw Mongo documents, so the ObjectId in `_id` made
    FastAPI's encoder fail on the first real record ever written.
    """
    from app.core.database import treasury_transactions_collection

    await treasury_transactions_collection().insert_one({
        "id": "tx-1",
        "type": "income",
        "amount": 1.5,
        "currency": "ETH",
        "description": "Aporte registrado",
        "category": "operations",
        "timestamp": datetime.now(timezone.utc),
    })

    response = await client.get("/api/governance/treasury/transactions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "tx-1"
    assert "_id" not in body[0]


async def test_public_list_limits_are_bounded(client):
    """An unauthenticated caller cannot ask for an unbounded page."""
    for path in (
        "/api/governance/proposals?limit=1000000",
        "/api/governance/treasury/transactions?limit=1000000",
        "/api/governance/elections?limit=1000000",
        "/api/dashboard/activity?limit=1000000",
    ):
        assert (await client.get(path)).status_code == 422, path
        assert (await client.get(path.replace("1000000", "0"))).status_code == 422, path


async def test_replayed_ballot_nonce_is_rejected_as_conflict(client, monkeypatch):
    """Reusing a (voter, nonce) pair must fail as 409, not as a storage error.

    Only DuplicateKeyError means "already used"; any other Mongo failure now
    surfaces as 503 so a transient outage is never reported to the voter as a
    spent ballot.
    """
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", True)
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    first_proposal = (await _create_proposal(client)).json()["id"]
    second_proposal = (await _create_proposal(client)).json()["id"]
    headers = await _headers_for(client, ADDR_B)
    nonce = "replayed-nonce"

    def _signed(proposal_id):
        encoded = encode_typed_data(full_message=ballot_service.typed_data(
            proposal_id, ADDR_B, "for", nonce,
        ))
        return ACCOUNT_B.sign_message(encoded).signature.hex()

    async def _cast(proposal_id):
        return await client.post(
            "/api/governance/vote",
            json={
                "proposal_id": proposal_id,
                "voter_address": ADDR_B,
                "vote": "for",
                "nonce": nonce,
                "signature": _signed(proposal_id),
            },
            headers=headers,
        )

    assert (await _cast(first_proposal)).json()["ok"] is True

    replayed = await _cast(second_proposal)
    assert replayed.status_code == 409
    assert "ya fue usada" in replayed.json()["detail"]


async def test_delegation_depth_heuristic_survived_the_move_to_mongo(client):
    """La profundidad máxima de cadena se evalúa ahora sobre el grafo real.

    Antes vivía en el FraudDetector en memoria, sobre una copia que se vaciaba
    en cada reinicio: bastaba reiniciar el proceso para que una cadena
    profunda dejara de detectarse. Ahora sale de MongoDB.
    """
    from app.core.database import delegations_collection
    from app.services.governance_service import MAX_DELEGATION_DEPTH, governance_service

    # Cadena b -> c -> d -> e, más profunda que el máximo admitido.
    chain = ["0xb", "0xc", "0xd", "0xe"]
    for origin, target in zip(chain, chain[1:]):
        await delegations_collection().insert_one(
            {"delegator": origin, "delegate": target}
        )

    assert MAX_DELEGATION_DEPTH == 3
    # Delegar en el inicio de la cadena la haría demasiado profunda.
    assert await governance_service.find_delegation_cycle("0xa", "0xb") is True


async def test_a_short_delegation_chain_is_still_allowed(client):
    """La heurística no puede rechazar una delegación normal."""
    from app.services.governance_service import governance_service

    assert await governance_service.find_delegation_cycle("0xa", "0xb") is False


async def test_delegation_cycles_are_still_detected(client):
    from app.core.database import delegations_collection
    from app.services.governance_service import governance_service

    await delegations_collection().insert_one({"delegator": "0xb", "delegate": "0xa"})

    # a -> b cerraría el ciclo a -> b -> a.
    assert await governance_service.find_delegation_cycle("0xa", "0xb") is True
