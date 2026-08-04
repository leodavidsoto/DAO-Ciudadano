"""
Reintentos y reconciliación del minteo ZK (seguimiento de c9950d8).

Dos defectos que Codex señaló y que estos tests fijan:

2. Una operación `failed` quedaba atrapada: el índice único la convertía en un
   409 permanente y el ciudadano no podía volver a intentarlo nunca.
4. Tras confirmar, `members` no se actualizaba, así que
   /membership/member/{wallet} y las estadísticas no veían el SBT recién
   emitido — y el gate de gobernanza rechazaba a alguien que sí tenía su
   credencial on-chain.
"""

from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.database import members_collection
from app.routers.membership import mint_operations_collection

# La reconciliación se movió a services/ para que la compartan el relayer y el
# camino ERC-4337, que antes no la ejecutaba (ver AUDIT P-70).
from app.services.membership_records import (
    reconcile_onchain_membership as _reconcile_member_record,
)

CITIZEN = Account.from_key("0x" + "f6" * 32)
NULLIFIER = "0x" + "ab" * 32


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


def _body(account):
    return {
        "wallet_address": account.address,
        "pA": ["1", "2"],
        "pB": [["1", "2"], ["3", "4"]],
        "pC": ["5", "6"],
        "nullifier_hash": NULLIFIER,
        "identity_root": "123",
    }


async def test_a_failed_operation_can_be_retried(client):
    """Un `failed` debe poder reintentarse, no quedar en 409 permanente."""
    headers = await _session(client, CITIZEN)
    await mint_operations_collection().insert_one(
        {
            "nullifier_hash": NULLIFIER,
            "wallet_address": CITIZEN.address.lower(),
            "status": "failed",
            "attempts": 1,
        }
    )

    response = await client.post(
        "/api/membership/mint-zk", json=_body(CITIZEN), headers=headers
    )

    # Falla al enviar (no hay cadena configurada), pero NO con el 409 que
    # bloqueaba el reintento: la operación se reclamó y se volvió a intentar.
    assert response.status_code != 409
    record = await mint_operations_collection().find_one({"nullifier_hash": NULLIFIER})
    assert record["attempts"] == 2


async def test_a_pending_operation_still_blocks_a_duplicate(client):
    """Reintentar mientras hay una en vuelo sí debe rechazarse."""
    headers = await _session(client, CITIZEN)
    await mint_operations_collection().insert_one(
        {
            "nullifier_hash": NULLIFIER,
            "wallet_address": CITIZEN.address.lower(),
            "status": "pending",
        }
    )

    response = await client.post(
        "/api/membership/mint-zk", json=_body(CITIZEN), headers=headers
    )

    assert response.status_code == 409


async def test_a_confirmed_operation_is_returned_without_resending(client):
    headers = await _session(client, CITIZEN)
    await mint_operations_collection().insert_one(
        {
            "nullifier_hash": NULLIFIER,
            "wallet_address": CITIZEN.address.lower(),
            "status": "confirmed",
            "token_id": 7,
            "tx_hash": "0xdead",
        }
    )

    body = (
        await client.post(
            "/api/membership/mint-zk", json=_body(CITIZEN), headers=headers
        )
    ).json()

    assert body["ok"] is True
    assert body["token_id"] == 7


async def test_reconciliation_makes_the_sbt_visible_to_the_api(client):
    """Sin esto, un SBT emitido por la vía ZK era invisible para la API."""
    assert (
        await members_collection().find_one({"wallet_address": CITIZEN.address.lower()})
        is None
    )

    await _reconcile_member_record(CITIZEN.address, token_id=42, tx_hash="0xfeed")

    body = (await client.get(f"/api/membership/member/{CITIZEN.address}")).json()

    assert body["found"] is True
    member = body["member"]
    assert member["token_id"] == 42
    assert member["tx_hash"] == "0xfeed"
    assert member["onchain"] is True
    # La prueba ZK ES la verificación: el contrato solo acepta raíces que el
    # emisor aprobó tras consumir un grant civil.
    assert member["identity_verified"] is True


async def test_reconciliation_is_idempotent(client):
    await _reconcile_member_record(CITIZEN.address, token_id=42, tx_hash="0xfeed")
    await _reconcile_member_record(CITIZEN.address, token_id=42, tx_hash="0xfeed")

    assert (
        await members_collection().count_documents(
            {"wallet_address": CITIZEN.address.lower()}
        )
        == 1
    )
