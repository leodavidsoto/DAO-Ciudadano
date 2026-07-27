"""
Integrity guarantees found by the 27-07-2026 audit pass (N-4…N-9).

These cover the invariants that the *indexes* and fail-closed paths enforce,
not just the friendly pre-checks in the routers: a pre-check that two
concurrent requests can both pass is not a guarantee.
"""
import asyncio

import pytest

from app.core.config import settings
from app.core.database import Database

ADDR_A = "0x" + "aa" * 20
ADDR_B = "0x" + "bb" * 20
ADDR_C = "0x" + "cc" * 20


async def _mint(client, address):
    return await client.post("/api/membership/mint", json={
        "wallet_address": address,
        "assurance_level": "AL2",
        "doc_hash": f"0xdoc{address[-8:]}",
    })


# === N-7: los índices de integridad existen ===

async def test_required_integrity_indexes_exist(client):
    """The unique indexes are the real guarantee; assert they were created."""
    db = Database.get_db()
    expected = {
        "members": [("wallet_address",), ("token_id",)],
        "votes": [("proposal_id", "voter_address")],
        "candidacies": [("election_id", "candidate_address")],
        "election_votes": [("election_id", "voter_address")],
        "representatives": [("election_id", "address")],
    }
    for collection, key_sets in expected.items():
        info = await db[collection].index_information()
        unique_keys = {
            tuple(k for k, _ in spec["key"])
            for spec in info.values() if spec.get("unique")
        }
        for keys in key_sets:
            assert keys in unique_keys, (
                f"Falta índice único {keys} en {collection}: {unique_keys}"
            )


# === N-4: token_id único ===

async def test_token_ids_are_unique_across_members(client):
    for addr in (ADDR_A, ADDR_B, ADDR_C):
        assert (await _mint(client, addr)).json()["ok"] is True

    db = Database.get_db()
    ids = [m["token_id"] async for m in db["members"].find({})]
    assert len(ids) == len(set(ids)), f"token_id duplicado: {ids}"


async def test_concurrent_mints_get_distinct_token_ids(client):
    """Concurrent mints must not collide on token_id (N-4)."""
    results = await asyncio.gather(
        _mint(client, ADDR_A), _mint(client, ADDR_B), _mint(client, ADDR_C),
    )
    assert all(r.json()["ok"] for r in results)
    token_ids = [r.json()["token_id"] for r in results]
    assert len(set(token_ids)) == 3, f"colisión: {token_ids}"


# === N-5: un voto por miembro y propuesta ===

async def _proposal(client, creator):
    return (await client.post("/api/governance/proposals", json={
        "title": "Propuesta de prueba",
        "description": "Descripción suficientemente larga para pasar la validación.",
        "category": "general",
        "creator_address": creator,
        "duration_days": 7,
    })).json()["id"]


async def test_double_vote_is_rejected(client):
    await _mint(client, ADDR_A)
    pid = await _proposal(client, ADDR_A)

    first = await client.post("/api/governance/vote", json={
        "proposal_id": pid, "voter_address": ADDR_A, "vote": "for"})
    second = await client.post("/api/governance/vote", json={
        "proposal_id": pid, "voter_address": ADDR_A, "vote": "against"})

    assert first.json()["ok"] is True
    assert second.json()["ok"] is False

    db = Database.get_db()
    ballots = await db["votes"].count_documents({"proposal_id": pid})
    assert ballots == 1, "se registró más de una papeleta"


async def test_ballot_count_matches_proposal_counters(client):
    """Counters must never drift from the immutable ballots."""
    for addr in (ADDR_A, ADDR_B):
        await _mint(client, addr)
    pid = await _proposal(client, ADDR_A)

    for addr in (ADDR_A, ADDR_B):
        await client.post("/api/governance/vote", json={
            "proposal_id": pid, "voter_address": addr, "vote": "for"})

    db = Database.get_db()
    ballots = [b async for b in db["votes"].find({"proposal_id": pid})]
    proposal = await db["proposals"].find_one({"id": pid})
    assert proposal["votes_for"] == sum(b["weight"] for b in ballots)


# === N-9: liveness falla cerrado ===

async def test_liveness_fails_closed_without_provider(client, monkeypatch):
    """Without an API key there is no evidence: must not return ok=true."""
    monkeypatch.setattr(settings, "EMERGENT_LLM_KEY", None, raising=False)

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = await client.post(
        "/api/auth/liveness",
        files={"file": ("selfie.png", png, "image/png")},
    )
    body = response.json()
    assert body["ok"] is False, "el liveness aceptó sin proveedor configurado"
    assert body.get("score") != 0.85, "sigue devolviendo el score fabricado"


# === N-8: las excepciones no se filtran ===

async def test_errors_do_not_leak_internals(client):
    """Client-facing errors must not carry driver/infra detail."""
    response = await client.post("/api/auth/register", json={
        "rut": "no-es-un-rut", "email": "x@y.cl",
        "nombre": "A", "apellido": "B",
    })
    detail = str(response.json())
    for leak in ("Traceback", "mongodb://", "mongomock", "motor", "pymongo"):
        assert leak not in detail, f"la respuesta filtra '{leak}'"


# === Arranque no bloqueante vs garantías (reconciliación con el PR #2) ===

async def test_writes_are_refused_while_indexes_are_missing(client):
    """Startup does not block on index creation, so the guarantee moves here.

    Without the unique indexes the router pre-checks are only friendly
    messages that two concurrent requests can both pass, so writes must be
    refused (503) rather than accepted unprotected.
    """
    original_ready = Database._indexes_ready
    original_missing = list(Database._missing_required_indexes)
    try:
        Database._indexes_ready = False
        Database._missing_required_indexes = ["members.wallet_address"]

        response = await _mint(client, ADDR_A)
        assert response.status_code == 503
        assert "integridad" in response.json()["detail"].lower()
    finally:
        Database._indexes_ready = original_ready
        Database._missing_required_indexes = original_missing


async def test_reads_still_work_while_indexes_are_missing(client):
    """Only writes are gated: a degraded service must stay readable."""
    original_ready = Database._indexes_ready
    try:
        Database._indexes_ready = False
        Database._missing_required_indexes = ["members.wallet_address"]

        assert (await client.get("/api/dashboard/stats")).status_code == 200
        assert (await client.get("/api/governance/proposals")).status_code == 200
    finally:
        Database._indexes_ready = original_ready
        Database._missing_required_indexes = []


async def test_health_reports_integrity_state(client):
    """/health must distinguish healthy from degraded, not just say 'healthy'."""
    healthy = (await client.get("/health")).json()
    assert healthy["status"] == "healthy"
    assert healthy["integrity"]["ready"] is True

    original = Database._indexes_ready
    try:
        Database._indexes_ready = False
        Database._missing_required_indexes = ["votes.compound"]
        degraded = (await client.get("/health")).json()
        assert degraded["status"] == "degraded"
        assert "votes.compound" in degraded["integrity"]["missing_required_indexes"]
    finally:
        Database._indexes_ready = original
        Database._missing_required_indexes = []
