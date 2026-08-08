import pytest
import jwt
from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.config import settings
from app.core.database import revoked_tokens_collection
from app.services.siwe_service import issue_token, read_token, revoke_token


@pytest.mark.asyncio
async def test_revoked_token_is_rejected(client):
    address = "0x1234567890123456789012345678901234567890"
    token = issue_token(address)

    assert await read_token(token) == address.lower()

    await revoke_token(token)

    assert await read_token(token) is None


@pytest.mark.asyncio
async def test_unrevoked_token_remains_valid(client):
    address1 = "0x1111111111111111111111111111111111111111"
    address2 = "0x2222222222222222222222222222222222222222"

    token1 = issue_token(address1)
    token2 = issue_token(address2)

    await revoke_token(token1)

    assert await read_token(token1) is None
    assert await read_token(token2) == address2.lower()


@pytest.mark.asyncio
async def test_revoke_token_is_idempotent(client):
    address = "0x3333333333333333333333333333333333333333"
    token = issue_token(address)

    await revoke_token(token)
    await revoke_token(token)  # Second time should not fail

    assert await read_token(token) is None

    # Check that there's only one record for this jti
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=["HS256"],
        audience=settings.SIWE_DOMAIN,
        issuer=settings.SIWE_URI,
    )
    jti = payload.get("jti")

    count = await revoked_tokens_collection().count_documents({"jti": jti})
    assert count == 1


@pytest.mark.asyncio
async def test_revoke_invalid_token_does_not_fail(client):
    invalid_token = "invalid.token.string"
    await revoke_token(invalid_token)  # Should not raise an error


@pytest.mark.asyncio
async def test_logout_revokes_token_in_endpoint(client):
    account = Account.from_key("0x" + "aa" * 32)

    challenge = await client.post(
        "/api/wallet/challenge", json={"address": account.address}
    )
    body = challenge.json()

    signature = Account.sign_message(
        encode_defunct(text=body["message"]),
        private_key=account.key,
    ).signature.hex()

    verify = await client.post(
        "/api/wallet/verify",
        json={
            "address": account.address,
            "nonce": body["nonce"],
            "signature": signature,
        },
    )

    token = verify.json()["token"]

    # Should work
    session_res = await client.get(
        "/api/wallet/session", headers={"Authorization": f"Bearer {token}"}
    )
    assert session_res.status_code == 200

    # Logout
    logout_res = await client.post(
        "/api/wallet/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert logout_res.status_code == 200

    # Session should now be 401
    session_res2 = await client.get(
        "/api/wallet/session", headers={"Authorization": f"Bearer {token}"}
    )
    assert session_res2.status_code == 401
