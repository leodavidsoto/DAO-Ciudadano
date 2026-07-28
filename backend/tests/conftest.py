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
from main import app  # noqa: E402


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
        yield c

    Database.client = None
