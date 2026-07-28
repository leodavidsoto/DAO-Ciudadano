"""
On-chain minting (ROADMAP 1.5, audit finding C-2).

The property under test is not "web3 was called" but that the backend never
claims a membership exists when the chain did not confirm one. That claim is
the whole reason this finding was critical: the UI showed confetti and a token
number while totalSupply() on Sepolia stayed at 0.
"""
import pytest

from app.core.database import Database
import importlib

# app/services/__init__.py exports the *instance* under the same name, which
# shadows the submodule on a plain import. Reach for the module explicitly.
bs_module = importlib.import_module("app.services.blockchain_service")
from app.services.blockchain_service import blockchain_service
from app.services.chain_service import ChainNotConfigured, chain_service

ADDR = "0x" + "ab" * 20
DOC_HASH = "0x" + "cd" * 32  # 32 bytes, the bytes32 the contract expects


class _FakeChain:
    """Stands in for the contract. Records what it was asked to do."""

    def __init__(self, *, enabled=True, token_id=42, tx="0xfeed", fail=None):
        self.enabled = enabled
        self._token_id = token_id
        self._tx = tx
        self._fail = fail
        self.calls = []

    def mint(self, to, identity_hash_hex, assurance_level, token_uri):
        self.calls.append((to, identity_hash_hex, assurance_level, token_uri))
        if self._fail:
            raise self._fail
        return (self._token_id, self._tx)


@pytest.fixture
def fake_chain(monkeypatch):
    def _install(**kwargs):
        fake = _FakeChain(**kwargs)
        monkeypatch.setattr(bs_module, "chain_service", fake)
        return fake
    return _install


# === Configuración ===

def test_chain_is_disabled_without_configuration(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "", raising=False)
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "", raising=False)
    assert chain_service.enabled is False


def test_using_an_unconfigured_chain_raises(monkeypatch):
    """Fail closed: no silent fallback to a database write."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "", raising=False)
    chain_service._w3 = None
    with pytest.raises(ChainNotConfigured):
        chain_service._connect()


# === Camino demo (sin cadena configurada) ===

async def test_demo_mode_never_fabricates_a_tx_hash(client):
    """Demo mode is acceptable; pretending a transaction happened is not."""
    response = await client.post("/api/membership/mint", json={
        "wallet_address": ADDR, "assurance_level": "AL2", "doc_hash": DOC_HASH,
    })
    body = response.json()
    assert body["ok"] is True
    assert body["tx_hash"] is None


# === Camino on-chain ===

async def test_uses_the_contract_token_id_not_a_local_counter(client, fake_chain):
    """The contract assigns the id; the database only caches it."""
    fake = fake_chain(token_id=777, tx="0xabc123")

    ok, token_id, tx_hash, error = await blockchain_service.mint_sbt(
        wallet_address=ADDR, assurance_level="AL2", doc_hash=DOC_HASH,
    )

    assert (ok, token_id, tx_hash, error) == (True, 777, "0xabc123", None)
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == ADDR.lower()

    stored = await Database.get_db()["members"].find_one({"wallet_address": ADDR.lower()})
    assert stored["token_id"] == 777
    assert stored["tx_hash"] == "0xabc123"


async def test_a_failed_transaction_creates_no_membership(client, fake_chain):
    """The critical property: no silent fallback.

    If the chain rejects the mint, the person must NOT end up with a
    membership record that makes the UI show a token they do not own.
    """
    fake_chain(fail=RuntimeError("execution reverted: AlreadyHasMembership"))

    ok, token_id, tx_hash, error = await blockchain_service.mint_sbt(
        wallet_address=ADDR, assurance_level="AL2", doc_hash=DOC_HASH,
    )

    assert ok is False
    assert token_id is None and tx_hash is None
    assert error and "blockchain" in error.lower()

    count = await Database.get_db()["members"].count_documents({"wallet_address": ADDR.lower()})
    assert count == 0, "se registró una membresía pese a fallar la transacción"


async def test_error_messages_do_not_leak_internals(client, fake_chain):
    """A revert string can carry RPC URLs and internal detail (finding N-8)."""
    fake_chain(fail=RuntimeError("https://secret-rpc.example/key123 failed"))

    _, _, _, error = await blockchain_service.mint_sbt(
        wallet_address=ADDR, assurance_level="AL2", doc_hash=DOC_HASH,
    )
    assert "secret-rpc" not in error
    assert "ref:" in error  # correlation id for the log instead


async def test_confirmed_transaction_without_token_id_is_an_error(client, fake_chain):
    """Receipt parsed but no event: report it, do not invent an id."""
    fake_chain(token_id=None, tx="0xdead")

    ok, token_id, _, error = await blockchain_service.mint_sbt(
        wallet_address=ADDR, assurance_level="AL2", doc_hash=DOC_HASH,
    )
    assert ok is False and token_id is None
    assert "ID del token" in error
