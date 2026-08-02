"""
Transporte ERC-4337 (Bundler + Paymaster).

Lo que se prueba es que **falla cerrado**. La firma de UserOperations no está
implementada porque falta decidir la implementación de cuenta inteligente, y
lo peor que podría hacer este módulo es aparentar que funciona: el EntryPoint
rechazaría las operaciones con `AA24 signature error` después de haber
consumido gas patrocinado.
"""
import pytest

from app.core.config import settings
from app.services import paymaster_service as pm


def test_disabled_by_default():
    """Sin configurar, no se activa: el relayer EOA sigue siendo el camino."""
    assert pm.is_enabled() is False


def test_reports_exactly_what_is_missing():
    errors = pm.configuration_errors()
    assert "BUNDLER_RPC_URL" in errors
    assert "ERC4337_ACCOUNT_ADDRESS" in errors
    # La implementación de cuenta es la decisión que bloquea la firma.
    assert "ERC4337_ACCOUNT_IMPLEMENTATION" in errors


def test_config_refuses_when_incomplete():
    with pytest.raises(pm.PaymasterUnavailable):
        pm.config()


def test_requires_https_bundler(monkeypatch):
    monkeypatch.setattr(settings, "BUNDLER_RPC_URL", "http://bundler.example")
    assert pm.configuration_errors()["BUNDLER_RPC_URL"] == "debe ser HTTPS"


def test_rejects_unknown_entrypoint_version(monkeypatch):
    monkeypatch.setattr(settings, "ERC4337_ENTRYPOINT_VERSION", "0.5")
    assert "ERC4337_ENTRYPOINT_VERSION" in pm.configuration_errors()


def test_backend_refuses_to_sign_user_operations(monkeypatch):
    """El backend NO firma: la Safe es del ciudadano.

    Si firmara, sería custodio — podría mintear membresías a nombre de
    cualquiera sin su consentimiento. Que esto falle es la garantía, no un
    defecto.
    """
    monkeypatch.setattr(settings, "BUNDLER_RPC_URL", "https://bundler.example")
    monkeypatch.setattr(settings, "ERC4337_ACCOUNT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "ERC4337_ACCOUNT_IMPLEMENTATION", "safe")
    monkeypatch.setattr(settings, "SAFE_4337_MODULE_ADDRESS", "0x" + "22" * 20)

    with pytest.raises(pm.PaymasterUnavailable) as exc:
        pm.sign_user_operation({"sender": "0x" + "11" * 20})
    assert "no firma" in str(exc.value).lower()


def test_configuring_an_owner_key_is_reported_as_an_error(monkeypatch):
    """Tener SAFE_OWNER_PRIVATE_KEY configurada es señal de alarma.

    No se usa en ningún camino; que exista sugiere que alguien pretende que el
    servidor custodie Safes ajenas.
    """
    monkeypatch.setattr(settings, "ERC4337_ACCOUNT_IMPLEMENTATION", "safe")
    monkeypatch.setattr(settings, "SAFE_OWNER_PRIVATE_KEY", "0x" + "c3" * 32)

    errors = pm.configuration_errors()
    assert "SAFE_OWNER_PRIVATE_KEY" in errors
    assert "custodio" in errors["SAFE_OWNER_PRIVATE_KEY"]


def test_mint_refuses_while_disabled():
    with pytest.raises(pm.PaymasterUnavailable):
        pm.mint_via_user_operation(
            wallet_address="0x" + "11" * 20,
            proof_a=["1", "2"],
            proof_b=[["1", "2"], ["3", "4"]],
            proof_c=["5", "6"],
            nullifier_hash="0x" + "ab" * 32,
            identity_root=1,
        )


def test_status_declares_the_backend_is_not_custodial():
    """El contrato de API debe decir que el servidor no firma ni custodia."""
    status = pm.status()
    assert status["enabled"] is False
    assert status["custodial"] is False
    assert status["signing_implemented"] is False
    assert status["verified_against_bundler"] is False


def test_calldata_uses_the_real_contract_abi():
    """El selector debe salir del ABI, no escribirse a mano."""
    calldata = pm.build_mint_calldata(
        to="0x" + "11" * 20,
        proof_a=[1, 2],
        proof_b=[[1, 2], [3, 4]],
        proof_c=[5, 6],
        nullifier_hash="0x" + "ab" * 32,
        identity_root=7,
    )
    assert calldata.startswith("0x")
    # 4 bytes de selector + 6 argumentos codificados (bytes32 y arreglos fijos).
    assert len(calldata) > 8 + 64 * 6
