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


class Call:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class Reverts:
    """Una función que el contrato desplegado NO expone."""

    def call(self):
        raise ValueError("execution reverted")


ROOT_MANAGER_ROLE = b"r" * 32


def _fake_chain(
    monkeypatch,
    *,
    scope=12345,
    paused=False,
    balance=1,
    has_root_role=True,
    exposes_scope=True,
):
    """Contrato de mentira que imita a DAOCiudadanaSBT.sol, no a un contrato ideal.

    Deliberadamente NO tiene `MINTER_ROLE()`: el contrato real tampoco. Un
    doble más permisivo que el original es cómo el sondeo llegó a producción
    exigiendo un rol inexistente con el suite en verde.
    """
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "0x" + "22" * 32)
    monkeypatch.setattr(chain_service, "_runtime_cache", None)

    class Functions:
        def membershipScope(self):
            return Call(scope) if exposes_scope else Reverts()

        def paused(self):
            return Call(paused)

        def ROOT_MANAGER_ROLE(self):
            return Call(ROOT_MANAGER_ROLE)

        def hasRole(self, role, account):
            return Call(
                has_root_role and role == ROOT_MANAGER_ROLE and account == "0xminter"
            )

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
            return balance if address == "0xminter" else 0

    class Web3Client:
        eth = Eth()

        @staticmethod
        def is_connected():
            return True

    class Account:
        address = "0xminter"

    monkeypatch.setattr(
        chain_service, "_client", lambda: (Web3Client(), Contract(), Account())
    )


def test_runtime_status_is_ready_against_the_real_contract_abi(monkeypatch):
    """El relevo del minteo no exige ningún rol: la prueba ES la autorización.

    Regresión del P0: el sondeo llamaba a `MINTER_ROLE()`, que
    `DAOCiudadanaSBT.sol` no declara. La llamada revertía, se capturaba como
    "no se pudo validar" y todo minteo real moría en la precondición.
    """
    _fake_chain(monkeypatch)

    result = chain_service.runtime_status()

    assert result["ready"] is True
    assert result["errors"] == []
    assert result["chain_id"] == chain_service.SEPOLIA_CHAIN_ID
    assert result["membership_scope"] == "12345"
    assert result["paused"] is False


def test_runtime_status_rejects_a_contract_without_membership_scope(monkeypatch):
    """La dirección histórica de Sepolia tiene otra ABI: hay que decirlo."""
    _fake_chain(monkeypatch, exposes_scope=False)

    result = chain_service.runtime_status()

    assert result["ready"] is False
    assert any("membershipScope()" in error for error in result["errors"])


def test_runtime_status_reports_a_paused_contract(monkeypatch):
    """`mintMembership` es `whenNotPaused`: minteo pausado, no "fallo de red"."""
    _fake_chain(monkeypatch, paused=True)

    result = chain_service.runtime_status()

    assert result["ready"] is False
    assert result["paused"] is True
    assert any("pausado" in error for error in result["errors"])


def test_runtime_status_requires_gas_but_not_a_role(monkeypatch):
    _fake_chain(monkeypatch, balance=0)

    result = chain_service.runtime_status()

    assert result["ready"] is False
    assert any("saldo" in error for error in result["errors"])


def test_root_manager_role_is_reported_without_blocking_minting(monkeypatch):
    """Sin ROOT_MANAGER_ROLE no se aprueban raíces, pero sí se releva un minteo.

    Un despliegue donde el Safe admin aprueba las raíces a mano es legítimo;
    exigir el rol al relayer lo dejaría sin poder mintear nunca.
    """
    _fake_chain(monkeypatch, has_root_role=False)

    result = chain_service.runtime_status()

    assert result["ready"] is True
    assert result["can_approve_roots"] is False


def _proof_args():
    return {
        "wallet_address": "0x" + "ab" * 20,
        "proof_a": ["1", "2"],
        "proof_b": [["1", "2"], ["3", "4"]],
        "proof_c": ["5", "6"],
        "nullifier_hash": "0x" + "cd" * 32,
        "identity_root": 123,
    }


def test_mint_raises_when_not_configured(monkeypatch):
    import pytest

    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "")
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "")
    with pytest.raises(chain_service.ChainMintError):
        chain_service.mint_with_proof(**_proof_args())


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
        chain_service.mint_with_proof(**_proof_args())


def test_the_failed_precondition_says_what_actually_failed(monkeypatch):
    """El motivo llega al log en vez de un "revisa RPC, red, contrato y rol"."""
    import pytest

    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "0x" + "22" * 32)
    monkeypatch.setattr(
        chain_service,
        "runtime_status",
        lambda: {"ready": False, "errors": ["el contrato de membresía está pausado"]},
    )

    with pytest.raises(chain_service.ChainMintError, match="pausado"):
        chain_service.mint_with_proof(**_proof_args())


def test_tx_hash_is_normalized_to_the_0x_prefix():
    """hexbytes 1.x dejó de prefijar `.hex()`, y un hash sin `0x` no es un hash.

    Ningún explorador lo acepta y el ciudadano no puede seguir su transacción.
    """

    class FakeHexBytes:
        @staticmethod
        def hex():
            return "ab" * 32

    assert chain_service.tx_hash_hex(FakeHexBytes()).startswith("0x")
    assert chain_service.tx_hash_hex("0x" + "ab" * 32) == "0x" + "ab" * 32


# === Lecturas sin llave privada ===


def test_reading_the_chain_does_not_require_a_minter_key(monkeypatch):
    """Las lecturas no necesitan llave privada.

    Exigirla hacía que la emisión de credenciales fallara con "no se pudo leer
    membershipScope()" cuando el único problema era que el relayer no estaba
    configurado — dos cosas sin relación. Se descubrió al leer el contrato
    realmente desplegado en Sepolia.
    """
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://rpc.example")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "ab" * 20)
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "")

    assert chain_service.can_read_chain() is True
    # Enviar transacciones sigue exigiendo la llave.
    assert chain_service.is_configured() is False


def test_reading_still_needs_the_rpc_and_the_contract(monkeypatch):
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "ab" * 20)
    assert chain_service.can_read_chain() is False

    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://rpc.example")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "")
    assert chain_service.can_read_chain() is False
