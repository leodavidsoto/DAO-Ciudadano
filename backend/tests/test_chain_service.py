"""
Minteo on-chain (ROADMAP 1.5): app/services/chain_service.py.

Sin RPC/contrato/llave reales en el entorno de test, is_configured() debe
ser False -- y por lo tanto blockchain_service.mint_sbt() debe seguir
cayendo al modo demo (probado en test_membership.py, tx_hash siempre None).
Este archivo cubre chain_service.py de forma aislada.
"""
from app.core.config import settings
from app.services import chain_service


def test_is_configured_false_when_nothing_set(monkeypatch):
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "")
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "")
    assert chain_service.is_configured() is False


def test_is_configured_false_when_partially_set(monkeypatch):
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "")  # falta la llave
    assert chain_service.is_configured() is False


def test_is_configured_true_when_fully_set(monkeypatch):
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "0x" + "22" * 32)
    assert chain_service.is_configured() is True


def test_mint_raises_when_not_configured(monkeypatch):
    import pytest
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "")
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "")
    with pytest.raises(chain_service.ChainMintError):
        chain_service.mint_sbt_onchain("0x" + "ab" * 20, "0x" + "00" * 32, "AL2")
