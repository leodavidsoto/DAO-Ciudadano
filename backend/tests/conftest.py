"""
Shared fixtures: in-memory MongoDB (mongomock) + ASGI test client.
No real network or database is touched by this suite.
"""
import sys
from pathlib import Path

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

# Make `app` and `main` importable when pytest runs from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Database  # noqa: E402
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

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    Database.client = None
