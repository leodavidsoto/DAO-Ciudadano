"""
Dashboard endpoints: real counts only (no inflated figures).
"""

VALID_ADDRESS = "0x" + "ef" * 20


async def test_stats_are_zero_with_empty_db(client):
    stats = (await client.get("/api/dashboard/stats")).json()
    assert stats["total_members"] == 0
    assert stats["recent_joins"] == 0


async def test_stats_count_real_members(client):
    await client.post("/api/membership/mint", json={
        "wallet_address": VALID_ADDRESS,
        "assurance_level": "AL2",
        "doc_hash": "0xdeadbeef",
    })
    stats = (await client.get("/api/dashboard/stats")).json()
    assert stats["total_members"] == 1
    assert stats["recent_joins"] == 1


async def test_activity_feed(client):
    empty = (await client.get("/api/dashboard/activity")).json()
    assert empty["activities"] == []

    await client.post("/api/membership/mint", json={
        "wallet_address": VALID_ADDRESS,
        "assurance_level": "AL2",
        "doc_hash": "0xdeadbeef",
    })
    feed = (await client.get("/api/dashboard/activity")).json()
    assert len(feed["activities"]) == 1
    assert feed["activities"][0]["type"] == "new_member"
    assert feed["activities"][0]["token_id"] == 1
