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
os.environ.setdefault(
    "PII_ENCRYPTION_KEY", "pDWj9oG8D2Ms2dcHjTCiLsQM5raWlXfiINYLooDS4Q0="
)
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-for-production")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("MINT_MODE", "demo")

# La suite debe ser hermética: `pydantic-settings` lee `backend/.env` al
# importar, así que sin esto un `.env` de desarrollo con credenciales reales
# cambiaría los resultados y CI divergiría de local. Se fijan a vacío las
# variables de integraciones externas — `os.environ` tiene precedencia sobre
# el archivo. Un test que necesite alguna, la activa con monkeypatch.
os.environ["ERC4337_ENABLED"] = "false"  # booleano: "" no parsea
for _external in (
    "BUNDLER_RPC_URL",
    "ERC4337_ACCOUNT_IMPLEMENTATION",
    "ERC4337_PAYMASTER_ADDRESS",
    "SAFE_4337_MODULE_ADDRESS",
    "SAFE_OWNER_PRIVATE_KEY",
    "REDIS_URL",
    "SEPOLIA_RPC_URL",
    "SBT_CONTRACT_ADDRESS",
    "MINTER_PRIVATE_KEY",
    "MACI_COORDINATOR_ADDRESS",
    "IDENTITY_ISSUER_PRIVATE_KEY",
    "IDENTITY_PROVIDER",
    # Tesorería (ROADMAP 3.6): sin esto, un `.env` con un Safe real haría que
    # la suite intentara hablar con un RPC y con la API de precios.
    "TREASURY_SAFE_ADDRESS",
    "TREASURY_RPC_URL",
    "ETH_PRICE_API_URL",
):
    os.environ[_external] = ""

# El proveedor de precio se apaga por defecto en la suite: un test que quiera
# precio lo activa y sustituye la llamada de red explícitamente.
os.environ["ETH_PRICE_PROVIDER"] = "none"

import httpx
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
        if hasattr(node, "store") and hasattr(node, "PENALTY_THRESHOLD"):
            # Todo el estado vive en el almacén desde ROADMAP 3.8.
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
    await fraud_detector.reset()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c

    Database.client = None
    Database.indexes_ready = False
