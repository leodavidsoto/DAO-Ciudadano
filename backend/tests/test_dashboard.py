"""
Dashboard endpoints: real counts only (no inflated figures).
"""

from datetime import datetime, timezone

from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.config import settings
from conftest import membership_grant_for
from app.core.database import members_collection

# Minting now requires a real wallet session (SIWE, C-1).
_ACCOUNT = Account.from_key("0x" + "ef" * 32)
VALID_ADDRESS = _ACCOUNT.address.lower()


async def _sign_in(client, account):
    challenge = await client.post(
        "/api/wallet/challenge", json={"address": account.address}
    )
    challenge.raise_for_status()
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


async def _mint(client):
    headers = await _sign_in(client, _ACCOUNT)
    return await client.post(
        "/api/membership/mint",
        json={
            "wallet_address": VALID_ADDRESS,
            "membership_grant": membership_grant_for(VALID_ADDRESS),
        },
        headers=headers,
    )


async def test_stats_are_zero_with_empty_db(client):
    stats = (await client.get("/api/dashboard/stats")).json()
    assert stats["total_members"] == 0
    assert stats["recent_joins"] == 0


async def test_stats_count_real_members(client):
    await _mint(client)
    stats = (await client.get("/api/dashboard/stats")).json()
    assert stats["total_members"] == 1
    assert stats["recent_joins"] == 1


async def test_activity_feed(client):
    empty = (await client.get("/api/dashboard/activity")).json()
    assert empty["activities"] == []

    await _mint(client)
    feed = (await client.get("/api/dashboard/activity")).json()
    assert len(feed["activities"]) == 1
    assert feed["activities"][0]["type"] == "new_member"
    assert feed["activities"][0]["token_id"] == 1


async def test_removed_public_status_write_endpoint_is_not_exposed(client):
    response = await client.post(
        "/api/dashboard/status",
        json={"client_name": "untrusted-client"},
    )

    assert response.status_code == 404


async def test_production_metrics_quarantine_demo_and_legacy_rows(client, monkeypatch):
    now = datetime.now(timezone.utc)
    await members_collection().insert_many(
        [
            {
                "wallet_address": "0x" + "11" * 20,
                "token_id": 10,
                "status": "active",
                "issuance_mode": "demo",
                "identity_verified": False,
                "created_at": now,
            },
            {
                "wallet_address": "0x" + "22" * 20,
                "token_id": 11,
                "status": "active",
                "created_at": now,
            },
            {
                "wallet_address": "0x" + "33" * 20,
                "token_id": 12,
                "status": "active",
                "issuance_mode": "onchain",
                "identity_verified": True,
                "tx_hash": "0x" + "ab" * 32,
                "created_at": now,
            },
        ]
    )
    monkeypatch.setattr(settings, "APP_ENV", "production")

    stats = (await client.get("/api/dashboard/stats")).json()
    activity = (await client.get("/api/dashboard/activity")).json()

    assert stats["total_members"] == 1
    assert stats["recent_joins"] == 1
    assert len(activity["activities"]) == 1
    assert activity["activities"][0]["token_id"] == 12
