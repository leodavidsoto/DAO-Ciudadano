"""
Verificación de membresía on-chain (ROADMAP 3.1).

Con MEMBERSHIP_SOURCE=onchain el gate de gobernanza consulta
`hasMembership(address)` en el SBT, con una caché corta por dirección. Aquí se
cubren las tres cosas que importan: que una dirección sin SBT reciba 403, que
la caché evite el viaje al RPC, y que un RPC caído NO se confunda con "no es
miembro" (503, nunca 403).

No se toca la red: `chain_service.has_membership` y el contrato de solo
lectura se sustituyen por dobles.
"""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.config import settings
from app.services import chain_service
from app.services.membership_verifier import (
    MembershipVerificationUnavailable,
    MongoMembershipVerifier,
    OnChainMembershipVerifier,
    clear_membership_cache,
    get_membership_verifier,
)

MEMBER_ACCOUNT = Account.from_key("0x" + "5e" * 32)
OUTSIDER_ACCOUNT = Account.from_key("0x" + "6f" * 32)
MEMBER = MEMBER_ACCOUNT.address.lower()
OUTSIDER = OUTSIDER_ACCOUNT.address.lower()


@pytest.fixture(autouse=True)
def _isolated_cache():
    """La caché es global al proceso: sin esto un test contamina al siguiente."""
    clear_membership_cache()
    yield
    clear_membership_cache()


@pytest.fixture
def onchain(monkeypatch):
    """Fuente de verdad on-chain con un doble del contrato.

    Devuelve el diccionario de miembros y la lista de llamadas registradas,
    para poder afirmar sobre la caché.
    """
    members = {MEMBER: True, OUTSIDER: False}
    calls = []

    def fake_has_membership(wallet_address: str) -> bool:
        calls.append(wallet_address.lower())
        return members.get(wallet_address.lower(), False)

    monkeypatch.setattr(settings, "MEMBERSHIP_SOURCE", "onchain")
    monkeypatch.setattr(chain_service, "has_membership", fake_has_membership)
    return {"members": members, "calls": calls}


async def _sign_in(client, account):
    challenge = await client.post(
        "/api/wallet/challenge", json={"address": account.address}
    )
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


# === chain_service.has_membership ===


def test_has_membership_requires_rpc_and_contract(monkeypatch):
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "")

    with pytest.raises(chain_service.ChainReadError):
        chain_service.has_membership(MEMBER)


def test_has_membership_reads_the_contract(monkeypatch):
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)
    seen = {}

    class _Call:
        def __init__(self, address):
            seen["address"] = address

        def call(self):
            return True

    class _Functions:
        hasMembership = staticmethod(_Call)

    class _Contract:
        functions = _Functions()

    monkeypatch.setattr(chain_service, "_read_only_contract", lambda: _Contract())

    assert chain_service.has_membership(MEMBER) is True
    # El contrato recibe la dirección en formato checksum, no en minúsculas.
    assert seen["address"] == MEMBER_ACCOUNT.address


def test_has_membership_never_turns_an_rpc_failure_into_false(monkeypatch):
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)

    def explode():
        raise ConnectionError("RPC caído")

    monkeypatch.setattr(chain_service, "_read_only_contract", explode)

    with pytest.raises(chain_service.ChainReadError):
        chain_service.has_membership(MEMBER)


# === OnChainMembershipVerifier + caché ===


async def test_onchain_verifier_answers_from_the_contract(onchain):
    verifier = get_membership_verifier()

    assert isinstance(verifier, OnChainMembershipVerifier)
    assert await verifier.is_member(MEMBER) is True
    assert await verifier.is_member(OUTSIDER) is False


async def test_repeated_checks_hit_the_rpc_once(onchain, monkeypatch):
    monkeypatch.setattr(settings, "MEMBERSHIP_CACHE_TTL_SECONDS", 30)
    verifier = OnChainMembershipVerifier()

    for _ in range(5):
        assert await verifier.is_member(MEMBER) is True

    assert onchain["calls"] == [MEMBER]


async def test_negative_answers_are_cached_too(onchain, monkeypatch):
    monkeypatch.setattr(settings, "MEMBERSHIP_CACHE_TTL_SECONDS", 30)
    verifier = OnChainMembershipVerifier()

    assert await verifier.is_member(OUTSIDER) is False
    assert await verifier.is_member(OUTSIDER) is False

    assert onchain["calls"] == [OUTSIDER]


async def test_cache_can_be_disabled(onchain, monkeypatch):
    monkeypatch.setattr(settings, "MEMBERSHIP_CACHE_TTL_SECONDS", 0)
    verifier = OnChainMembershipVerifier()

    await verifier.is_member(MEMBER)
    await verifier.is_member(MEMBER)

    assert onchain["calls"] == [MEMBER, MEMBER]


async def test_minting_invalidates_a_cached_negative_answer(onchain, monkeypatch):
    """Quien acaba de recibir su SBT no debe seguir viendo 403 por la caché."""
    monkeypatch.setattr(settings, "MEMBERSHIP_CACHE_TTL_SECONDS", 30)
    from app.services.membership_verifier import invalidate_cached_membership

    verifier = OnChainMembershipVerifier()
    assert await verifier.is_member(OUTSIDER) is False

    onchain["members"][OUTSIDER] = True
    assert await verifier.is_member(OUTSIDER) is False  # todavía cacheado

    invalidate_cached_membership(OUTSIDER)
    assert await verifier.is_member(OUTSIDER) is True


async def test_cache_entry_expires(onchain, monkeypatch):
    monkeypatch.setattr(settings, "MEMBERSHIP_CACHE_TTL_SECONDS", 30)
    verifier = OnChainMembershipVerifier()
    assert await verifier.is_member(MEMBER) is True

    # Avanza el reloj monotónico más allá del TTL en vez de dormir.
    from app.services import membership_verifier as module

    real_monotonic = module.time.monotonic
    monkeypatch.setattr(module.time, "monotonic", lambda: real_monotonic() + 31)

    assert await verifier.is_member(MEMBER) is True
    assert onchain["calls"] == [MEMBER, MEMBER]


async def test_malformed_address_is_not_a_chain_error(onchain):
    verifier = OnChainMembershipVerifier()

    assert await verifier.is_member("no-es-una-direccion") is False
    assert onchain["calls"] == []


async def test_unreachable_chain_raises_instead_of_denying(monkeypatch):
    def unavailable(wallet_address):
        raise chain_service.ChainReadError("RPC caído")

    monkeypatch.setattr(settings, "MEMBERSHIP_SOURCE", "onchain")
    monkeypatch.setattr(chain_service, "has_membership", unavailable)

    with pytest.raises(MembershipVerificationUnavailable):
        await OnChainMembershipVerifier().is_member(MEMBER)


# === Gate de gobernanza extremo a extremo ===


async def test_vote_without_sbt_is_rejected_with_403(client, onchain):
    headers = await _sign_in(client, MEMBER_ACCOUNT)
    proposal = await client.post(
        "/api/governance/proposals",
        json={
            "title": "Propuesta con membresía on-chain",
            "description": "Una descripción suficientemente larga para validar.",
            "creator_address": MEMBER,
            "duration_days": 7,
        },
        headers=headers,
    )
    assert proposal.status_code == 200, proposal.json()

    outsider_headers = await _sign_in(client, OUTSIDER_ACCOUNT)
    response = await client.post(
        "/api/governance/vote",
        json={
            "proposal_id": proposal.json()["id"],
            "voter_address": OUTSIDER,
            "vote": "for",
        },
        headers=outsider_headers,
    )

    assert response.status_code == 403
    assert "membresía activa" in response.json()["detail"]


async def test_proposal_without_sbt_is_rejected_with_403(client, onchain):
    headers = await _sign_in(client, OUTSIDER_ACCOUNT)

    response = await client.post(
        "/api/governance/proposals",
        json={
            "title": "Propuesta de alguien sin SBT",
            "description": "Una descripción suficientemente larga para validar.",
            "creator_address": OUTSIDER,
            "duration_days": 7,
        },
        headers=headers,
    )

    assert response.status_code == 403


async def test_unreachable_chain_answers_503_not_403(client, monkeypatch):
    """Un RPC caído es un fallo del servicio, no una negación de membresía."""

    def unavailable(wallet_address):
        raise chain_service.ChainReadError("RPC caído")

    monkeypatch.setattr(settings, "MEMBERSHIP_SOURCE", "onchain")
    monkeypatch.setattr(chain_service, "has_membership", unavailable)
    headers = await _sign_in(client, MEMBER_ACCOUNT)

    response = await client.post(
        "/api/governance/proposals",
        json={
            "title": "Propuesta con el RPC caído",
            "description": "Una descripción suficientemente larga para validar.",
            "creator_address": MEMBER,
            "duration_days": 7,
        },
        headers=headers,
    )

    assert response.status_code == 503
    assert "problema del servicio" in response.json()["detail"]


# === filter_members: el peso por delegación usa la misma definición ===


async def test_mongo_filter_members_matches_the_single_address_gate(client):
    from app.core.database import members_collection

    # token_id explícito: la colección tiene índice único y dos documentos
    # sin él chocarían por `null`.
    await members_collection().insert_many(
        [
            {"wallet_address": MEMBER, "status": "active", "token_id": 1},
            {"wallet_address": OUTSIDER, "status": "revoked", "token_id": 2},
        ]
    )
    verifier = MongoMembershipVerifier()

    assert await verifier.filter_members([MEMBER, OUTSIDER]) == {MEMBER}
    assert await verifier.is_member(MEMBER) is True
    assert await verifier.is_member(OUTSIDER) is False


async def test_onchain_filter_members_uses_the_contract(onchain):
    verifier = OnChainMembershipVerifier()

    assert await verifier.filter_members([MEMBER, OUTSIDER]) == {MEMBER}


async def test_chain_failure_while_weighing_delegations_is_also_503(
    client, onchain, monkeypatch
):
    """El peso por delegación consulta la misma fuente: no puede degradar a un
    error genérico cuando la cadena se cae a mitad del voto.

    El montaje aísla ese camino: la respuesta del gate para el votante queda
    cacheada y solo la del delegador tiene que ir a la cadena.
    """
    from app.services.membership_verifier import invalidate_cached_membership

    onchain["members"][OUTSIDER] = True  # para poder delegar
    headers = await _sign_in(client, MEMBER_ACCOUNT)
    outsider_headers = await _sign_in(client, OUTSIDER_ACCOUNT)

    proposal = await client.post(
        "/api/governance/proposals",
        json={
            "title": "Propuesta antes de la caída",
            "description": "Una descripción suficientemente larga para validar.",
            "creator_address": MEMBER,
            "duration_days": 7,
        },
        headers=headers,
    )
    assert proposal.status_code == 200

    delegation = await client.post(
        "/api/governance/delegate",
        json={
            "delegator_address": OUTSIDER,
            "delegate_address": MEMBER,
        },
        headers=outsider_headers,
    )
    assert delegation.json()["ok"] is True, delegation.json()

    def unavailable(wallet_address):
        raise chain_service.ChainReadError("RPC caído")

    monkeypatch.setattr(chain_service, "has_membership", unavailable)
    # El votante sigue cacheado como miembro; el delegador no, así que el
    # único punto que toca la cadena es el cálculo del peso.
    invalidate_cached_membership(OUTSIDER)

    response = await client.post(
        "/api/governance/vote",
        json={
            "proposal_id": proposal.json()["id"],
            "voter_address": MEMBER,
            "vote": "for",
        },
        headers=headers,
    )

    assert response.status_code == 503
    assert "problema del servicio" in response.json()["detail"]
