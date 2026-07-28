"""
Configuration readiness.

A missing production secret used to surface as "Ocurrió un error (ref: 7dae…)"
on every login while /health reported "healthy". The service looked fine to
monitoring and was broken for every user, and the operator had nothing to act
on. These tests are about diagnosability, not about the secrets themselves.
"""
import pytest

from app.core import readiness
from app.core.config import settings


@pytest.fixture
def production(monkeypatch):
    """Production-like: DEBUG off, secrets present unless a test clears one."""
    monkeypatch.setattr(settings, "DEBUG", False, raising=False)
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", "a-pepper", raising=False)
    monkeypatch.setattr(settings, "PII_ENCRYPTION_KEY", "a-key", raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "a-secret", raising=False)
    return monkeypatch


def test_complete_configuration_is_ready(production):
    assert readiness.missing_requirements() == []
    assert readiness.status()["ready"] is True


def test_missing_secret_is_named(production):
    production.setattr(settings, "IDENTITY_PEPPER", "", raising=False)
    missing = readiness.status()["missing"]
    assert [m["key"] for m in missing] == ["IDENTITY_PEPPER"]
    # Says what stops working, not just that something is wrong.
    assert "sesión" in missing[0]["breaks"]


def test_default_secret_key_counts_as_missing(production):
    """A left-over dev default is as dangerous as no value at all."""
    production.setattr(settings, "SECRET_KEY", "dev-secret-key", raising=False)
    assert "SECRET_KEY" in [m["key"] for m in readiness.status()["missing"]]


def test_development_does_not_require_secrets(production):
    production.setattr(settings, "DEBUG", True, raising=False)
    production.setattr(settings, "IDENTITY_PEPPER", "", raising=False)
    assert readiness.missing_requirements() == []


def test_require_raises_an_actionable_error(production):
    """The message must name the variable and say it is not the user's fault."""
    from fastapi import HTTPException

    production.setattr(settings, "IDENTITY_PEPPER", "", raising=False)
    with pytest.raises(HTTPException) as exc:
        readiness.require("IDENTITY_PEPPER", "iniciar sesión")

    assert exc.value.status_code == 503
    assert "IDENTITY_PEPPER" in exc.value.detail
    assert "no es de tu cuenta" in exc.value.detail or "no de tu cuenta" in exc.value.detail \
        or "problema de despliegue" in exc.value.detail


async def test_login_reports_missing_configuration_instead_of_a_generic_error(
    client, monkeypatch
):
    """The regression that started this: an opaque ref on every login."""
    monkeypatch.setattr(settings, "DEBUG", False, raising=False)
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", "", raising=False)

    response = await client.post("/api/auth/login", json={
        "rut": "11111111-1", "email": "x@y.cl",
    })
    assert response.status_code == 503
    body = response.json()
    assert "IDENTITY_PEPPER" in body["detail"]
    assert "ref:" not in body["detail"], "volvió al mensaje opaco"


async def test_health_surfaces_missing_configuration(client, monkeypatch):
    """/health must not report 'healthy' while auth is down."""
    monkeypatch.setattr(settings, "DEBUG", False, raising=False)
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", "", raising=False)

    response = await client.get("/health")
    body = response.json()
    assert body["status"] == "degraded"
    assert response.status_code == 503
    assert "IDENTITY_PEPPER" in str(body["configuration"]["missing"])
