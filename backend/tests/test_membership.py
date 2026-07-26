"""
Membership endpoints: mint (off-chain demo), duplicate rejection,
address validation and lookups.
"""

VALID_ADDRESS = "0x" + "ab" * 20
OTHER_ADDRESS = "0x" + "cd" * 20


async def _mint(client, address=VALID_ADDRESS, doc_hash="0xdeadbeef", level="AL2"):
    return await client.post("/api/membership/mint", json={
        "wallet_address": address,
        "assurance_level": level,
        "doc_hash": doc_hash,
    })


async def test_mint_creates_member(client):
    response = await _mint(client)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["token_id"] == 1
    # Nothing is written on-chain yet: tx_hash must be null, never fabricated
    assert data["tx_hash"] is None


async def test_mint_rejects_duplicate_wallet_case_insensitive(client):
    first = await _mint(client, address="0x" + "AB" * 20)
    assert first.json()["ok"] is True

    duplicate = await _mint(client, address="0x" + "ab" * 20)
    data = duplicate.json()
    assert data["ok"] is False
    assert "Ya existe" in data["error"]


async def test_mint_rejects_invalid_address(client):
    response = await _mint(client, address="0x123")
    data = response.json()
    assert data["ok"] is False
    assert data["token_id"] is None


async def test_mint_requires_doc_hash(client):
    response = await _mint(client, doc_hash="")
    data = response.json()
    assert data["ok"] is False


async def test_token_ids_are_sequential(client):
    first = await _mint(client, address=VALID_ADDRESS)
    second = await _mint(client, address=OTHER_ADDRESS)
    assert first.json()["token_id"] == 1
    assert second.json()["token_id"] == 2


async def test_verify_membership(client):
    await _mint(client)

    found = await client.get("/api/membership/verify/1")
    data = found.json()
    assert data["valid"] is True
    assert data["wallet_address"] == VALID_ADDRESS
    assert data["status"] == "active"

    missing = await client.get("/api/membership/verify/999")
    assert missing.json()["valid"] is False


async def test_get_member_by_wallet(client):
    await _mint(client)

    found = await client.get(f"/api/membership/member/{VALID_ADDRESS}")
    data = found.json()
    assert data["found"] is True
    assert data["member"]["token_id"] == 1

    missing = await client.get(f"/api/membership/member/{OTHER_ADDRESS}")
    assert missing.json()["found"] is False
