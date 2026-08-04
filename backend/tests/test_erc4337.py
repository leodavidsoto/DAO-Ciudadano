"""
Endpoints ERC-4337 — minteo patrocinado NO custodial.

Lo que protegen estos tests es el reparto de poderes: la Safe es del
ciudadano, firma él con MetaMask, y el backend solo prepara y retransmite.
Si el servidor pudiera firmar, podría mintear a nombre de cualquiera.

La otra garantía crítica es que el patrocinio de la DAO no financie una
transacción arbitraria: `callData` lo controla el cliente por completo, así
que se decodifica y se exige que sea exactamente el mintMembership declarado.
"""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.config import settings
from app.services import paymaster_service as pm

CITIZEN = Account.from_key("0x" + "d4" * 32)


async def _session(client, account):
    challenge = await client.post(
        "/api/wallet/challenge", json={"address": account.address}
    )
    data = challenge.json()
    signature = account.sign_message(
        encode_defunct(text=data["message"])
    ).signature.hex()
    verify = await client.post(
        "/api/wallet/verify",
        json={
            "address": account.address,
            "nonce": data["nonce"],
            "signature": signature,
        },
    )
    return {"Authorization": f"Bearer {verify.json()['token']}"}


async def test_config_requires_a_wallet_session(client):
    assert (await client.get("/api/erc4337/config")).status_code == 401


async def test_config_declares_non_custodial_and_fails_closed(client):
    """Sin configurar debe decir `enabled: false`, no valores plausibles."""
    headers = await _session(client, CITIZEN)

    body = (await client.get("/api/erc4337/config", headers=headers)).json()

    assert body["enabled"] is False
    assert body["custodial"] is False
    assert body["account_type"] == "safe"
    assert body["entry_point_version"] == "0.7"
    # El módulo canónico es parte del contrato: el cliente lo fija y rechaza otro.
    assert (
        body["safe_4337_module_address"] == "0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226"
    )
    assert body["missing"], "debe enumerar qué falta para poder habilitarse"


# === Contrato con el cliente (P-53) ===

SBT = "0x" + "5b" * 20
NULLIFIER = "0x" + "ab" * 32
ROOT = "12345"
PA = ["1", "2"]
PB = [["3", "4"], ["5", "6"]]
PC = ["7", "8"]


def _account_profile():
    return {
        "type": "safe",
        "version": "1.4.1",
        "salt_nonce": "0",
        "safe_4337_module_address": "0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226",
        "use_multi_send_for_setup": False,
    }


def _build_call_data(
    to_sbt=SBT,
    recipient=None,
    operation=0,
    value=0,
    nullifier=NULLIFIER,
    root=ROOT,
    pa=None,
):
    """Construye el callData de DOS capas, como lo hace el cliente.

    La externa es Safe4337Module.executeUserOpWithErrorString; dentro va la
    llamada real al SBT. Reproducirlo aquí es lo que prueba que el backend
    decodifica la capa correcta.
    """
    from web3 import Web3

    from app.routers.erc4337 import _SAFE_EXEC_ABI
    from app.services import chain_service

    w3 = Web3()
    sbt = w3.eth.contract(abi=chain_service._MINT_ABI)
    inner = sbt.encode_abi(
        "mintMembership",
        args=[
            Web3.to_checksum_address(recipient or CITIZEN.address),
            [int(v) for v in (pa or PA)],
            [[int(v) for v in row] for row in PB],
            [int(v) for v in PC],
            bytes.fromhex(nullifier.removeprefix("0x")),
            int(root),
        ],
    )
    wrapper = w3.eth.contract(abi=_SAFE_EXEC_ABI)
    return wrapper.encode_abi(
        "executeUserOpWithErrorString",
        args=[
            Web3.to_checksum_address(to_sbt),
            value,
            bytes.fromhex(inner.removeprefix("0x")),
            operation,
        ],
    )


def _prepare_body(**overrides):
    body = {
        "owner_address": CITIZEN.address,
        "safe_address": "0x" + "11" * 20,
        "chain_id": str(settings.SIWE_CHAIN_ID),
        "entry_point": pm.ENTRYPOINT_V07,
        "account": _account_profile(),
        "mint": {
            "wallet_address": CITIZEN.address,
            "pA": PA,
            "pB": PB,
            "pC": PC,
            "nullifier_hash": NULLIFIER,
            "identity_root": ROOT,
        },
        "user_operation": {
            "sender": "0x" + "11" * 20,
            "callData": _build_call_data(),
        },
    }
    body.update(overrides)
    return body


def test_the_two_layer_call_data_decodes_correctly():
    """El callData es un envoltorio Safe4337 que contiene la llamada al SBT.

    La versión anterior lo decodificaba directamente con la ABI del SBT, así
    que el camino integrado devolvía 422 antes de patrocinar nada (P-53).
    """
    from app.routers.erc4337 import _decode_inner_mint_call, _decode_safe_wrapper

    wrapper = _decode_safe_wrapper(_build_call_data())

    assert wrapper["to"].lower() == SBT
    assert wrapper["value"] == 0
    assert wrapper["operation"] == 0

    inner = _decode_inner_mint_call(wrapper["data"])
    assert inner["to"].lower() == CITIZEN.address.lower()
    assert "0x" + inner["nullifierHash"].hex() == NULLIFIER
    assert str(inner["identityRoot"]) == ROOT


def test_decoding_the_outer_layer_as_the_sbt_abi_fails():
    """Contraprueba del bug: la capa externa NO es una llamada al SBT."""
    from fastapi import HTTPException

    from app.routers.erc4337 import _decode_inner_mint_call

    with pytest.raises(HTTPException):
        _decode_inner_mint_call(_build_call_data())


def test_delegatecall_is_rejected():
    """DELEGATECALL ejecutaría código arbitrario en el contexto de la Safe."""
    from fastapi import HTTPException

    from app.routers.erc4337 import _decode_safe_wrapper

    with pytest.raises(HTTPException) as exc:
        _decode_safe_wrapper(_build_call_data(operation=1))
    assert "CALL" in exc.value.detail


def test_value_transfer_is_rejected():
    from fastapi import HTTPException

    from app.routers.erc4337 import _decode_safe_wrapper

    with pytest.raises(HTTPException):
        _decode_safe_wrapper(_build_call_data(value=1))


def test_account_profile_must_match_the_served_config():
    """Otro módulo cambia el dominio EIP-712 y la firma dejaría de validar."""
    from fastapi import HTTPException

    from app.routers.erc4337 import SafeAccountProfile, _assert_account_profile

    bad = SafeAccountProfile(
        **{**_account_profile(), "safe_4337_module_address": "0x" + "99" * 20}
    )
    with pytest.raises(HTTPException) as exc:
        _assert_account_profile(bad)
    assert "Módulo Safe4337" in exc.value.detail


def test_sponsored_deployment_must_name_the_authenticated_owner():
    """Impide que el paymaster pague el despliegue de una Safe ajena."""
    from fastapi import HTTPException

    from app.routers.erc4337 import _assert_deployment_binds_owner

    owner = CITIZEN.address
    # Sin factoryData no hay despliegue que patrocinar: no aplica.
    _assert_deployment_binds_owner({}, owner)
    # Con el owner dentro del inicializador: correcto.
    _assert_deployment_binds_owner(
        {"factoryData": "0xaaaa" + owner.lower().removeprefix("0x")}, owner
    )
    # Inicializador de otra cuenta: rechazado.
    with pytest.raises(HTTPException):
        _assert_deployment_binds_owner({"factoryData": "0x" + "cd" * 40}, owner)


def test_declared_proof_must_match_the_executed_one():
    """Sin esto, `mint` sería decorativo: se valida una prueba y se ejecuta otra."""
    from fastapi import HTTPException

    from app.routers.erc4337 import (
        MintPayload,
        _assert_proof_matches,
        _decode_inner_mint_call,
        _decode_safe_wrapper,
    )

    # El callData ejecuta pA distinto del declarado.
    wrapper = _decode_safe_wrapper(_build_call_data(pa=["99", "98"]))
    inner = _decode_inner_mint_call(wrapper["data"])
    declared = MintPayload(
        wallet_address=CITIZEN.address,
        pA=PA,
        pB=PB,
        pC=PC,
        nullifier_hash=NULLIFIER,
        identity_root=ROOT,
    )

    with pytest.raises(HTTPException) as exc:
        _assert_proof_matches(inner, declared)
    assert "pA" in exc.value.detail


async def test_prepare_mint_refuses_while_sponsorship_is_unavailable(client):
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/erc4337/prepare-mint",
        json={
            "owner_address": CITIZEN.address,
            "safe_address": "0x" + "11" * 20,
            "chain_id": str(settings.SIWE_CHAIN_ID),
            "entry_point": pm.ENTRYPOINT_V07,
            "account": _account_profile(),
            "mint": {
                "wallet_address": CITIZEN.address,
                "pA": PA,
                "pB": PB,
                "pC": PC,
                "nullifier_hash": NULLIFIER,
                "identity_root": ROOT,
            },
            "user_operation": {"sender": "0x" + "11" * 20, "callData": "0x"},
        },
        headers=headers,
    )

    assert response.status_code == 503


async def test_prepare_mint_cannot_be_requested_for_another_wallet(client):
    other = Account.from_key("0x" + "e5" * 32)
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/erc4337/prepare-mint",
        json={
            "owner_address": other.address,
            "safe_address": "0x" + "11" * 20,
            "chain_id": str(settings.SIWE_CHAIN_ID),
            "entry_point": pm.ENTRYPOINT_V07,
            "account": _account_profile(),
            "mint": {
                "wallet_address": CITIZEN.address,
                "pA": PA,
                "pB": PB,
                "pC": PC,
                "nullifier_hash": NULLIFIER,
                "identity_root": ROOT,
            },
            "user_operation": {"sender": "0x" + "11" * 20, "callData": "0x"},
        },
        headers=headers,
    )

    assert response.status_code == 403


async def test_submit_of_an_unknown_operation_is_rejected(client):
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/erc4337/submit-mint",
        json={
            "operation_id": "op_inexistente",
            "owner_address": CITIZEN.address,
            "safe_address": "0x" + "11" * 20,
            "entry_point": pm.ENTRYPOINT_V07,
            "user_operation": {},
        },
        headers=headers,
    )

    assert response.status_code == 404


async def test_operation_status_of_unknown_hash_is_404(client):
    response = await client.get("/api/erc4337/operations/0xdeadbeef")
    assert response.status_code == 404


def test_calldata_decoder_rejects_a_non_mint_call():
    """El patrocinio no puede financiar cualquier transacción."""
    from fastapi import HTTPException

    from app.routers.erc4337 import _decode_inner_mint_call

    with pytest.raises(HTTPException) as exc:
        _decode_inner_mint_call("0xdeadbeef")
    assert exc.value.status_code == 422


# === Derivación CREATE2 de la Safe (cierre de P-53) ===

# Vector REAL generado con el mismo permissionless.js que usa el navegador,
# contra Safe v1.4.1 y el módulo canónico en Sepolia. No es inventado: si esta
# derivación se rompe, el test falla en vez de rechazar peticiones legítimas
# en producción.
VECTOR_OWNER = "0x1111111111111111111111111111111111111111"
VECTOR_SAFE = "0x4315A87ca896aCfd7c8Ce0Fcf10eEc8fe3053816"
VECTOR_FACTORY = "0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67"


def _vector_factory_data():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "safe_factory_data.txt"
    )
    return path.read_text().strip()


def _stub_proxy_creation_code(monkeypatch, code: bytes):
    """Evita una llamada RPC real: el código del proxy es inmutable."""
    from app.routers import erc4337

    monkeypatch.setattr(erc4337, "_proxy_creation_code", lambda factory: code)


def test_create2_derivation_matches_the_real_client(monkeypatch):
    """La dirección derivada debe ser la que produjo permissionless.js."""
    from pathlib import Path

    from app.routers.erc4337 import _assert_safe_address_is_derived

    code = bytes.fromhex(
        (
            Path(__file__).resolve().parents[1]
            / "tests"
            / "fixtures"
            / "safe_proxy_creation_code.txt"
        )
        .read_text()
        .strip()
    )
    _stub_proxy_creation_code(monkeypatch, code)

    # No lanza: la dirección declarada es la que ese factoryData despliega.
    _assert_safe_address_is_derived(
        {"factory": VECTOR_FACTORY, "factoryData": _vector_factory_data()},
        VECTOR_SAFE,
    )


def test_a_declared_address_that_does_not_match_is_rejected(monkeypatch):
    """Impide que el paymaster financie el despliegue de otra cuenta."""
    from pathlib import Path

    from fastapi import HTTPException

    from app.routers.erc4337 import _assert_safe_address_is_derived

    code = bytes.fromhex(
        (
            Path(__file__).resolve().parents[1]
            / "tests"
            / "fixtures"
            / "safe_proxy_creation_code.txt"
        )
        .read_text()
        .strip()
    )
    _stub_proxy_creation_code(monkeypatch, code)

    with pytest.raises(HTTPException) as exc:
        _assert_safe_address_is_derived(
            {"factory": VECTOR_FACTORY, "factoryData": _vector_factory_data()},
            "0x" + "99" * 20,
        )
    assert "no es la que produce" in exc.value.detail


def test_factory_data_that_is_not_create_proxy_is_rejected(monkeypatch):
    from fastapi import HTTPException

    from app.routers.erc4337 import _assert_safe_address_is_derived

    _stub_proxy_creation_code(monkeypatch, b"\x00")

    with pytest.raises(HTTPException) as exc:
        _assert_safe_address_is_derived(
            {"factory": VECTOR_FACTORY, "factoryData": "0xdeadbeef" + "00" * 64},
            VECTOR_SAFE,
        )
    assert "createProxyWithNonce" in exc.value.detail


def test_an_already_deployed_safe_needs_no_derivation(monkeypatch):
    """Sin factoryData no hay despliegue que patrocinar ni que verificar."""
    from app.routers.erc4337 import _assert_safe_address_is_derived

    _assert_safe_address_is_derived({}, VECTOR_SAFE)


# === Verificación de la firma SafeOp antes de retransmitir (D-1) ===

MODULE = "0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226"


def _complete_user_op():
    """UserOperation con todos los campos que el struct SafeOp exige."""
    return {
        "sender": "0x" + "11" * 20,
        "nonce": "0x0",
        "callData": "0xdeadbeef",
        "callGasLimit": "0x1",
        "verificationGasLimit": "0x2",
        "preVerificationGas": "0x3",
        "maxFeePerGas": "0x4",
        "maxPriorityFeePerGas": "0x5",
    }


def _signed_user_op(account, prepared, chain_id=11155111, module=MODULE):
    """Firma una SafeOp como lo haría la wallet del ciudadano."""
    from app.services import safe_4337

    return safe_4337.sign_user_operation(
        {k: v for k, v in prepared.items() if k != "signature"},
        account.key.hex(),
        pm.ENTRYPOINT_V07,
        chain_id,
        module,
    )


def test_a_safe_op_signature_recovers_its_owner():
    """Ida y vuelta: lo que firma la wallet es lo que el backend recupera."""
    from app.services import safe_4337

    owner = Account.from_key("0x" + "c1" * 32)
    user_op = _complete_user_op()
    signed = safe_4337.sign_user_operation(
        user_op, owner.key.hex(), pm.ENTRYPOINT_V07, 11155111, MODULE
    )

    recovered = safe_4337.recover_owner(signed, pm.ENTRYPOINT_V07, 11155111, MODULE)

    assert recovered.lower() == owner.address.lower()


def test_a_signature_over_a_different_operation_does_not_verify():
    """Firmar una cosa y enviar otra tiene que detectarse aquí, no on-chain."""
    from app.services import safe_4337

    owner = Account.from_key("0x" + "c1" * 32)
    signed = safe_4337.sign_user_operation(
        _complete_user_op(),
        owner.key.hex(),
        pm.ENTRYPOINT_V07,
        11155111,
        MODULE,
    )
    # El callData cambia DESPUÉS de firmar.
    tampered = {**signed, "callData": "0xfeedface"}

    recovered = safe_4337.recover_owner(tampered, pm.ENTRYPOINT_V07, 11155111, MODULE)

    assert recovered.lower() != owner.address.lower()


def test_a_malformed_signature_is_rejected_with_a_reason():
    from app.services import safe_4337

    with pytest.raises(ValueError):
        safe_4337.recover_owner(
            {"sender": "0x" + "11" * 20, "signature": "0x1234"},
            pm.ENTRYPOINT_V07,
            11155111,
            MODULE,
        )


async def test_submit_rejects_a_signature_from_another_wallet(client, monkeypatch):
    """El backend no retransmite una operación que no autorizó su dueño."""
    from app.routers import erc4337 as erc4337_router

    owner = Account.from_key("0x" + "d2" * 32)
    impostor = Account.from_key("0x" + "e3" * 32)
    headers = await _session(client, owner)
    monkeypatch.setattr(settings, "SAFE_4337_MODULE_ADDRESS", MODULE)

    prepared = {**_complete_user_op(), "signature": "0x"}
    await erc4337_router.erc4337_operations_collection().insert_one(
        {
            "operation_id": "op_test_firma",
            "nullifier_hash": "0x" + "aa" * 32,
            "owner_address": owner.address.lower(),
            "safe_address": prepared["sender"].lower(),
            "prepared_user_operation": prepared,
            "status": "prepared",
        }
    )

    # La firma la produce OTRA wallet sobre la misma operación.
    signed = _signed_user_op(impostor, prepared)

    relayed = []
    monkeypatch.setattr(
        pm,
        "send_user_operation",
        lambda op: relayed.append(op) or "0xhash",
    )

    response = await client.post(
        "/api/erc4337/submit-mint",
        json={
            "operation_id": "op_test_firma",
            "owner_address": owner.address.lower(),
            "safe_address": prepared["sender"].lower(),
            "entry_point": pm.ENTRYPOINT_V07,
            "user_operation": signed,
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "no corresponde al propietario" in response.json()["detail"]
    assert relayed == []  # y no se gastó el viaje al bundler


async def test_submit_relays_a_correctly_signed_operation(client, monkeypatch):
    from app.routers import erc4337 as erc4337_router

    owner = Account.from_key("0x" + "d2" * 32)
    headers = await _session(client, owner)
    monkeypatch.setattr(settings, "SAFE_4337_MODULE_ADDRESS", MODULE)

    prepared = {**_complete_user_op(), "signature": "0x"}
    await erc4337_router.erc4337_operations_collection().insert_one(
        {
            "operation_id": "op_test_ok",
            "nullifier_hash": "0x" + "bb" * 32,
            "owner_address": owner.address.lower(),
            "safe_address": prepared["sender"].lower(),
            "prepared_user_operation": prepared,
            "status": "prepared",
        }
    )
    signed = _signed_user_op(owner, prepared)
    monkeypatch.setattr(pm, "send_user_operation", lambda op: "0x" + "fe" * 32)

    response = await client.post(
        "/api/erc4337/submit-mint",
        json={
            "operation_id": "op_test_ok",
            "owner_address": owner.address.lower(),
            "safe_address": prepared["sender"].lower(),
            "entry_point": pm.ENTRYPOINT_V07,
            "user_operation": signed,
        },
        headers=headers,
    )

    assert response.status_code == 200, response.json()
    assert response.json()["user_operation_hash"] == "0x" + "fe" * 32


# === La membresía patrocinada llega a la gobernanza (P-70) ===


async def test_a_sponsored_mint_creates_the_membership(client, monkeypatch):
    """Sin esto, el ciudadano obtenía el SBT y no podía votar."""
    from app.core.database import members_collection
    from app.routers import erc4337 as erc4337_router
    from app.services import chain_service

    owner = Account.from_key("0x" + "d2" * 32)
    op_hash = "0x" + "cc" * 32
    await erc4337_router.erc4337_operations_collection().insert_one(
        {
            "operation_id": "op_confirmada",
            "nullifier_hash": "0x" + "dd" * 32,
            "owner_address": owner.address.lower(),
            "safe_address": "0x" + "11" * 20,
            "user_operation_hash": op_hash,
            "status": "submitted",
        }
    )
    monkeypatch.setattr(
        pm,
        "get_user_operation_receipt",
        lambda h: {"success": True, "receipt": {"transactionHash": "0xtx"}},
    )
    monkeypatch.setattr(chain_service, "membership_token_of", lambda addr: 77)

    body = (await client.get(f"/api/erc4337/operations/{op_hash}")).json()

    assert body["status"] == "confirmed"
    assert body["token_id"] == 77
    member = await members_collection().find_one(
        {"wallet_address": owner.address.lower()}
    )
    assert member is not None, "el minteo patrocinado no creó la membresía"
    assert member["issuance_mode"] == "onchain"
    assert member["identity_verified"] is True
    assert member["token_id"] == 77
