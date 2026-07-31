"""
Dashboard endpoints: real counts only (no inflated figures).
"""
from eth_account import Account
from eth_account.messages import encode_defunct

# Minting now requires a real wallet session (SIWE, C-1).
_ACCOUNT = Account.from_key("0x" + "ef" * 32)
VALID_ADDRESS = _ACCOUNT.address.lower()


async def _sign_in(client, account):
    challenge = await client.post("/api/wallet/challenge", json={"address": account.address})
    challenge.raise_for_status()
    body = challenge.json()
    signed = Account.sign_message(encode_defunct(text=body["message"]), private_key=account.key)
    verify = await client.post("/api/wallet/verify", json={
        "address": account.address,
        "nonce": body["nonce"],
        "signature": signed.signature.hex(),
    })
    verify.raise_for_status()
    return {"Authorization": f"Bearer {verify.json()['token']}"}


async def _mint(client):
    headers = await _sign_in(client, _ACCOUNT)
    return await client.post("/api/membership/mint", json={
        "wallet_address": VALID_ADDRESS,
        "assurance_level": "AL2",
        "doc_hash": "0xdeadbeef",
    }, headers=headers)


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
