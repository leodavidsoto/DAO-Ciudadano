"""Wallet session surface: only the SIWE challenge/verify flow is exposed."""

from datetime import datetime, timedelta, timezone

from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.config import settings
from app.core.database import siwe_nonces_collection


_ACCOUNT = Account.from_key("0x" + "ac" * 32)
_OTHER_ACCOUNT = Account.from_key("0x" + "bd" * 32)


async def test_removed_mock_wallet_endpoint_is_not_exposed(client):
    response = await client.post("/api/wallet/connect")

    assert response.status_code == 404


async def test_removed_mock_balance_endpoint_is_not_exposed(client):
    response = await client.get(
        "/api/wallet/balance/0x0000000000000000000000000000000000000000"
    )

    assert response.status_code == 404


async def test_wallet_challenge_uses_sensitive_rate_limit(client):
    payload = {"address": "0x0000000000000000000000000000000000000001"}
    limit = settings.RATE_LIMIT_SENSITIVE_REQUESTS

    allowed = [
        await client.post("/api/wallet/challenge", json=payload) for _ in range(limit)
    ]
    limited = await client.post("/api/wallet/challenge", json=payload)

    assert all(response.status_code == 200 for response in allowed)
    assert limited.status_code == 429


async def test_siwe_challenge_binds_domain_uri_chain_and_expiration(client):
    response = await client.post(
        "/api/wallet/challenge",
        json={"address": _ACCOUNT.address},
    )
    message = response.json()["message"]

    assert message.startswith(
        f"{settings.SIWE_DOMAIN} wants you to sign in with your Ethereum account:"
    )
    assert f"URI: {settings.SIWE_URI}" in message
    assert f"Chain ID: {settings.SIWE_CHAIN_ID}" in message
    assert "Expiration Time:" in message


async def test_siwe_challenge_rejects_non_hex_address(client):
    response = await client.post(
        "/api/wallet/challenge",
        json={"address": "0x" + "z" * 40},
    )

    assert response.status_code == 422


async def test_invalid_signature_does_not_consume_siwe_challenge(client):
    challenge = await client.post(
        "/api/wallet/challenge",
        json={"address": _ACCOUNT.address},
    )
    body = challenge.json()
    wrong_signature = Account.sign_message(
        encode_defunct(text=body["message"]),
        private_key=_OTHER_ACCOUNT.key,
    ).signature.hex()

    rejected = await client.post(
        "/api/wallet/verify",
        json={
            "address": _ACCOUNT.address,
            "nonce": body["nonce"],
            "signature": wrong_signature,
        },
    )
    stored = await siwe_nonces_collection().find_one({"nonce": body["nonce"]})

    assert rejected.status_code == 401
    assert stored["consumed"] is False

    valid_signature = Account.sign_message(
        encode_defunct(text=body["message"]),
        private_key=_ACCOUNT.key,
    ).signature.hex()
    accepted = await client.post(
        "/api/wallet/verify",
        json={
            "address": _ACCOUNT.address,
            "nonce": body["nonce"],
            "signature": valid_signature,
        },
    )

    assert accepted.status_code == 200


async def test_expired_siwe_challenge_cannot_issue_session(client):
    challenge = await client.post(
        "/api/wallet/challenge",
        json={"address": _ACCOUNT.address},
    )
    body = challenge.json()
    signature = Account.sign_message(
        encode_defunct(text=body["message"]),
        private_key=_ACCOUNT.key,
    ).signature.hex()
    await siwe_nonces_collection().update_one(
        {"nonce": body["nonce"]},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )

    response = await client.post(
        "/api/wallet/verify",
        json={
            "address": _ACCOUNT.address,
            "nonce": body["nonce"],
            "signature": signature,
        },
    )

    assert response.status_code == 401


async def test_production_siwe_misconfiguration_fails_before_writing_nonce(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SIWE_DOMAIN", "localhost")
    monkeypatch.setattr(settings, "SIWE_URI", "http://localhost:3000")
    before = await siwe_nonces_collection().count_documents({})

    response = await client.post(
        "/api/wallet/challenge",
        json={"address": _ACCOUNT.address},
    )

    assert response.status_code == 503
    assert await siwe_nonces_collection().count_documents({}) == before
