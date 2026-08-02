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


def test_unsupported_account_implementation_fails_loudly(monkeypatch):
    """Solo 'safe' está implementada.

    SimpleAccount y Kernel firman de otra forma: aceptarlas produciría firmas
    que el módulo rechaza con AA24 tras pagar la simulación, en vez de un
    error claro aquí.
    """
    monkeypatch.setattr(settings, "BUNDLER_RPC_URL", "https://bundler.example")
    monkeypatch.setattr(settings, "ERC4337_ACCOUNT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "ERC4337_ACCOUNT_IMPLEMENTATION", "kernel")

    # Se rechaza ya en la validación de configuración —antes de intentar
    # firmar— y el error nombra la variable culpable.
    assert "ERC4337_ACCOUNT_IMPLEMENTATION" in pm.configuration_errors()
    with pytest.raises(pm.PaymasterUnavailable) as exc:
        pm.sign_user_operation({"sender": "0x" + "11" * 20})
    assert "ERC4337_ACCOUNT_IMPLEMENTATION" in str(exc.value)


def test_safe_signing_requires_the_module_address(monkeypatch):
    """Sin la dirección del módulo el dominio EIP-712 es otro."""
    monkeypatch.setattr(settings, "BUNDLER_RPC_URL", "https://bundler.example")
    monkeypatch.setattr(settings, "ERC4337_ACCOUNT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "ERC4337_ACCOUNT_IMPLEMENTATION", "safe")
    monkeypatch.setattr(settings, "SAFE_OWNER_PRIVATE_KEY", "0x" + "c3" * 32)
    monkeypatch.setattr(settings, "SAFE_4337_MODULE_ADDRESS", "")

    with pytest.raises(pm.PaymasterUnavailable):
        pm.sign_user_operation({"sender": "0x" + "11" * 20})


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


def test_status_separates_implemented_from_verified():
    """"Implementado" y "verificado" no son lo mismo.

    La firma Safe existe, pero nunca se ejecutó contra un bundler real.
    Confundir ambas cosas es como se despliega algo que falla con AA24 en
    producción, así que el estado las declara por separado.
    """
    status = pm.status()
    assert status["enabled"] is False
    assert status["signing_implemented"] is True
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
