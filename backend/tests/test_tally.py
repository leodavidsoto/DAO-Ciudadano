"""
Recuento reconstruible y atomicidad (ROADMAP 3.10).

Dos cosas distintas que la tarea junta:

1. **Que una caída no produzca divergencia.** Votar es una sola escritura de
   un documento y los totales se derivan al leer, así que no hay contador que
   pueda quedar desincronizado. Lo que sí escribía varios documentos era la
   finalización de una elección; aquí se reproduce una caída a mitad y se
   comprueba que la siguiente ejecución la termina.

2. **Que el resultado se pueda reconstruir desde las firmas válidas.** Los
   endpoints `/audit` recomputan el recuento verificando cada firma EIP-712 y
   dicen en qué se diferencia de lo publicado.
"""
from datetime import datetime, timedelta, timezone

from eth_account import Account
from eth_account.messages import encode_typed_data

from app.core.config import settings
from app.core.database import representatives_collection, votes_collection
from app.services import ballot_service
from app.services.governance_service import governance_service
from tests.test_governance import (
    ACCOUNT_A,
    ACCOUNT_B,
    ADDR_A,
    ADDR_B,
    ADDR_C,
    _create_proposal,
    _delegate,
    _headers_for,
    _mint_member,
    _vote,
)
from tests.test_elections import (
    _close_election,
    _create_election,
    _nominate,
    _open_voting,
)
from tests.test_elections import _mint_member as _mint_election_member


def _sign_proposal_ballot(account, proposal_id, choice, nonce):
    data = ballot_service.typed_data(
        proposal_id, account.address.lower(), choice, nonce, settings.SIWE_CHAIN_ID
    )
    signed = Account.sign_message(
        encode_typed_data(full_message=data), private_key=account.key
    )
    return signed.signature.hex()


async def _signed_vote(client, account, proposal_id, choice, nonce):
    headers = await _headers_for(client, account.address.lower())
    signature = _sign_proposal_ballot(account, proposal_id, choice, nonce)
    return await client.post("/api/governance/vote", json={
        "proposal_id": proposal_id,
        "voter_address": account.address.lower(),
        "vote": choice,
        "nonce": nonce,
        "signature": signature,
    }, headers=headers)


# === Reconstrucción desde firmas válidas ===

async def test_audit_reproduces_the_published_tally(client):
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]
    assert (await _signed_vote(client, ACCOUNT_A, proposal_id, "for", "n1")).json()["ok"]
    assert (await _signed_vote(client, ACCOUNT_B, proposal_id, "against", "n2")).json()["ok"]

    audit = (await client.get(f"/api/governance/proposals/{proposal_id}/audit")).json()

    assert audit["matches"] is True
    assert audit["verified_tally"]["votes_for"] == 1
    assert audit["verified_tally"]["votes_against"] == 1
    assert audit["verified_tally"] == audit["published_tally"]
    assert audit["ballots_counted"] == 2
    assert audit["rejected"] == []


async def test_a_tampered_ballot_is_not_counted(client):
    """Si alguien reescribe una papeleta en la base, la firma deja de cuadrar."""
    await _mint_member(client, ADDR_A)
    proposal_id = (await _create_proposal(client)).json()["id"]
    await _signed_vote(client, ACCOUNT_A, proposal_id, "for", "n1")

    # Manipulación directa en Mongo: el voto pasa de "for" a "against".
    await votes_collection().update_one(
        {"proposal_id": proposal_id, "voter_address": ADDR_A},
        {"$set": {"vote": "against"}},
    )

    audit = (await client.get(f"/api/governance/proposals/{proposal_id}/audit")).json()

    assert audit["matches"] is False  # el publicado ya no se sostiene
    assert audit["verified_tally"]["votes_against"] == 0
    assert audit["ballots_counted"] == 0
    assert "no corresponde" in audit["rejected"][0]["reason"]


async def test_an_inflated_weight_is_detected(client):
    """El peso se persiste con su composición (P-61): inflarlo se nota."""
    await _mint_member(client, ADDR_A)
    proposal_id = (await _create_proposal(client)).json()["id"]
    await _signed_vote(client, ACCOUNT_A, proposal_id, "for", "n1")

    await votes_collection().update_one(
        {"proposal_id": proposal_id, "voter_address": ADDR_A},
        {"$set": {"weight": 99}},
    )

    audit = (await client.get(f"/api/governance/proposals/{proposal_id}/audit")).json()

    assert audit["matches"] is False
    assert "peso" in audit["rejected"][0]["reason"]


async def test_delegated_weight_survives_the_audit(client):
    """Un peso legítimo de 2 (voto propio + un delegante) debe verificar."""
    await _mint_member(client, ADDR_A)
    await _mint_member(client, ADDR_B)
    proposal_id = (await _create_proposal(client)).json()["id"]
    assert (await _delegate(client, ADDR_B, ADDR_A)).json()["ok"] is True

    assert (await _signed_vote(client, ACCOUNT_A, proposal_id, "for", "n1")).json()["weight"] == 2

    audit = (await client.get(f"/api/governance/proposals/{proposal_id}/audit")).json()

    assert audit["matches"] is True
    assert audit["verified_tally"]["votes_for"] == 2
    assert audit["rejected"] == []


async def test_unsigned_ballots_are_reported_as_such(client):
    """El piloto admite papeletas sin firma; el auditor no las disfraza."""
    await _mint_member(client, ADDR_A)
    proposal_id = (await _create_proposal(client)).json()["id"]
    await _vote(client, ADDR_A, proposal_id, "for")  # sin firma

    audit = (await client.get(f"/api/governance/proposals/{proposal_id}/audit")).json()

    assert audit["ballots_unsigned"] == 1
    assert audit["signed_ballots_required"] is False
    assert audit["matches"] is True


async def test_unsigned_ballots_are_rejected_when_signatures_are_required(
    client, monkeypatch
):
    await _mint_member(client, ADDR_A)
    proposal_id = (await _create_proposal(client)).json()["id"]
    await _vote(client, ADDR_A, proposal_id, "for")

    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", True)
    audit = (await client.get(f"/api/governance/proposals/{proposal_id}/audit")).json()

    assert audit["ballots_counted"] == 0
    assert audit["rejected"][0]["reason"] == "sin firma"


async def test_audit_of_a_missing_proposal_is_404(client):
    response = await client.get("/api/governance/proposals/no-existe/audit")

    assert response.status_code == 404


async def test_audit_is_public(client):
    """Un resultado que solo verifica quien tiene sesión no es verificable."""
    await _mint_member(client, ADDR_A)
    proposal_id = (await _create_proposal(client)).json()["id"]
    client.cookies.clear()

    response = await client.get(f"/api/governance/proposals/{proposal_id}/audit")

    assert response.status_code == 200


# === Atomicidad de la finalización de elecciones ===

async def test_a_crash_mid_finalization_is_repaired_on_the_next_run(client):
    """La caída que producía un parlamento incompleto para siempre.

    `insert_many` no es atómico entre documentos: si el proceso muere a mitad,
    quedan algunos escaños escritos. La versión anterior salía sin hacer nada
    en cuanto existía CUALQUIER representante, así que ese estado parcial se
    volvía permanente.
    """
    for addr in (ADDR_A, ADDR_B, ADDR_C):
        await _mint_election_member(client, addr)
    election_id = (await _create_election(client, seats=3)).json()["id"]
    for addr in (ADDR_A, ADDR_B, ADDR_C):
        await _nominate(client, election_id, addr)
    await _open_voting(election_id)
    for addr in (ADDR_A, ADDR_B, ADDR_C):
        await client.post(
            f"/api/governance/elections/{election_id}/vote",
            json={"voter_address": addr, "candidate_address": addr},
            headers=await _headers_for(client, addr),
        )
    await _close_election(election_id)

    await client.get(f"/api/governance/elections/{election_id}/results")
    assert await representatives_collection().count_documents(
        {"election_id": election_id}
    ) == 3

    # Simula la caída con fidelidad: se escribió UN escaño de los tres y la
    # marca `finalized_at` nunca llegó a escribirse, que es exactamente el
    # estado que deja morir a mitad de la reconciliación.
    from app.core.database import elections_collection

    await representatives_collection().delete_many(
        {"election_id": election_id, "address": {"$in": [ADDR_B, ADDR_C]}}
    )
    await elections_collection().update_one(
        {"id": election_id}, {"$unset": {"finalized_at": ""}}
    )
    assert await representatives_collection().count_documents(
        {"election_id": election_id}
    ) == 1

    # Cualquier lectura posterior reconcilia en vez de dar por bueno lo parcial.
    await client.get(f"/api/governance/elections/{election_id}/results")

    assert await representatives_collection().count_documents(
        {"election_id": election_id}
    ) == 3


async def test_finalization_is_idempotent(client):
    """Reejecutarla no duplica escaños."""
    await _mint_election_member(client, ADDR_A)
    await _mint_election_member(client, ADDR_B)
    election_id = (await _create_election(client, seats=1)).json()["id"]
    await _nominate(client, election_id, ADDR_A)
    await _open_voting(election_id)
    await client.post(
        f"/api/governance/elections/{election_id}/vote",
        json={"voter_address": ADDR_B, "candidate_address": ADDR_A},
        headers=await _headers_for(client, ADDR_B),
    )
    await _close_election(election_id)

    for _ in range(3):
        await client.get(f"/api/governance/elections/{election_id}/results")

    assert await representatives_collection().count_documents(
        {"election_id": election_id}
    ) == 1


async def test_a_stale_representative_is_removed(client):
    """El estado publicado debe ser el derivado, no el que quedó escrito."""
    await _mint_election_member(client, ADDR_A)
    await _mint_election_member(client, ADDR_B)
    election_id = (await _create_election(client, seats=1)).json()["id"]
    await _nominate(client, election_id, ADDR_A)
    await _open_voting(election_id)
    await client.post(
        f"/api/governance/elections/{election_id}/vote",
        json={"voter_address": ADDR_B, "candidate_address": ADDR_A},
        headers=await _headers_for(client, ADDR_B),
    )
    await _close_election(election_id)
    await client.get(f"/api/governance/elections/{election_id}/results")

    # Alguien insertó a mano un representante que nadie eligió.
    await representatives_collection().insert_one({
        "election_id": election_id,
        "address": ADDR_C,
        "votes": 99,
        "term_start": datetime.now(timezone.utc),
        "term_end": datetime.now(timezone.utc) + timedelta(days=365),
    })

    election = await governance_service.sync_election_status(
        {"id": election_id, "status": "closed",
         "voting_end_at": datetime.now(timezone.utc) - timedelta(hours=1),
         "nominations_end_at": datetime.now(timezone.utc) - timedelta(hours=2),
         "seats": 1, "term_months": 12}
    )
    await governance_service.finalize_election(election)

    seated = await representatives_collection().find(
        {"election_id": election_id}
    ).to_list(length=10)
    assert [s["address"] for s in seated] == [ADDR_A]


async def test_election_audit_reproduces_the_published_result(client):
    await _mint_election_member(client, ADDR_A)
    await _mint_election_member(client, ADDR_B)
    election_id = (await _create_election(client, seats=1)).json()["id"]
    await _nominate(client, election_id, ADDR_A)
    await _open_voting(election_id)
    await client.post(
        f"/api/governance/elections/{election_id}/vote",
        json={"voter_address": ADDR_B, "candidate_address": ADDR_A},
        headers=await _headers_for(client, ADDR_B),
    )

    audit = (await client.get(f"/api/governance/elections/{election_id}/audit")).json()

    assert audit["matches"] is True
    assert audit["verified_tally"][ADDR_A] == 1
    assert audit["rejected"] == []
