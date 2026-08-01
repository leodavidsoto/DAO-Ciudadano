"""
Minteo on-chain (ROADMAP 1.5): app/services/chain_service.py.

Sin RPC/contrato/llave reales en el entorno de test, `is_configured()` debe
ser False. `MINT_MODE=onchain` falla cerrado en ese estado; el modo demo solo
se usa cuando fue seleccionado explícitamente. Este archivo cubre la
configuración y el probe de `chain_service.py` de forma aislada.
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


def test_is_configured_rejects_nonempty_but_malformed_values(monkeypatch):
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "not-a-url")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "not-an-address")
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "not-a-key")

    errors = chain_service.configuration_errors()

    assert chain_service.is_configured() is False
    assert set(errors) == {
        "SEPOLIA_RPC_URL",
        "SBT_CONTRACT_ADDRESS",
        "MINTER_PRIVATE_KEY",
    }


def test_production_onchain_rpc_requires_https(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "http://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "0x" + "22" * 32)

    assert chain_service.configuration_errors()["SEPOLIA_RPC_URL"] == (
        "debe usar HTTPS en producción"
    )


def test_runtime_status_checks_chain_contract_role_and_balance(monkeypatch):
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "0x" + "22" * 32)
    monkeypatch.setattr(chain_service, "_runtime_cache", None)

    class Call:
        def __init__(self, value):
            self.value = value

        def call(self):
            return self.value

    class Functions:
        def MINTER_ROLE(self):
            return Call(b"m" * 32)

        def hasRole(self, role, account):
            return Call(role == b"m" * 32 and account == "0xminter")

    class Contract:
        address = "0x" + "11" * 20
        functions = Functions()

    class Eth:
        chain_id = chain_service.SEPOLIA_CHAIN_ID

        @staticmethod
        def get_code(address):
            return b"\x01" if address == Contract.address else b""

        @staticmethod
        def get_balance(address):
            return 1 if address == "0xminter" else 0

    class Web3Client:
        eth = Eth()

        @staticmethod
        def is_connected():
            return True

    class Account:
        address = "0xminter"

    monkeypatch.setattr(
        chain_service,
        "_client",
        lambda: (Web3Client(), Contract(), Account()),
    )

    result = chain_service.runtime_status()

    assert result["ready"] is True
    assert result["chain_id"] == chain_service.SEPOLIA_CHAIN_ID
    assert result["errors"] == []


def test_mint_raises_when_not_configured(monkeypatch):
    import pytest
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "")
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "")
    with pytest.raises(chain_service.ChainMintError):
        chain_service.mint_sbt_onchain("0x" + "ab" * 20, "0x" + "00" * 32, "AL2")


def test_mint_never_uses_client_when_runtime_precondition_fails(monkeypatch):
    import pytest

    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "0x" + "22" * 32)
    monkeypatch.setattr(
        chain_service,
        "runtime_status",
        lambda: {"ready": False, "errors": ["chainId inesperado"]},
    )

    def unexpected_client():
        raise AssertionError("_client must not run after a failed runtime probe")

    monkeypatch.setattr(chain_service, "_client", unexpected_client)

    with pytest.raises(chain_service.ChainMintError, match="precondición operativa"):
        chain_service.mint_sbt_onchain(
            "0x" + "ab" * 20,
            "0x" + "00" * 32,
            "AL2",
        )
