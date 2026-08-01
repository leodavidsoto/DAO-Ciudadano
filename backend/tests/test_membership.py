"""
Membership endpoints: explicit demo mode, fail-closed production behavior,
duplicate rejection, address validation, lookups, and wallet session auth
(C-1: minting "as" another address is rejected).
"""
from datetime import datetime, timezone

from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.config import settings
from app.core.database import members_collection
from app.services.blockchain_service import blockchain_service

# Direcciones reales derivadas de llaves privadas fijas de prueba (NO usar en
# producción). Necesarias porque POST /api/membership/mint ahora exige una
# sesión de wallet (SIWE, ver services/siwe_service.py) — firmar el desafío
# requiere una llave privada real, no basta un string "0x..." arbitrario.
VALID_ACCOUNT = Account.from_key("0x" + "11" * 32)
OTHER_ACCOUNT = Account.from_key("0x" + "22" * 32)
VALID_ADDRESS = VALID_ACCOUNT.address.lower()
OTHER_ADDRESS = OTHER_ACCOUNT.address.lower()


async def _sign_in(client, account):
    """Ejecuta el flujo SIWE real (challenge + firma + verify) y devuelve
    los headers de Authorization para autenticar como esa cuenta."""
    challenge = await client.post("/api/wallet/challenge", json={"address": account.address})
    challenge.raise_for_status()
    body = challenge.json()
    signed = Account.sign_message(encode_defunct(text=body["message"]), private_key=account.key)
    verify = await client.post("/api/wallet/verify", json={
        "address": account.address,
        "nonce": body["nonce"],
        "signature": signed.signature.hex(),
    })
    verify.raise_for_status()
    return {"Authorization": f"Bearer {verify.json()['token']}"}


async def _mint(client, account=VALID_ACCOUNT, address=None, doc_hash="0xdeadbeef", level="AL2"):
    """Mintea autenticado como `account`. Por defecto usa la propia
    dirección de `account`; pásale `address` distinto para probar el
    rechazo de "mintear como otra persona" (C-1)."""
    headers = await _sign_in(client, account)
    return await client.post("/api/membership/mint", json={
        "wallet_address": address if address is not None else account.address,
        "assurance_level": level,
        "doc_hash": doc_hash,
    }, headers=headers)


async def test_mint_requires_wallet_session(client):
    """Sin Authorization: Bearer, mint se rechaza con 401 (no con un ok:false)."""
    response = await client.post("/api/membership/mint", json={
        "wallet_address": VALID_ADDRESS,
        "assurance_level": "AL2",
        "doc_hash": "0xdeadbeef",
    })
    assert response.status_code == 401


async def test_mint_is_unavailable_when_mode_is_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "MINT_MODE", "disabled")

    response = await _mint(client)

    assert response.status_code == 503
    assert "deshabilitada" in response.json()["detail"]


async def test_mint_fails_closed_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "MINT_MODE", "onchain")
    # Keep SIWE itself valid so this regression reaches the independent
    # production identity-grant guard in the mint endpoint.
    monkeypatch.setattr(settings, "SIWE_DOMAIN", "estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_URI", "https://estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_CHAIN_ID", 11155111)

    response = await _mint(client)

    assert response.status_code == 503
    assert "verificación de identidad" in response.json()["detail"]


async def test_mint_rejects_acting_as_another_address(client):
    """Autenticado como VALID_ACCOUNT pero reclamando OTHER_ADDRESS en el
    body: 403, nunca se llega a intentar el minteo (cierra C-1)."""
    response = await _mint(client, account=VALID_ACCOUNT, address=OTHER_ADDRESS)
    assert response.status_code == 403


async def test_mint_creates_member(client):
    response = await _mint(client)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["token_id"] == 1
    # chain_service no está configurado en tests: nunca se fabrica un tx_hash
    assert data["tx_hash"] is None


async def test_mint_rejects_duplicate_wallet_case_insensitive(client):
    first = await _mint(client, account=VALID_ACCOUNT)
    assert first.json()["ok"] is True

    # Mismo wallet, distinto casing en el body -- pero debe seguir
    # autenticando como la MISMA cuenta (las direcciones no distinguen
    # mayúsculas), así que ensure_acts_as_self lo sigue aceptando.
    duplicate = await _mint(client, account=VALID_ACCOUNT, address=VALID_ACCOUNT.address.upper().replace("0X", "0x"))
    data = duplicate.json()
    assert data["ok"] is False
    assert "Ya existe" in data["error"]


async def test_mint_requires_doc_hash(client):
    response = await _mint(client, doc_hash="")
    data = response.json()
    assert data["ok"] is False


async def test_token_ids_are_sequential(client):
    first = await _mint(client, account=VALID_ACCOUNT)
    second = await _mint(client, account=OTHER_ACCOUNT)
    assert first.json()["token_id"] == 1
    assert second.json()["token_id"] == 2


async def test_verify_active_demo_membership_is_valid_but_offchain(client):
    await _mint(client, account=VALID_ACCOUNT)

    found = await client.get("/api/membership/verify/1")
    data = found.json()
    assert data["valid"] is True
    assert data["onchain"] is False
    assert data["issuance_mode"] == "demo"
    assert data["identity_verified"] is False
    assert data["tx_hash"] is None
    assert data["wallet_address"] == VALID_ADDRESS
    assert data["status"] == "active"

    missing = await client.get("/api/membership/verify/999")
    assert missing.json() == {"valid": False, "onchain": False, "token_id": 999}


async def test_verify_revoked_membership_is_not_valid(client):
    await _mint(client, account=VALID_ACCOUNT)
    revoked, error = await blockchain_service.revoke_membership(1)

    assert revoked is True
    assert error is None

    response = await client.get("/api/membership/verify/1")
    data = response.json()
    assert data["valid"] is False
    assert data["onchain"] is False
    assert data["tx_hash"] is None
    assert data["status"] == "revoked"


async def test_get_member_by_wallet(client):
    await _mint(client, account=VALID_ACCOUNT)

    found = await client.get(f"/api/membership/member/{VALID_ADDRESS}")
    data = found.json()
    assert data["found"] is True
    assert data["member"]["token_id"] == 1
    assert data["member"]["valid"] is True
    assert data["member"]["issuance_mode"] == "demo"
    assert data["member"]["identity_verified"] is False
    assert "doc_hash" not in data["member"]

    missing = await client.get(f"/api/membership/member/{OTHER_ADDRESS}")
    assert missing.json()["found"] is False


async def test_demo_member_loses_governance_rights_after_production_promotion(
    client,
    monkeypatch,
):
    """Promoting the same DB must not promote self-asserted demo identity."""
    headers = await _sign_in(client, VALID_ACCOUNT)
    minted = await client.post(
        "/api/membership/mint",
        json={
            "wallet_address": VALID_ADDRESS,
            "assurance_level": "AL2",
            "doc_hash": "0xselfasserted",
        },
        headers=headers,
    )
    assert minted.json()["ok"] is True

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SIWE_DOMAIN", "estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_URI", "https://estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_CHAIN_ID", 11155111)

    verification = (await client.get("/api/membership/verify/1")).json()
    assert verification["valid"] is False
    assert verification["onchain"] is False
    assert verification["issuance_mode"] == "demo"
    assert verification["identity_verified"] is False

    lookup = (await client.get(f"/api/membership/member/{VALID_ADDRESS}")).json()
    assert lookup["member"]["valid"] is False

    governance = await client.post(
        "/api/governance/proposals",
        json={
            "title": "Propuesta no autorizada",
            "description": "Una membresía demo no puede gobernar en producción.",
            "creator_address": VALID_ADDRESS,
            "duration_days": 7,
        },
        headers=headers,
    )
    assert governance.status_code == 403
    assert "miembros activos" in governance.json()["detail"]


async def test_legacy_member_without_provenance_is_quarantined_in_production(
    client,
    monkeypatch,
):
    await members_collection().insert_one({
        "id": "legacy-member",
        "wallet_address": OTHER_ADDRESS,
        "token_id": 77,
        "doc_hash": "0xlegacy",
        "assurance_level": "AL2",
        "status": "active",
        "created_at": datetime.now(timezone.utc),
    })
    monkeypatch.setattr(settings, "APP_ENV", "production")

    verification = (await client.get("/api/membership/verify/77")).json()
    assert verification["valid"] is False
    assert verification["onchain"] is False
    assert verification["issuance_mode"] == "legacy_unverified"
    assert verification["identity_verified"] is False


async def test_revoking_twice_reports_the_membership_as_found(client):
    """Re-revoking must not claim the token does not exist.

    `update_one` reports modified_count == 0 for a no-op write, so keying the
    "not found" answer off it made an already-revoked membership look like it
    was never issued.
    """
    await _mint(client, account=VALID_ACCOUNT)

    first_ok, first_error = await blockchain_service.revoke_membership(1)
    second_ok, second_error = await blockchain_service.revoke_membership(1)
    missing_ok, missing_error = await blockchain_service.revoke_membership(999)

    assert (first_ok, first_error) == (True, None)
    assert (second_ok, second_error) == (True, None)
    assert (missing_ok, missing_error) == (False, "Token no encontrado")
