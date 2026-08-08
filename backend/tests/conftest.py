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
os.environ["IDENTITY_PEPPER"] = "test-only-identity-pepper-not-for-production"
os.environ["PII_ENCRYPTION_KEY"] = "pDWj9oG8D2Ms2dcHjTCiLsQM5raWlXfiINYLooDS4Q0="
os.environ["SECRET_KEY"] = "test-only-secret-key-not-for-production"
os.environ["APP_ENV"] = "test"
os.environ["MINT_MODE"] = "demo"

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

# Redis va aparte del resto de integraciones externas (ROADMAP 3.8).
#
# Por defecto se apaga igual que las demás y la suite corre sobre el almacén en
# memoria: hermética, sin servicios levantados, y CI no depende de nadie. Pero
# el limitador y el antifraude son el ÚNICO módulo cuya implementación real es
# un script Lua que se ejecuta dentro de Redis. Probarlo solo contra fakeredis
# valida la lógica de Python y da por bueno el Lua sin haberlo ejecutado nunca
# en el intérprete que lo correrá en producción.
#
# `TEST_REDIS_URL` es la vía explícita para apuntar la suite ENTERA a un Redis
# real. Sin ella, nada cambia:
#
#     TEST_REDIS_URL=redis://localhost:6379/15 pytest tests/test_antifraud.py
#
# Usa una base dedicada (aquí la 15): la suite la vacía entre tests, y hacerlo
# sobre la 0 borraría lo que alguien tuviera en su Redis de desarrollo.
_test_redis_url = os.environ.get("TEST_REDIS_URL", "").strip()
os.environ["REDIS_URL"] = _test_redis_url

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
from app.services import membership_grant  # noqa: E402
from main import app  # noqa: E402


def membership_grant_for(subject_key: str, assurance_level: str = "AL2") -> str:
    """Grant de membresía firmado por el servidor, para tests (ROADMAP 1.10).

    `POST /api/membership/mint` ya no acepta un nivel autoafirmado: exige este
    JWT (AUDIT P-4). Vive en conftest y no en cada archivo porque casi toda la
    suite necesita miembros para llegar a lo que de verdad prueba.

    Cada llamada emite un jti nuevo, así que un test que reintenta el alta
    debe reutilizar el MISMO valor — igual que haría el cliente real.
    """
    return membership_grant.issue(
        subject_key=subject_key,
        assurance_level=assurance_level,
        provider="test-provider",
    )


async def mint_membership(client, account, headers, address=None, grant=None):
    """Da de alta a `account` con un grant recién emitido para ese sujeto.

    El sujeto se deriva de la dirección: distintas cuentas son distintas
    personas, que es lo que espera la regla "una identidad, una membresía".
    """
    return await client.post(
        "/api/membership/mint",
        json={
            "wallet_address": address if address is not None else account.address,
            "membership_grant": grant or membership_grant_for(account.address.lower()),
        },
        headers=headers,
    )


_stores_to_reset = []


def _reset_rate_limiter(asgi_app):
    """Register the rate-limit store so counters don't leak between tests.

    This used to walk `app.middleware_stack` looking for the middleware
    instance, but Starlette leaves that attribute as None until the app
    starts, so the walk found nothing and the counters accumulated across
    tests: the suite failed sporadically with 429. The store is a module-level
    singleton, so take it straight from there.
    """
    from main import rate_limit_store

    if rate_limit_store not in _stores_to_reset:
        _stores_to_reset.append(rate_limit_store)


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
