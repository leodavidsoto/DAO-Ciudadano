"""
Antifraude conectado a los endpoints (ROADMAP 3.4).

El código del detector existía desde hacía tiempo pero nadie comprobaba que
siguiera *llamándose*: un `import` huérfano fue exactamente el hallazgo A-4.
Estos tests van por HTTP, así que fallan si alguien quita la llamada aunque el
detector siga siendo correcto por dentro.

Cubren las tres heurísticas que quedaron activas:

* voto rápido (`FraudDetector.check_rapid_voting`) en propuestas y elecciones,
* ciclos de delegación sobre el grafo real,
* profundidad máxima de cadena, que es lo único que aportaba en exclusiva la
  copia en memoria eliminada en 3.8.
"""

from datetime import datetime, timedelta, timezone

import pytest

from eth_account import Account

from app.core.database import elections_collection
from app.core.security_middleware import FraudDetector, fraud_detector
from app.services.governance_service import MAX_DELEGATION_DEPTH
from tests.test_governance import (
    ADDR_A,
    ADDR_B,
    ADDR_C,
    ADDR_D,
    _create_proposal,
    _delegate,
    _headers_for,
    _mint_member,
    _sign_in,
    _vote,
)

# Quinta wallet: con solo cuatro, una cadena lo bastante profunda como para
# disparar la heurística de profundidad se cierra sobre sí misma y el
# veredicto correcto pasa a ser "ciclo".
ACCOUNT_E = Account.from_key("0x" + "e5" * 32)
ADDR_E = ACCOUNT_E.address.lower()


async def _members(client, *addresses):
    for address in addresses:
        await _mint_member(client, address)


async def _member_e(client):
    """Alta de la quinta wallet; devuelve sus headers de sesión."""
    headers = await _sign_in(client, ACCOUNT_E)
    response = await client.post(
        "/api/membership/mint",
        json={
            "wallet_address": ADDR_E,
            "assurance_level": "AL2",
            "doc_hash": f"0xdoc{ADDR_E[-8:]}",
        },
        headers=headers,
    )
    assert response.json()["ok"] is True, response.json()
    return headers


async def _deep_chain(client):
    """Construye b->a, c->b, d->c: tres saltos por detrás de `d`."""
    await _members(client, ADDR_A, ADDR_B, ADDR_C, ADDR_D)
    for delegator, delegate in ((ADDR_B, ADDR_A), (ADDR_C, ADDR_B), (ADDR_D, ADDR_C)):
        response = await _delegate(client, delegator, delegate)
        assert response.json()["ok"] is True, response.json()


# === Voto rápido ===


async def test_rapid_voting_is_blocked_at_the_documented_threshold(client):
    """El umbral es MAX_VOTES_PER_WINDOW; el voto siguiente recibe 429."""
    await _mint_member(client, ADDR_A)
    headers = await _headers_for(client, ADDR_A)
    limit = FraudDetector.MAX_VOTES_PER_WINDOW
    proposals = [
        (
            await _create_proposal(
                client, title=f"Propuesta número {i}", headers=headers
            )
        ).json()["id"]
        for i in range(limit + 1)
    ]

    allowed = [
        await _vote(client, ADDR_A, proposals[i], "for", headers=headers)
        for i in range(limit)
    ]
    blocked = await _vote(client, ADDR_A, proposals[limit], "for", headers=headers)

    assert all(r.json()["ok"] is True for r in allowed)
    assert blocked.status_code == 429
    assert "sospechosa" in blocked.json()["detail"]


async def test_rapid_voting_counts_per_voter_not_per_proposal(client):
    """Rotar el proposal_id no devuelve la cuota: si no, no limita nada."""
    await _members(client, ADDR_A, ADDR_B)
    headers_a = await _headers_for(client, ADDR_A)
    headers_b = await _headers_for(client, ADDR_B)
    limit = FraudDetector.MAX_VOTES_PER_WINDOW
    proposals = [
        (
            await _create_proposal(
                client, title=f"Propuesta rotada {i}", headers=headers_a
            )
        ).json()["id"]
        for i in range(limit + 1)
    ]

    for i in range(limit):
        await _vote(client, ADDR_A, proposals[i], "for", headers=headers_a)

    exhausted = await _vote(client, ADDR_A, proposals[limit], "for", headers=headers_a)
    # Otra dirección conserva su propia cuota: el límite es por votante.
    other_voter = await _vote(client, ADDR_B, proposals[0], "for", headers=headers_b)

    assert exhausted.status_code == 429
    assert other_voter.json()["ok"] is True


async def test_election_votes_share_the_same_heuristic(client):
    """La ventana es por votante, así que agotarla en propuestas frena la elección."""
    await _members(client, ADDR_A, ADDR_B)
    headers = await _headers_for(client, ADDR_A)
    limit = FraudDetector.MAX_VOTES_PER_WINDOW
    for i in range(limit):
        proposal_id = (
            await _create_proposal(
                client, title=f"Propuesta previa {i}", headers=headers
            )
        ).json()["id"]
        await _vote(client, ADDR_A, proposal_id, "for", headers=headers)

    election = await client.post(
        "/api/governance/elections",
        json={
            "title": "Elección con la cuota agotada",
            "description": "Elegimos representantes para el próximo período.",
            "seats": 1,
            "nominations_days": 7,
            "voting_days": 7,
            "term_months": 12,
            "creator_address": ADDR_A,
        },
        headers=headers,
    )
    election_id = election.json()["id"]
    await client.post(
        f"/api/governance/elections/{election_id}/candidacies",
        json={
            "candidate_address": ADDR_B,
            "statement": "Mi programa: participación, transparencia y cuentas claras.",
        },
        headers=await _headers_for(client, ADDR_B),
    )
    await elections_collection().update_one(
        {"id": election_id},
        {
            "$set": {
                "nominations_end_at": datetime.now(timezone.utc) - timedelta(hours=1)
            }
        },
    )

    response = await client.post(
        f"/api/governance/elections/{election_id}/vote",
        json={"voter_address": ADDR_A, "candidate_address": ADDR_B},
        headers=headers,
    )

    assert response.status_code == 429


async def test_detector_without_store_fails_closed(client, monkeypatch):
    """Sin almacén no se vota: dejar pasar desactivaría el antifraude en silencio."""
    await _mint_member(client, ADDR_A)
    headers = await _headers_for(client, ADDR_A)
    proposal_id = (await _create_proposal(client, headers=headers)).json()["id"]
    monkeypatch.setattr(fraud_detector, "_store", None)

    response = await _vote(client, ADDR_A, proposal_id, "for", headers=headers)

    assert response.status_code == 429


# === Grafo de delegaciones ===


async def test_delegation_cycle_is_rejected_over_the_stored_graph(client):
    """a->b->c y luego c->a: el ciclo solo se ve recorriendo la base."""
    await _members(client, ADDR_A, ADDR_B, ADDR_C)
    assert (await _delegate(client, ADDR_A, ADDR_B)).json()["ok"] is True
    assert (await _delegate(client, ADDR_B, ADDR_C)).json()["ok"] is True

    closing = await _delegate(client, ADDR_C, ADDR_A)

    assert closing.json()["ok"] is False
    assert "circular" in closing.json()["error"]


async def test_too_deep_chain_is_rejected_without_calling_it_a_cycle(client):
    """Una cadena larga no es un ciclo, y el mensaje no debe decir que lo es."""
    await _deep_chain(client)
    headers_e = await _member_e(client)

    response = await _delegate(client, ADDR_E, ADDR_D, headers=headers_e)
    body = response.json()

    assert body["ok"] is False
    assert "circular" not in body["error"]
    assert str(MAX_DELEGATION_DEPTH) in body["error"]


async def test_a_chain_within_the_limit_is_still_allowed(client):
    """El corte está en la profundidad documentada, no antes."""
    await _members(client, ADDR_A, ADDR_B, ADDR_C)
    assert (await _delegate(client, ADDR_B, ADDR_A)).json()["ok"] is True

    # c -> b, con un solo salto por detrás de b, sigue siendo admisible.
    response = await _delegate(client, ADDR_C, ADDR_B)

    assert response.json()["ok"] is True


@pytest.mark.parametrize("reason", ["cycle", "depth"])
async def test_service_distinguishes_the_two_rejections(client, reason):
    """El servicio devuelve el motivo; el router es quien lo redacta."""
    from app.services.governance_service import governance_service

    if reason == "cycle":
        await _members(client, ADDR_A, ADDR_B, ADDR_C)
        await _delegate(client, ADDR_A, ADDR_B)
        await _delegate(client, ADDR_B, ADDR_C)
        verdict = await governance_service.delegation_block_reason(ADDR_C, ADDR_A)
    else:
        await _deep_chain(client)
        await _member_e(client)
        verdict = await governance_service.delegation_block_reason(ADDR_E, ADDR_D)

    assert verdict == reason
