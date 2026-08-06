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
    if key == "PII_ENCRYPTION_KEY":
        monkeypatch.setattr(settings, "PII_ENCRYPTION_KEYS", "")

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


async def test_the_zk_relayer_is_reported_even_when_mint_mode_is_not_onchain(
    client,
    monkeypatch,
):
    """El minteo real no consulta `MINT_MODE`, así que su estado no puede
    esconderse detrás de él.

    `/health` solo sondeaba la cadena con `MINT_MODE=onchain`. Como el relayer
    ZK (`/membership/mint-zk`) no mira esa variable, un despliegue con el
    relayer inservible se anunciaba "listo".
    """
    monkeypatch.setattr(settings, "MINT_MODE", "disabled")
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "")
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "")

    response = await client.get("/health/ready")
    relayer = response.json()["configuration"]["minting"]["zk_relayer"]

    assert relayer["available"] is False
    assert any("relayer ZK no está configurado" in b for b in relayer["blockers"])


async def test_a_relayer_without_root_manager_role_is_flagged(client, monkeypatch):
    """Sin ROOT_MANAGER_ROLE no se aprueban raíces, y sin raíz nadie mintea.

    Tiene que verse en readiness y no descubrirse cuando falle el alta de la
    primera persona.
    """
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)
    monkeypatch.setattr(settings, "MINTER_PRIVATE_KEY", "0x" + "22" * 32)

    from app.services import chain_service

    monkeypatch.setattr(
        chain_service,
        "runtime_status",
        lambda: {"ready": True, "errors": [], "can_approve_roots": False},
    )

    response = await client.get("/health/ready")
    relayer = response.json()["configuration"]["minting"]["zk_relayer"]

    assert any("ROOT_MANAGER_ROLE" in blocker for blocker in relayer["blockers"])


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


async def test_onchain_membership_source_without_rpc_is_never_ready(
    client,
    monkeypatch,
):
    """El verificador on-chain existe (ROADMAP 3.1), pero sin RPC ni contrato
    solo sabría responder 503: eso no es un despliegue listo."""
    monkeypatch.setattr(settings, "MEMBERSHIP_SOURCE", "onchain")
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "")

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert any(
        "MEMBERSHIP_SOURCE=onchain" in blocker
        for blocker in response.json()["configuration"]["blockers"]
    )


async def test_onchain_membership_source_with_rpc_is_not_blocked(monkeypatch):
    monkeypatch.setattr(settings, "MEMBERSHIP_SOURCE", "onchain")
    monkeypatch.setattr(settings, "SEPOLIA_RPC_URL", "https://sepolia.example/rpc")
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", "0x" + "11" * 20)

    blockers = readiness.deployment_blockers()

    assert not any("MEMBERSHIP_SOURCE=onchain" in blocker for blocker in blockers)


# === Servicios añadidos después de la primera pasada ===


def _production(monkeypatch, **overrides):
    """Producción con lo mínimo bien configurado, salvo lo que se sobreescriba."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 48)
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", "p" * 48)
    monkeypatch.setattr(settings, "SIWE_DOMAIN", "estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_URI", "https://estamosdao.cl")
    monkeypatch.setattr(settings, "CORS_ORIGINS", "https://estamosdao.cl")
    monkeypatch.setattr(settings, "SIGNED_BALLOTS_REQUIRED", True)
    monkeypatch.setattr(
        settings, "MONGO_URL", "mongodb+srv://user:pw@cluster.example/db"
    )
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value)


def test_production_requires_the_credential_issuer(monkeypatch):
    """Sin emisor no se puede emitir ninguna credencial: es un requisito duro."""
    _production(monkeypatch, IDENTITY_ISSUER_PRIVATE_KEY="")

    missing = [r.key for r in readiness.missing_requirements()]

    assert "IDENTITY_ISSUER_PRIVATE_KEY" in missing


def test_the_issuer_key_must_be_a_usable_ethereum_key(monkeypatch):
    """Una cadena cualquiera fallaría con un error opaco al primer intento."""
    monkeypatch.setattr(settings, "IDENTITY_ISSUER_PRIVATE_KEY", "no-es-una-llave")
    assert readiness.requirement_is_valid("IDENTITY_ISSUER_PRIVATE_KEY") is False

    monkeypatch.setattr(settings, "IDENTITY_ISSUER_PRIVATE_KEY", "0x" + "5a" * 32)
    assert readiness.requirement_is_valid("IDENTITY_ISSUER_PRIVATE_KEY") is True


def test_demo_does_not_require_the_issuer(monkeypatch):
    """En demo su ausencia es legítima: el endpoint ya falla cerrado solo."""
    monkeypatch.setattr(settings, "APP_ENV", "demo")
    monkeypatch.setattr(settings, "IDENTITY_ISSUER_PRIVATE_KEY", "")

    missing = [r.key for r in readiness.missing_requirements()]

    assert "IDENTITY_ISSUER_PRIVATE_KEY" not in missing


def test_production_blocks_without_a_civil_provider(monkeypatch):
    _production(monkeypatch, IDENTITY_PROVIDER="")

    blockers = " ".join(readiness.deployment_blockers())

    assert "IDENTITY_PROVIDER" in blockers


def test_production_blocks_without_shared_rate_limiting(monkeypatch):
    """Con varias instancias y sin Redis, el límite efectivo se multiplica."""
    _production(monkeypatch, REDIS_URL="")

    blockers = " ".join(readiness.deployment_blockers())

    assert "REDIS_URL" in blockers


def test_production_blocks_without_the_membership_contract(monkeypatch):
    _production(monkeypatch, SBT_CONTRACT_ADDRESS="")

    blockers = " ".join(readiness.deployment_blockers())

    assert "SBT_CONTRACT_ADDRESS" in blockers


# === Qué puede hacer realmente el despliegue ===


def test_feature_status_reflects_configuration_not_intention(monkeypatch):
    """Un booleano `ready` no dice QUÉ funciona; esto sí."""
    monkeypatch.setattr(settings, "IDENTITY_ISSUER_PRIVATE_KEY", "")
    monkeypatch.setattr(settings, "IDENTITY_PROVIDER", "")
    monkeypatch.setattr(settings, "REDIS_URL", "")

    features = readiness.feature_status()

    assert features["identity_issuance"]["available"] is False
    assert features["shared_rate_limiting"]["available"] is False
    # El backend nunca es custodio: forma parte del contrato de API.
    assert features["sponsored_minting"]["custodial"] is False
    # MACI registra llaves pero NO habilita votación privada.
    assert features["maci"]["key_registry"] is True
    assert features["maci"]["private_voting"] is False


def test_feature_status_turns_on_with_real_configuration(monkeypatch):
    monkeypatch.setattr(settings, "IDENTITY_ISSUER_PRIVATE_KEY", "0x" + "5a" * 32)
    monkeypatch.setattr(settings, "IDENTITY_PROVIDER", "clave-unica")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://cache:6379/0")

    features = readiness.feature_status()

    assert features["identity_issuance"]["available"] is True
    assert features["identity_issuance"]["civil_provider"] == "clave-unica"
    assert features["shared_rate_limiting"]["available"] is True
