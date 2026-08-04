"""
Representative elections: nomination window, weighted voting, results,
tie-breaking and seated representatives. Statuses derive from dates, so the
tests move the stored dates to force phase transitions (same technique the
proposal-expiry tests use).
"""

from datetime import datetime, timedelta, timezone

import jwt
from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.config import settings
from app.core.database import (
    candidacies_collection,
    elections_collection,
    members_collection,
    representatives_collection,
)

# Wallets reales derivadas de llaves privadas fijas de prueba (NO producción).
# Necesarias porque todos los endpoints mutantes prueban control de la wallet
# mediante una sesión SIWE, además de comprobar la membresía activa.
_ACCOUNT_A = Account.from_key("0x" + "1a" * 32)
_ACCOUNT_B = Account.from_key("0x" + "2b" * 32)
_ACCOUNT_C = Account.from_key("0x" + "3c" * 32)
_ACCOUNT_D = Account.from_key("0x" + "4d" * 32)
_NON_MEMBER_ACCOUNT = Account.from_key("0x" + "9f" * 32)

# Todos los endpoints normalizan direcciones a minúsculas antes de guardarlas
# o devolverlas, así que estas constantes ya están en minúsculas para poder
# comparar directamente contra las respuestas (igual que las literales "0x..."
# que reemplazan, que ya eran todas minúsculas).
ADDR_A = _ACCOUNT_A.address.lower()
ADDR_B = _ACCOUNT_B.address.lower()
ADDR_C = _ACCOUNT_C.address.lower()
ADDR_D = _ACCOUNT_D.address.lower()
NON_MEMBER = _NON_MEMBER_ACCOUNT.address.lower()

_ACCOUNTS_BY_ADDRESS = {
    a.address.lower(): a
    for a in (_ACCOUNT_A, _ACCOUNT_B, _ACCOUNT_C, _ACCOUNT_D, _NON_MEMBER_ACCOUNT)
}


async def _sign_in(client, account):
    challenge = await client.post(
        "/api/wallet/challenge", json={"address": account.address}
    )
    challenge.raise_for_status()
    body = challenge.json()
    signed = Account.sign_message(
        encode_defunct(text=body["message"]), private_key=account.key
    )
    verify = await client.post(
        "/api/wallet/verify",
        json={
            "address": account.address,
            "nonce": body["nonce"],
            "signature": signed.signature.hex(),
        },
    )
    verify.raise_for_status()
    return {"Authorization": f"Bearer {verify.json()['token']}"}


_SESSION_HEADERS = {}


async def _headers_for(client, address):
    """Reuse a valid stateless JWT within a test to keep the suite fast."""
    normalized = address.lower()
    key = (id(client), normalized)
    if key not in _SESSION_HEADERS:
        _SESSION_HEADERS[key] = await _sign_in(client, _ACCOUNTS_BY_ADDRESS[normalized])
    return _SESSION_HEADERS[key]


def _no_session(client):
    """Devuelve headers vacíos y descarta la sesión por cookie del cliente.

    Desde que `/wallet/verify` fija una cookie HttpOnly (tarea 1.13), el
    cliente httpx la conserva en su cookie jar: "sin encabezado Authorization"
    ya no significa "sin sesión". Estos tests quieren lo segundo.
    """
    client.cookies.clear()
    return {}


async def _mint_member(client, address):
    headers = await _sign_in(client, _ACCOUNTS_BY_ADDRESS[address])
    response = await client.post(
        "/api/membership/mint",
        json={
            "wallet_address": address,
            "assurance_level": "AL2",
            "doc_hash": f"0xdoc{address[-8:]}",
        },
        headers=headers,
    )
    assert response.json()["ok"] is True
    return response


async def _create_election(
    client,
    title="Elección de prueba",
    description="Elegimos representantes para el próximo período.",
    seats=1,
    nominations_days=7,
    voting_days=7,
    term_months=12,
    creator_address=ADDR_A,
    authenticated_address=None,
    include_auth=True,
):
    headers = _no_session(client)
    if include_auth:
        headers = await _headers_for(client, authenticated_address or creator_address)
    return await client.post(
        "/api/governance/elections",
        json={
            "title": title,
            "description": description,
            "seats": seats,
            "nominations_days": nominations_days,
            "voting_days": voting_days,
            "term_months": term_months,
            "creator_address": creator_address,
        },
        headers=headers,
    )


async def _nominate(
    client,
    election_id,
    address,
    statement=None,
    authenticated_address=None,
    include_auth=True,
):
    headers = _no_session(client)
    if include_auth:
        headers = await _headers_for(client, authenticated_address or address)
    return await client.post(
        f"/api/governance/elections/{election_id}/candidacies",
        json={
            "candidate_address": address,
            "statement": statement
            or "Mi programa: participación, transparencia y rendición de cuentas.",
        },
        headers=headers,
    )


async def _vote(
    client, election_id, voter, candidate, authenticated_address=None, include_auth=True
):
    headers = _no_session(client)
    if include_auth:
        headers = await _headers_for(client, authenticated_address or voter)
    return await client.post(
        f"/api/governance/elections/{election_id}/vote",
        json={
            "voter_address": voter,
            "candidate_address": candidate,
        },
        headers=headers,
    )


async def _open_voting(election_id):
    """Move nominations_end_at to the past so the derived status is `voting`."""
    await elections_collection().update_one(
        {"id": election_id},
        {
            "$set": {
                "nominations_end_at": datetime.now(timezone.utc) - timedelta(hours=1)
            }
        },
    )


async def _close_election(election_id):
    """Move both dates to the past so the derived status is `closed`."""
    now = datetime.now(timezone.utc)
    await elections_collection().update_one(
        {"id": election_id},
        {
            "$set": {
                "nominations_end_at": now - timedelta(hours=2),
                "voting_end_at": now - timedelta(hours=1),
            }
        },
    )


# === Creation and listing ===


async def test_create_election(client):
    await _mint_member(client, ADDR_A)
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


async def test_create_election_requires_own_wallet_session(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)

    missing = await _create_election(client, include_auth=False)
    assert missing.status_code == 401

    impersonated = await _create_election(
        client,
        creator_address=ADDR_A,
        authenticated_address=ADDR_B,
    )
    assert impersonated.status_code == 403
    assert "otra dirección" in impersonated.json()["detail"]


async def test_public_development_key_cannot_forge_election_session(
    client,
    monkeypatch,
):
    """An unconfigured deployment must not trust the repository's known key."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "SECRET_KEY", "dev-secret-key")
    await members_collection().insert_one(
        {
            "wallet_address": ADDR_A,
            "status": "active",
        }
    )
    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {
            "sub": ADDR_A,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
        },
        "dev-secret-key",
        algorithm="HS256",
    )

    response = await client.post(
        "/api/governance/elections",
        json={
            "title": "Elección que no debe existir",
            "description": "Este intento usa una llave pública de desarrollo.",
            "seats": 1,
            "nominations_days": 7,
            "voting_days": 7,
            "term_months": 12,
            "creator_address": ADDR_A,
        },
        headers={"Authorization": f"Bearer {forged}"},
    )

    assert response.status_code == 503
    assert "SECRET_KEY" in response.json()["detail"]
    assert await elections_collection().count_documents({}) == 0


async def test_create_election_rejects_non_member(client):
    """Opening an election is a governance action, not open to any address."""
    response = await _create_election(client, creator_address=NON_MEMBER)
    assert response.status_code == 403
    assert "miembros activos" in response.json()["detail"]


async def test_create_election_rejects_invalid_seats(client):
    response = await _create_election(client, seats=0)
    assert response.status_code == 422


async def test_get_missing_election_returns_404(client):
    response = await client.get("/api/governance/elections/no-existe")
    assert response.status_code == 404


async def test_production_election_vote_is_blocked_until_ballots_are_signed(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SIWE_DOMAIN", "estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_URI", "https://estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_CHAIN_ID", 11155111)
    await members_collection().insert_one(
        {
            "wallet_address": ADDR_A,
            "token_id": 99,
            "status": "active",
            "issuance_mode": "onchain",
            "identity_verified": True,
            "tx_hash": "0x" + "cd" * 32,
        }
    )
    headers = await _sign_in(client, _ACCOUNT_A)

    response = await client.post(
        "/api/governance/elections/prod-election/vote",
        json={
            "voter_address": ADDR_A,
            "candidate_address": ADDR_B,
        },
        headers=headers,
    )

    # El bloqueo dejó de ser incondicional: ahora depende de que la exigencia
    # de papeletas firmadas esté activada (ROADMAP 3.2/3.3).
    assert response.status_code == 503
    assert "SIGNED_BALLOTS_REQUIRED" in response.json()["detail"]


async def test_production_with_signed_ballots_demands_a_signature(client, monkeypatch):
    """Con la exigencia activada, votar sin firma se rechaza explícitamente."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SIWE_DOMAIN", "estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_URI", "https://estamosdao.cl")
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", True)
    await members_collection().insert_one(
        {
            "wallet_address": ADDR_A,
            "token_id": 98,
            "status": "active",
            "issuance_mode": "onchain",
            "identity_verified": True,
            "tx_hash": "0x" + "ef" * 32,
        }
    )
    headers = await _sign_in(client, _ACCOUNT_A)

    response = await client.post(
        "/api/governance/elections/prod-election/vote",
        json={"voter_address": ADDR_A, "candidate_address": ADDR_B},
        headers=headers,
    )

    assert response.status_code == 422
    assert "firmada" in response.json()["detail"]


# === Candidacies ===


async def test_candidacy_rejects_non_member(client):
    await _mint_member(client, ADDR_A)
    election_id = (await _create_election(client)).json()["id"]
    response = await _nominate(client, election_id, NON_MEMBER)
    assert response.status_code == 403
    assert "miembros activos" in response.json()["detail"]


async def test_candidacy_requires_own_wallet_session(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    election_id = (await _create_election(client)).json()["id"]

    missing = await _nominate(client, election_id, ADDR_A, include_auth=False)
    assert missing.status_code == 401

    impersonated = await _nominate(
        client,
        election_id,
        ADDR_A,
        authenticated_address=ADDR_B,
    )
    assert impersonated.status_code == 403
    assert "otra dirección" in impersonated.json()["detail"]


async def test_candidacy_flow_and_duplicate(client):
    await _mint_member(client, ADDR_A)
    election_id = (await _create_election(client)).json()["id"]

    first = await _nominate(client, election_id, ADDR_A)
    assert first.status_code == 200
    assert first.json()["candidate_address"] == ADDR_A

    duplicate = await _nominate(client, election_id, ADDR_A)
    assert duplicate.status_code == 409

    listing = (
        await client.get(f"/api/governance/elections/{election_id}/candidacies")
    ).json()
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


async def test_election_vote_requires_own_wallet_session(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    election_id = (await _create_election(client)).json()["id"]
    await _nominate(client, election_id, ADDR_A)
    await _open_voting(election_id)

    missing = await _vote(client, election_id, ADDR_B, ADDR_A, include_auth=False)
    assert missing.status_code == 401

    impersonated = await _vote(
        client,
        election_id,
        ADDR_B,
        ADDR_A,
        authenticated_address=ADDR_A,
    )
    assert impersonated.status_code == 403
    assert "otra dirección" in impersonated.json()["detail"]

    valid = await _vote(client, election_id, ADDR_B, ADDR_A)
    assert valid.status_code == 200
    assert valid.json()["ok"] is True


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
        headers = await _sign_in(client, _ACCOUNTS_BY_ADDRESS[delegator])
        assert (
            await client.post(
                "/api/governance/delegate",
                json={
                    "delegator_address": delegator,
                    "delegate_address": ADDR_C,
                },
                headers=headers,
            )
        ).json()["ok"] is True

    vote = await _vote(client, election_id, ADDR_C, ADDR_D)
    data = vote.json()
    assert data["ok"] is True
    assert data["weight"] == 3

    results = (
        await client.get(f"/api/governance/elections/{election_id}/results")
    ).json()
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

    headers = await _sign_in(client, _ACCOUNTS_BY_ADDRESS[ADDR_A])
    await client.post(
        "/api/governance/delegate",
        json={
            "delegator_address": ADDR_A,
            "delegate_address": ADDR_B,
        },
        headers=headers,
    )
    response = await _vote(client, election_id, ADDR_A, ADDR_C)
    assert response.status_code == 403
    assert ADDR_B in response.json()["detail"]


# === Full cycle, results and representatives ===


async def test_full_election_cycle(client):
    for addr in (ADDR_A, ADDR_B, ADDR_C, ADDR_D):
        await _mint_member(client, addr)

    election_id = (await _create_election(client, seats=1, term_months=6)).json()["id"]

    # Nominations
    await _nominate(
        client, election_id, ADDR_A, "Programa A: abrir los datos de la DAO."
    )
    await _nominate(
        client, election_id, ADDR_B, "Programa B: descentralizar la tesorería."
    )

    # Voting: A gets 2 ballots, B gets 1
    await _open_voting(election_id)
    assert (await _vote(client, election_id, ADDR_C, ADDR_A)).json()["ok"] is True
    assert (await _vote(client, election_id, ADDR_D, ADDR_A)).json()["ok"] is True
    assert (await _vote(client, election_id, ADDR_B, ADDR_B)).json()["ok"] is True

    # Close and read final results
    await _close_election(election_id)
    results = (
        await client.get(f"/api/governance/elections/{election_id}/results")
    ).json()
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
    assert (term_end.year - term_start.year) * 12 + (
        term_end.month - term_start.month
    ) == 6

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
    results = (
        await client.get(f"/api/governance/elections/{election_id}/results")
    ).json()
    # 1-1 tie: the earlier candidacy (ADDR_A) takes the single seat
    assert results["results"][0]["candidate_address"] == ADDR_A
    assert results["results"][0]["elected"] is True
    assert results["results"][1]["elected"] is False


async def test_closed_election_without_votes_seats_nobody(client):
    await _mint_member(client, ADDR_A)
    election_id = (await _create_election(client)).json()["id"]
    await _nominate(client, election_id, ADDR_A)
    await _close_election(election_id)

    results = (
        await client.get(f"/api/governance/elections/{election_id}/results")
    ).json()
    assert results["final"] is True
    assert all(r["elected"] is False for r in results["results"])

    reps = (await client.get("/api/governance/representatives")).json()
    assert reps == []


# === Papeletas firmadas (ROADMAP 3.2 / 3.3) ===

from eth_account.messages import encode_typed_data  # noqa: E402

from app.services import ballot_service  # noqa: E402


def _sign_election_ballot(account, election_id, candidate, nonce):
    encoded = encode_typed_data(
        full_message=ballot_service.election_typed_data(
            election_id, account.address.lower(), candidate, nonce
        )
    )
    return account.sign_message(encoded).signature.hex()


async def _open_voting_election(client):
    """Elección con candidatura registrada y en período de votación."""
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    election_id = (await _create_election(client)).json()["id"]
    await _nominate(client, election_id, ADDR_B)
    # Adelantar a la fase de votación.
    await elections_collection().update_one(
        {"id": election_id},
        {
            "$set": {
                "nominations_end_at": datetime.now(timezone.utc) - timedelta(days=1)
            }
        },
    )
    return election_id


async def test_signed_election_ballot_is_persisted_and_verifiable(client, monkeypatch):
    """Criterio de 3.2: un tercero recomputa el resultado sin confiar en el servidor."""
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", True)
    election_id = await _open_voting_election(client)
    headers = await _sign_in(client, _ACCOUNT_A)
    nonce = "eleccion-nonce-1"
    signature = _sign_election_ballot(_ACCOUNT_A, election_id, ADDR_B, nonce)

    response = await client.post(
        f"/api/governance/elections/{election_id}/vote",
        json={
            "voter_address": ADDR_A,
            "candidate_address": ADDR_B,
            "nonce": nonce,
            "signature": signature,
        },
        headers=headers,
    )
    assert response.json()["ok"] is True

    evidence = (
        await client.get(f"/api/governance/elections/{election_id}/ballots")
    ).json()

    assert len(evidence) == 1
    assert evidence[0]["signature"] == signature
    assert evidence[0]["signature_scheme"] == "EIP-712"
    assert evidence[0]["signature_valid"] is True
    assert evidence[0]["chain_id"] == settings.SIWE_CHAIN_ID


async def test_replayed_election_nonce_is_rejected(client, monkeypatch):
    """Criterio de 3.3: reenviar un voto firmado da error."""
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", True)
    first_election = await _open_voting_election(client)
    headers = await _sign_in(client, _ACCOUNT_A)
    nonce = "nonce-reutilizado"

    first = await client.post(
        f"/api/governance/elections/{first_election}/vote",
        json={
            "voter_address": ADDR_A,
            "candidate_address": ADDR_B,
            "nonce": nonce,
            "signature": _sign_election_ballot(
                _ACCOUNT_A, first_election, ADDR_B, nonce
            ),
        },
        headers=headers,
    )
    assert first.json()["ok"] is True

    # Otra elección, mismo votante y mismo nonce: el nonce ya está gastado.
    second_election = (await _create_election(client, title="Segunda elección")).json()[
        "id"
    ]
    await _nominate(client, second_election, ADDR_B)
    await elections_collection().update_one(
        {"id": second_election},
        {
            "$set": {
                "nominations_end_at": datetime.now(timezone.utc) - timedelta(days=1)
            }
        },
    )

    replay = await client.post(
        f"/api/governance/elections/{second_election}/vote",
        json={
            "voter_address": ADDR_A,
            "candidate_address": ADDR_B,
            "nonce": nonce,
            "signature": _sign_election_ballot(
                _ACCOUNT_A, second_election, ADDR_B, nonce
            ),
        },
        headers=headers,
    )

    assert replay.status_code == 409
    assert "ya fue usada" in replay.json()["detail"]


async def test_a_proposal_signature_cannot_be_used_as_an_election_vote(
    client, monkeypatch
):
    """Separación de dominio: el primaryType entra en el structHash.

    Sin ella, quien firmara "a favor" en una propuesta estaría firmando
    también un voto en cualquier elección con el mismo nonce.
    """
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", True)
    election_id = await _open_voting_election(client)
    headers = await _sign_in(client, _ACCOUNT_A)
    nonce = "nonce-cruzado"

    # Firma con el tipo de PROPUESTA, enviada como voto de elección.
    proposal_signature = _ACCOUNT_A.sign_message(
        encode_typed_data(
            full_message=ballot_service.typed_data(election_id, ADDR_A, ADDR_B, nonce)
        )
    ).signature.hex()

    response = await client.post(
        f"/api/governance/elections/{election_id}/vote",
        json={
            "voter_address": ADDR_A,
            "candidate_address": ADDR_B,
            "nonce": nonce,
            "signature": proposal_signature,
        },
        headers=headers,
    )

    assert response.status_code == 401


async def test_signature_from_another_wallet_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", True)
    election_id = await _open_voting_election(client)
    headers = await _sign_in(client, _ACCOUNT_A)
    nonce = "nonce-ajeno"

    # Firma de C, enviada como si fuera de A.
    foreign = _sign_election_ballot(_ACCOUNT_C, election_id, ADDR_B, nonce)

    response = await client.post(
        f"/api/governance/elections/{election_id}/vote",
        json={
            "voter_address": ADDR_A,
            "candidate_address": ADDR_B,
            "nonce": nonce,
            "signature": foreign,
        },
        headers=headers,
    )

    assert response.status_code == 401


async def test_election_ballot_schema_is_served_and_distinct(client):
    """El cliente no debe mantener una copia manual del schema."""
    schema = (await client.get("/api/governance/elections/ballot-schema")).json()
    proposal_schema = (await client.get("/api/governance/ballot-schema")).json()

    assert schema["primaryType"] == "ElectionBallot"
    assert proposal_schema["primaryType"] == "Ballot"
    assert "candidate" in str(schema["types"]["ElectionBallot"])
