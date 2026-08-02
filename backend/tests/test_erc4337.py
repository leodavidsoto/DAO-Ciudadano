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
        json={"address": account.address, "nonce": data["nonce"], "signature": signature},
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
    assert body["safe_4337_module_address"] == "0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226"
    assert body["missing"], "debe enumerar qué falta para poder habilitarse"


async def test_prepare_mint_refuses_while_sponsorship_is_unavailable(client):
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/erc4337/prepare-mint",
        json={
            "owner_address": CITIZEN.address,
            "safe_address": "0x" + "11" * 20,
            "chain_id": str(settings.SIWE_CHAIN_ID),
            "entry_point": pm.ENTRYPOINT_V07,
            "proof": {
                "pA": ["1", "2"],
                "pB": [["1", "2"], ["3", "4"]],
                "pC": ["5", "6"],
                "nullifier_hash": "0x" + "ab" * 32,
                "identity_root": "123",
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
            "proof": {
                "pA": ["1", "2"], "pB": [["1", "2"], ["3", "4"]], "pC": ["5", "6"],
                "nullifier_hash": "0x" + "ab" * 32, "identity_root": "123",
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
        json={"operation_id": "op_inexistente", "user_operation": {}},
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
