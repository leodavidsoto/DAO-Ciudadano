"""
Emisión de credenciales de identidad ZK (/api/auth/identity-credential).

Lo que estos tests protegen, por orden de importancia:

1. Que el endpoint NO herede el bloqueo de los simuladores. `auth.py` apaga
   ClaveÚnica/NFC/liveness en producción con una dependencia a nivel de router;
   si este endpoint acabara colgando de ahí, devolvería 503 justo donde debe
   servir. Vive en `routers/identity.py` precisamente por eso.
2. Que exija sesión SIWE de la MISMA wallet: pedir una credencial "para" otra
   dirección emitiría algo que su dueño legítimo no puede usar.
3. Que falle cerrado sin proveedor civil, sin emisor y sin contrato.
"""
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.config import settings
from app.services import identity_grant, identity_issuer

ISSUER = Account.from_key("0x" + "5a" * 32)
CITIZEN = Account.from_key("0x" + "6b" * 32)
OTHER = Account.from_key("0x" + "7c" * 32)

CONTRACT = "0x" + "ab" * 20
SCOPE = 16645906639000314148974453730666249407391726919646577242780652979940179738392
COMMITMENT = 12345678901234567890123456789012345678901234567890


async def _session(client, account):
    """Sesión SIWE real: challenge + firma + verify."""
    challenge = await client.post(
        "/api/wallet/challenge", json={"address": account.address}
    )
    data = challenge.json()
    signature = account.sign_message(
        encode_defunct(text=data["message"])
    ).signature.hex()
    verify = await client.post(
        "/api/wallet/verify",
        json={
            "address": account.address,
            "nonce": data["nonce"],
            "signature": signature,
        },
    )
    return {"Authorization": f"Bearer {verify.json()['token']}"}


def _payload(wallet, grant, **overrides):
    body = {
        "wallet_address": wallet,
        "identity_commitment": str(COMMITMENT),
        "membership_scope": str(SCOPE),
        "membership_contract": CONTRACT,
        "chain_id": str(settings.SIWE_CHAIN_ID),
        "identity_grant": grant,
    }
    body.update(overrides)
    return body


@pytest.fixture
def issuer_configured(monkeypatch):
    """Emisor y contrato configurados, con la cadena simulada.

    `membership_scope()` y `approve_identity_root()` se sustituyen porque
    tocan un RPC real. Lo que se prueba aquí es la lógica del emisor; que el
    scope se lea de la cadena y no de la configuración ya es una decisión
    fijada en identity_issuer.
    """
    from app.services import chain_service

    monkeypatch.setattr(settings, "IDENTITY_ISSUER_PRIVATE_KEY", "0x" + "5a" * 32)
    monkeypatch.setattr(settings, "SBT_CONTRACT_ADDRESS", CONTRACT)
    monkeypatch.setattr(settings, "IDENTITY_PROVIDER", "clave-unica-sandbox")
    monkeypatch.setattr(chain_service, "membership_scope", lambda: SCOPE)
    approvals = []
    monkeypatch.setattr(
        chain_service, "approve_identity_root", lambda root: approvals.append(root)
    )
    return approvals


@pytest.fixture
def production_siwe(monkeypatch):
    """Producción con SIWE bien configurado.

    Sin esto, `APP_ENV=production` hace que challenge/verify y `current_address`
    devuelvan 503 por la configuración SIWE de desarrollo (P-22), y un test
    sobre el bloqueo de los demos mediría esa otra cosa.
    """
    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 48)
    monkeypatch.setattr(settings, "SIWE_DOMAIN", "estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_URI", "https://estamosdao.cl")
    monkeypatch.setattr(settings, "APP_ENV", "production")


# === El punto crítico: no heredar el bloqueo de los demos ===

async def test_endpoint_is_not_blocked_by_the_demo_gate(
    client, issuer_configured, production_siwe
):
    """En producción los simuladores dan 503; este endpoint NO debe hacerlo.

    Debe fallar por sus propias razones (grant inválido), no por el bloqueo
    que apaga ClaveÚnica/NFC/liveness.
    """
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/auth/identity-credential",
        json=_payload(CITIZEN.address, "grant-inexistente"),
        headers=headers,
    )

    assert response.status_code != 503, (
        "El endpoint heredó el bloqueo de los simuladores de identidad"
    )
    assert response.status_code == 403
    assert "grant" in response.json()["detail"].lower()


async def test_demo_routes_stay_blocked_in_production(client, monkeypatch):
    """Contraprueba: los simuladores siguen apagados en producción."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    response = await client.post("/api/auth/nfc", json={})
    assert response.status_code == 503


# === Autenticación ===

async def test_requires_a_wallet_session(client, issuer_configured):
    response = await client.post(
        "/api/auth/identity-credential",
        json=_payload(CITIZEN.address, "cualquiera"),
    )
    assert response.status_code == 401


async def test_cannot_request_a_credential_for_another_wallet(client, issuer_configured):
    """La credencial queda ligada a la wallet dentro de la hoja del árbol."""
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/auth/identity-credential",
        json=_payload(OTHER.address, "cualquiera"),
        headers=headers,
    )

    assert response.status_code == 403


# === Fallar cerrado ===

async def test_without_civil_provider_production_refuses(
    client, monkeypatch, production_siwe
):
    monkeypatch.setattr(settings, "IDENTITY_PROVIDER", "")
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/auth/identity-credential",
        json=_payload(CITIZEN.address, "cualquiera"),
        headers=headers,
    )

    assert response.status_code == 503
    assert "proveedor" in response.json()["detail"].lower()


async def test_rejects_a_contract_that_is_not_the_configured_one(client, issuer_configured):
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/auth/identity-credential",
        json=_payload(CITIZEN.address, "x", membership_contract="0x" + "cd" * 20),
        headers=headers,
    )

    assert response.status_code == 422


async def test_rejects_another_chain(client, issuer_configured):
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/auth/identity-credential",
        json=_payload(CITIZEN.address, "x", chain_id="1"),
        headers=headers,
    )

    assert response.status_code == 422


async def test_rejects_commitments_outside_the_field(client, issuer_configured):
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/auth/identity-credential",
        json=_payload(CITIZEN.address, "x", identity_commitment="0"),
        headers=headers,
    )

    assert response.status_code == 422


# === Grants ===

async def test_grant_is_single_use(client):
    grant = await identity_grant.issue("sujeto-1", provider="clave-unica-sandbox")

    assert await identity_grant.consume(grant) == "sujeto-1"
    with pytest.raises(identity_grant.IdentityGrantError):
        await identity_grant.consume(grant)


async def test_grant_value_is_never_stored(client):
    """Quien lea la base de datos no puede canjear un grant ajeno."""
    grant = await identity_grant.issue("sujeto-2", provider="clave-unica-sandbox")

    record = await identity_grant.identity_grants_collection().find_one(
        {"subject_key": "sujeto-2"}
    )

    assert grant not in str(record)
    assert record["digest"] == identity_grant.digest(grant)


# === Firma EIP-191 ===

def test_credential_message_is_the_exact_agreed_format():
    """El mensaje es contrato literal con el frontend (REQUEST_TO_CLAUDE.md).

    Dirección en minúsculas, enteros decimales, este orden de líneas. Un solo
    carácter distinto y el cliente no recupera al firmante.
    """
    message = identity_issuer.credential_message(
        wallet_address="0xAbC0000000000000000000000000000000000001",
        identity_root=111,
        membership_scope=222,
        identity_commitment=333,
    )

    assert message == (
        "DAO Ciudadana Identity Credential v1\n"
        "recipient:0xabc0000000000000000000000000000000000001\n"
        "identityRoot:111\n"
        "scope:222\n"
        "commitment:333"
    )


def test_signature_recovers_the_configured_issuer(monkeypatch):
    """El cliente fija la dirección del emisor; debe poder recuperarla."""
    monkeypatch.setattr(settings, "IDENTITY_ISSUER_PRIVATE_KEY", "0x" + "5a" * 32)

    message = identity_issuer.credential_message(CITIZEN.address, 1, 2, 3)
    signature = identity_issuer.sign_credential(message)

    recovered = Account.recover_message(
        encode_defunct(text=message), signature=signature
    )
    assert recovered == ISSUER.address
    assert identity_issuer.issuer_address() == ISSUER.address


async def test_issuer_endpoint_reports_unconfigured_honestly(client, monkeypatch):
    monkeypatch.setattr(settings, "IDENTITY_ISSUER_PRIVATE_KEY", "")

    body = (await client.get("/api/auth/identity-issuer")).json()

    assert body == {"configured": False, "issuer_address": None}


# === Camino completo ===

async def test_issues_a_credential_and_publishes_the_root(client, issuer_configured):
    """Camino feliz: canjea el grant, inserta la hoja, aprueba la raíz y firma."""
    approvals = issuer_configured
    grant = await identity_grant.issue("sujeto-feliz", provider="clave-unica-sandbox")
    headers = await _session(client, CITIZEN)

    response = await client.post(
        "/api/auth/identity-credential",
        json=_payload(CITIZEN.address, grant),
        headers=headers,
    )

    assert response.status_code == 200
    identity = response.json()["identity"]

    # 25 niveles, como exige el circuito MembershipEligibility(25).
    assert len(identity["path_elements"]) == 25
    assert len(identity["path_indices"]) == 25
    assert identity["identity_commitment"] == str(COMMITMENT)
    assert identity["membership_scope"] == str(SCOPE)

    # La raíz se publicó on-chain ANTES de responder: si no, el ciudadano
    # tendría una credencial que el contrato rechaza.
    assert approvals == [int(identity["identity_root"])]

    # La firma debe recuperar al emisor que el cliente tiene fijado.
    message = identity_issuer.credential_message(
        CITIZEN.address,
        int(identity["identity_root"]),
        SCOPE,
        COMMITMENT,
    )
    recovered = Account.recover_message(
        encode_defunct(text=message), signature=identity["signature"]
    )
    assert recovered == ISSUER.address


async def test_a_spent_grant_cannot_produce_a_second_identity(client, issuer_configured):
    """Reintentar con el mismo grant devuelve la MISMA hoja, no otra."""
    grant = await identity_grant.issue("sujeto-reintento", provider="clave-unica-sandbox")
    headers = await _session(client, CITIZEN)

    first = await client.post(
        "/api/auth/identity-credential",
        json=_payload(CITIZEN.address, grant),
        headers=headers,
    )
    second = await client.post(
        "/api/auth/identity-credential",
        json=_payload(CITIZEN.address, grant),
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert (
        first.json()["identity"]["identity_root"]
        == second.json()["identity"]["identity_root"]
    )
