"""
Shared fixtures: in-memory MongoDB (mongomock) + ASGI test client.
No real network or database is touched by this suite.
"""
import os
import sys
from pathlib import Path

# Deben fijarse ANTES de importar nada de `app` o `main`: Settings() se
# construye una sola vez al importar app.core.config, y con el fail-closed
# de identity.py/crypto.py (sin pepper/llave en producción -> excepción)
# la suite entera rompería si estos quedaran vacíos como en CI real.
# Valores fijos y obviamente-de-test, no los que usa producción.
os.environ.setdefault("IDENTITY_PEPPER", "test-only-identity-pepper-not-for-production")
os.environ.setdefault("PII_ENCRYPTION_KEY", "pDWj9oG8D2Ms2dcHjTCiLsQM5raWlXfiINYLooDS4Q0=")
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-for-production")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("MINT_MODE", "demo")

import httpx
import asyncio
import pytest
from mongomock_motor import AsyncMongoMockClient

# Make `app` and `main` importable when pytest runs from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Database  # noqa: E402
from app.core.security_middleware import fraud_detector  # noqa: E402
from main import app  # noqa: E402


_stores_to_reset = []


def _reset_rate_limiter(asgi_app):
    """Clear in-memory rate-limit counters left over from previous tests.

    The middleware stack is a chain of wrappers; walk it looking for the
    RateLimitMiddleware instance (identified by its state attributes).
    """
    node = getattr(asgi_app, "middleware_stack", None)
    seen = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if hasattr(node, "failed_attempts") and hasattr(node, "store"):
            node.requests.clear()
            node.failed_attempts.clear()
            node.last_seen.clear()
            # El estado real vive en el almacén desde ROADMAP 3.8; se limpia
            # de forma asíncrona en el propio fixture.
            _stores_to_reset.append(node.store)
        node = getattr(node, "app", None)


@pytest.fixture
async def client():
    """HTTP client against the real FastAPI app with a fresh in-memory DB."""
    Database.client = AsyncMongoMockClient()
    Database.db = Database.client["test_dao_ciudadana"]
    await Database.ensure_indexes()
    _stores_to_reset.clear()
    _reset_rate_limiter(app)
    for store in _stores_to_reset:
        await store.reset()
    # The fraud detector is a process-global singleton; clear its in-memory
    # history so vote/delegation patterns from one test can't flag the next.
    fraud_detector.vote_history.clear()
    fraud_detector.delegation_chains.clear()
    fraud_detector.delegated_to.clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    Database.client = None
    Database.indexes_ready = False
