"""
`/metrics` autenticado (observabilidad añadida en producción).

`Instrumentator().expose(app)` publicaba las métricas SIN autenticación. No
llevan PII, pero describen el sistema con precisión —inventario de rutas,
tráfico por endpoint, latencias, errores— y eso es reconocimiento gratuito
para cualquiera que las pida.

El router no se monta cuando `ENABLE_METRICS` es false, así que estos tests
construyen una app mínima con el router para poder ejercitar el guardia.
"""

import httpx
import pytest
from fastapi import FastAPI

from app.core import readiness
from app.core.config import settings
from app.routers.metrics import router as metrics_router

TOKEN = "token-de-metricas-largo-y-aleatorio"


@pytest.fixture
def metrics_client():
    app = FastAPI()
    app.include_router(metrics_router)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://metrics")


async def test_without_token_in_production_it_refuses_to_publish(
    metrics_client, monkeypatch
):
    """Fail closed: mejor sin métricas que con métricas públicas."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")

    async with metrics_client as client:
        response = await client.get("/metrics")

    assert response.status_code == 503
    assert "METRICS_TOKEN" in response.json()["detail"]


async def test_a_configured_token_is_required(metrics_client, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN)

    async with metrics_client as client:
        missing = await client.get("/metrics")
        wrong = await client.get(
            "/metrics", headers={"Authorization": "Bearer token-equivocado"}
        )
        ok = await client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    assert "python_gc_objects_collected_total" in ok.text


async def test_local_development_does_not_need_a_token(metrics_client, monkeypatch):
    """Sin token fuera de producción se sirve, para no estorbar el desarrollo."""
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")

    async with metrics_client as client:
        response = await client.get("/metrics")

    assert response.status_code == 200


async def test_metrics_are_not_mounted_when_disabled(client):
    """En la suite ENABLE_METRICS es false: la ruta no debe ni existir."""
    response = await client.get("/metrics")

    assert response.status_code == 404


def test_public_metrics_block_production_readiness(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ENABLE_METRICS", True)
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")

    blockers = readiness.deployment_blockers()

    assert any("METRICS_TOKEN" in blocker for blocker in blockers)


def test_metrics_with_a_token_do_not_block_readiness(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ENABLE_METRICS", True)
    monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN)

    blockers = readiness.deployment_blockers()

    assert not any("METRICS_TOKEN" in blocker for blocker in blockers)
