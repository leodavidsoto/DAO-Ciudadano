"""
Shared fixtures: in-memory MongoDB (mongomock) + ASGI test client.
No real network or database is touched by this suite.
"""
import os
import sys
from pathlib import Path

# Deterministic pepper so identity hashes are stable across the suite.
# Production reads it from a KMS; without it the code fails closed (ADR 0001 D-2).
os.environ.setdefault("IDENTITY_PEPPER", "test-pepper-not-a-secret")
os.environ.setdefault("PII_ENCRYPTION_KEY", "test-encryption-key-not-a-secret")

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

# Make `app` and `main` importable when pytest runs from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Database  # noqa: E402
from app.core.security_middleware import fraud_detector  # noqa: E402
from app.services.siwe_service import siwe_service  # noqa: E402
from main import app  # noqa: E402


# Address fields a request body may carry to identify the acting party.
_ACTOR_FIELDS = (
    "creator_address", "voter_address", "delegator_address",
    "candidate_address", "wallet_address", "address",
)


class _AutoAuthClient:
    """Test client that signs in as whoever the request body acts as.

    Every mutating endpoint now requires a session token proving control of
    the address (audit finding C-1). Threading a real SIWE handshake through
    every governance test would bury the behaviour under test in ceremony, so
    this wrapper issues the token automatically.

    It does NOT hide the guarantee: `anon_client` speaks to the same app with
    no credentials, and tests/test_session.py exercises the real signature
    flow — nonce, recovery, replay and expiry included.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def _send(self, method, url, **kwargs):
        body = kwargs.get("json")
        headers = kwargs.get("headers") or {}
        if isinstance(body, dict) and "Authorization" not in headers:
            for field in _ACTOR_FIELDS:
                if body.get(field):
                    headers = {
                        **headers,
                        "Authorization": f"Bearer {siwe_service.issue_token(body[field])}",
                    }
                    kwargs["headers"] = headers
                    break
        return await getattr(self._inner, method)(url, **kwargs)

    async def post(self, url, **kwargs):
        return await self._send("post", url, **kwargs)

    async def put(self, url, **kwargs):
        return await self._send("put", url, **kwargs)

    async def delete(self, url, **kwargs):
        return await self._send("delete", url, **kwargs)


def _reset_rate_limiter(asgi_app):
    """Clear in-memory rate-limit counters left over from previous tests.

    The middleware stack is a chain of wrappers; walk it looking for the
    RateLimitMiddleware instance (identified by its state attributes).
    """
    node = getattr(asgi_app, "middleware_stack", None)
    seen = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if hasattr(node, "failed_attempts") and hasattr(node, "requests"):
            node.requests.clear()
            node.failed_attempts.clear()
        node = getattr(node, "app", None)


@pytest.fixture
async def client():
    """HTTP client against the real FastAPI app with a fresh in-memory DB."""
    Database.client = AsyncMongoMockClient()
    Database.db = Database.client["test_dao_ciudadana"]
    await Database.ensure_indexes()
    _reset_rate_limiter(app)
    # The fraud detector is a process-global singleton; clear its in-memory
    # history so vote/delegation patterns from one test can't flag the next.
    fraud_detector.vote_history.clear()
    fraud_detector.delegation_chains.clear()
    fraud_detector.delegated_to.clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield _AutoAuthClient(c)

    Database.client = None


@pytest.fixture
async def anon_client():
    """Client with no session token: for asserting that endpoints reject it."""
    Database.client = AsyncMongoMockClient()
    Database.db = Database.client["test_dao_ciudadana_anon"]
    await Database.ensure_indexes()
    _reset_rate_limiter(app)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    Database.client = None


@pytest.fixture
def auth():
    """Build an Authorization header for an address."""
    def _auth(address):
        return {"Authorization": f"Bearer {siwe_service.issue_token(address)}"}
    return _auth
