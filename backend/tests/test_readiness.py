"""Operational liveness and fail-closed deployment readiness."""

import pytest

from app.core import readiness
from app.core.config import settings
from app.core.database import Database


async def test_live_endpoint_does_not_depend_on_external_services(client):
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


async def test_live_endpoint_is_not_rate_limited(client):
    responses = [await client.get("/health/live") for _ in range(110)]

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["status"] == "alive" for response in responses)


async def test_demo_environment_is_operational_but_not_production_ready(client):
    response = await client.get("/health/ready")
    data = response.json()

    assert response.status_code == 200
    assert data["configuration"]["environment"] == "test"
    assert data["configuration"]["minting"]["mode"] == "demo"
    assert data["configuration"]["ready"] is True
    assert data["configuration"]["production_ready"] is False


async def test_production_rejects_demo_mode_in_readiness(client, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "MINT_MODE", "demo")

    response = await client.get("/health/ready")
    data = response.json()

    assert response.status_code == 503
    assert data["status"] == "degraded"
    assert data["configuration"]["ready"] is False
    assert any(
        "no está permitido" in blocker
        for blocker in data["configuration"]["minting"]["blockers"]
    )


async def test_readiness_fails_when_required_indexes_are_missing(client, monkeypatch):
    monkeypatch.setattr(Database, "indexes_ready", False)

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["indexes"]["ready"] is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("SECRET_KEY", "dev-secret-key"),
        ("SECRET_KEY", "short-secret"),
        ("IDENTITY_PEPPER", "too-short"),
        ("PII_ENCRYPTION_KEY", "not-a-fernet-key"),
    ],
)
async def test_readiness_rejects_insecure_or_malformed_secrets(
    client,
    monkeypatch,
    key,
    value,
):
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, key, value)

    response = await client.get("/health/ready")
    data = response.json()

    assert response.status_code == 503
    assert data["configuration"]["ready"] is False
    assert key in {
        requirement["key"] for requirement in data["configuration"]["missing"]
    }


async def test_production_rejects_public_secret_even_if_debug_is_enabled(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "SECRET_KEY", "dev-secret-key")

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert "SECRET_KEY" in {
        requirement["key"]
        for requirement in response.json()["configuration"]["missing"]
    }


@pytest.mark.parametrize(
    "mongo_url",
    [
        "mongodb://localhost:27017",
        "mongodb://127.0.0.1:27017",
        "http://database.example.com",
        "not-a-mongo-uri",
        "mongodb://[broken",
        "",
    ],
)
async def test_production_requires_explicit_valid_mongo_url(
    client,
    monkeypatch,
    mongo_url,
):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "MONGO_URL", mongo_url)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert "MONGO_URL" in {
        requirement["key"]
        for requirement in response.json()["configuration"]["missing"]
    }


async def test_production_accepts_remote_mongodb_uri_as_configured(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(
        settings,
        "MONGO_URL",
        "mongodb+srv://dao.example.mongodb.net/dao_ciudadana",
    )

    assert readiness.requirement_is_valid("MONGO_URL") is True
    assert "MONGO_URL" not in {
        requirement.key for requirement in readiness.missing_requirements()
    }


async def test_onchain_mode_rejects_nonempty_malformed_configuration(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "MINT_MODE", "onchain")
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "x")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "x")
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "x")

    response = await client.get("/health/ready")
    onchain = response.json()["configuration"]["minting"]["onchain"]

    assert response.status_code == 503
    assert onchain["configured"] is False
    assert set(onchain["invalid"]) == {
        "SEPOLIA_RPC_URL",
        "SBT_CONTRACT_ADDRESS",
        "MINTER_PRIVATE_KEY",
    }


async def test_production_readiness_rejects_unsafe_cross_setting_combinations(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "CORS_ORIGINS", "*")
    monkeypatch.setattr(settings, "CORS_ORIGIN_REGEX", ".*")
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", False)
    monkeypatch.setattr(settings, "MEMBERSHIP_SOURCE", "mongo")
    monkeypatch.setattr(settings, "SIWE_DOMAIN", "dao-ciudadana")
    monkeypatch.setattr(settings, "SIWE_URI", "https://dao-ciudadana")

    response = await client.get("/health/ready")
    blockers = response.json()["configuration"]["blockers"]

    assert response.status_code == 503
    assert any("DEBUG" in blocker for blocker in blockers)
    assert any("CORS_ORIGINS" in blocker for blocker in blockers)
    assert any("CORS_ORIGIN_REGEX" in blocker for blocker in blockers)
    assert any("SIGNED_BALLOTS_REQUIRED" in blocker for blocker in blockers)
    assert any("MEMBERSHIP_SOURCE=mongo" in blocker for blocker in blockers)
    assert any("SIWE_DOMAIN" in blocker for blocker in blockers)


async def test_production_readiness_rejects_embedded_wildcard_and_non_https_cors(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "CORS_ORIGINS", "https://estamosdao.cl,*")
    wildcard_blockers = readiness.deployment_blockers()

    monkeypatch.setattr(settings, "CORS_ORIGINS", "http://estamosdao.cl/path")
    malformed_blockers = readiness.deployment_blockers()

    assert any("CORS_ORIGINS" in blocker for blocker in wildcard_blockers)
    assert any("orígenes HTTPS exactos" in blocker for blocker in malformed_blockers)


async def test_unimplemented_onchain_membership_source_is_never_ready(
    client,
    monkeypatch,
):
    monkeypatch.setattr(settings, "MEMBERSHIP_SOURCE", "onchain")

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert any(
        "MEMBERSHIP_SOURCE=onchain" in blocker
        for blocker in response.json()["configuration"]["blockers"]
    )
