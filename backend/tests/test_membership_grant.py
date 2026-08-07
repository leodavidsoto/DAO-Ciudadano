"""
Grant de membresía: emisión, un solo uso y reconciliación (ROADMAP 1.10, P-4).

Las tres reglas que este archivo fija como contrato:

1. **El servidor emite y el servidor certifica.** El JWT lleva sujeto y nivel,
   dura poco, y solo lo firma el backend. Nadie más puede fabricar uno.
2. **Un solo uso.** El jti se persiste al reclamarlo y es terminal en cuanto
   hay membresía: ni otra wallet, ni la misma, ni una identidad ya dada de
   alta pueden volver a usarlo.
3. **Un fallo transitorio no cuesta una identidad.** Si el alta falla por red
   o por gas, el mismo grant sigue sirviendo para reintentar; y cuando la
   cadena confirma, `members` pasa a `onchain` en una sola escritura.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.core.config import settings
from app.core.database import members_collection
from app.services import membership_grant, mint_operations
from app.services.blockchain_service import MintingUnavailable, blockchain_service

CITIZEN = Account.from_key("0x" + "3c" * 32)
OTHER = Account.from_key("0x" + "4d" * 32)
CITIZEN_ADDRESS = CITIZEN.address.lower()
OTHER_ADDRESS = OTHER.address.lower()

SUBJECT = "subject-key-ciego-del-run"


async def _sign_in(client, account):
    challenge = await client.post(
        "/api/wallet/challenge", json={"address": account.address}
    )
    body = challenge.json()
    signed = Account.sign_message(
        encode_defunct(text=body["message"]), private_key=account.key
    )
    verify = await client.post(
        "/api/wallet/verify",
        json={
            "address": account.address,
            "nonce": body["nonce"],
            "signature": signed.signature.hex(),
        },
    )
    return {"Authorization": f"Bearer {verify.json()['token']}"}


def _grant(subject=SUBJECT, level="CLAVE_UNICA", provider="clave-unica"):
    return membership_grant.issue(
        subject_key=subject, assurance_level=level, provider=provider
    )


async def _mint(client, account, grant, address=None):
    headers = await _sign_in(client, account)
    return await client.post(
        "/api/membership/mint",
        json={
            "wallet_address": address or account.address,
            "membership_grant": grant,
        },
        headers=headers,
    )


# === 1. Emisión: qué certifica el servidor ====================================


def test_issued_grant_certifies_subject_and_level_with_a_short_ttl():
    token = _grant()

    claims = membership_grant.verify(token)

    assert claims.subject_key == SUBJECT
    assert claims.assurance_level == "CLAVE_UNICA"
    assert claims.provider == "clave-unica"
    # 15 minutos por defecto: suficiente para conectar la wallet, corto para
    # que un token filtrado no sea una autorización de alta indefinida.
    remaining = claims.expires_at - datetime.now(timezone.utc)
    assert timedelta(seconds=0) < remaining <= timedelta(
        seconds=settings.MEMBERSHIP_GRANT_TTL_SECONDS
    )
    assert settings.MEMBERSHIP_GRANT_TTL_SECONDS == 900


def test_the_grant_never_carries_civil_data():
    """`sub` es el índice ciego, no el RUN. El token no identifica a nadie."""
    payload = jwt.decode(
        _grant(),
        settings.SECRET_KEY,
        algorithms=[membership_grant.ALGORITHM],
        audience=membership_grant.AUDIENCE,
        issuer=membership_grant.ISSUER,
    )

    assert payload["sub"] == SUBJECT
    assert set(payload) == {"iss", "aud", "sub", "lvl", "prv", "iat", "exp", "jti"}


def test_a_grant_signed_with_another_key_is_rejected():
    forged = jwt.encode(
        {
            "iss": membership_grant.ISSUER,
            "aud": membership_grant.AUDIENCE,
            "sub": SUBJECT,
            "lvl": "AL4_MAXIMO",
            "prv": "inventado",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "jti": "forjado",
        },
        "otra-llave-cualquiera",
        algorithm="HS256",
    )

    with pytest.raises(membership_grant.MembershipGrantError):
        membership_grant.verify(forged)


def test_an_expired_grant_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "MEMBERSHIP_GRANT_TTL_SECONDS", -1)
    expired = _grant()

    with pytest.raises(membership_grant.MembershipGrantError, match="expiró"):
        membership_grant.verify(expired)


def test_a_wallet_session_token_is_not_a_membership_grant():
    """Misma llave de firma, otra audiencia: no sirve como grant.

    Sin `aud` propio, quien ya controla una wallet reenviaría su JWT de sesión
    y volvería a autoafirmarse el nivel — exactamente lo que P-4 describe.
    """
    from app.services import siwe_service

    session_token = siwe_service.issue_token(CITIZEN_ADDRESS)

    with pytest.raises(membership_grant.MembershipGrantError):
        membership_grant.verify(session_token)


def test_a_grant_without_a_level_certifies_nothing():
    incomplete = jwt.encode(
        {
            "iss": membership_grant.ISSUER,
            "aud": membership_grant.AUDIENCE,
            "sub": SUBJECT,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
            "jti": "sin-nivel",
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )

    with pytest.raises(membership_grant.MembershipGrantError, match="incompleto"):
        membership_grant.verify(incomplete)


def test_production_without_a_configured_provider_refuses_to_issue(monkeypatch):
    """Falla cerrado: un grant que no respalda una verificación real es peor
    que no tener grant, porque el minteo lo trataría como si lo respaldara."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "IDENTITY_PROVIDER", "")

    with pytest.raises(membership_grant.MembershipGrantError, match="proveedor"):
        _grant()


# === 2. Un solo uso ===========================================================


async def test_mint_requires_a_grant_and_burns_its_jti(client):
    grant = _grant()
    claims = membership_grant.verify(grant)

    response = await _mint(client, CITIZEN, grant)

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["assurance_level"] == "CLAVE_UNICA"

    burned = await membership_grant.membership_grants_collection().find_one(
        {"jti": claims.jti}
    )
    assert burned["status"] == membership_grant.CONSUMED
    assert burned["wallet_address"] == CITIZEN_ADDRESS
    assert burned["subject_key"] == SUBJECT
    assert burned["token_id"] == response.json()["token_id"]


async def test_a_spent_grant_cannot_mint_again(client):
    """Ni siquiera para la misma wallet: el estado consumido es terminal."""
    grant = _grant()
    assert (await _mint(client, CITIZEN, grant)).json()["ok"] is True

    replay = await _mint(client, CITIZEN, grant)

    assert replay.status_code == 409
    assert "ya se usó" in replay.json()["detail"]


async def test_a_stolen_grant_cannot_be_redirected_to_another_wallet(client):
    """El jti queda atado a la primera wallet que lo reclamó.

    Sin esto, interceptar el grant de otra persona bastaría para convertir su
    verificación civil en una membresía propia.
    """
    grant = _grant()
    claims = membership_grant.verify(grant)
    await membership_grant.claim(claims, CITIZEN_ADDRESS)

    stolen = await _mint(client, OTHER, grant)

    assert stolen.status_code == 409
    assert "otra wallet" in stolen.json()["detail"]


async def test_the_same_identity_cannot_mint_twice_with_two_grants(client):
    """Identificarse dos veces no da dos membresías.

    Cada flujo civil emite un jti distinto, así que el ledger por token no
    basta: la regla es por sujeto.
    """
    assert (await _mint(client, CITIZEN, _grant())).json()["ok"] is True

    second = await _mint(client, OTHER, _grant())

    assert second.status_code == 409
    # El mensaje distingue este caso del grant reservado: aquí el token es
    # nuevo y válido; lo que ya está usado es la identidad.
    assert "ya tiene una membresía" in second.json()["detail"]


async def test_an_invalid_grant_never_reaches_the_ledger(client):
    """Un token que no valida no deja rastro de intento en Mongo."""
    response = await _mint(client, CITIZEN, "esto-no-es-un-jwt")

    assert response.status_code == 403
    assert await membership_grant.membership_grants_collection().count_documents({}) == 0


# === 3. Reconciliación: un fallo transitorio no cuesta la identidad ===========


async def test_a_transient_failure_keeps_the_grant_usable_for_a_retry(
    client, monkeypatch
):
    """El caso que motiva el consumo en dos fases.

    Quemar el jti de golpe al recibirlo dejaría a la persona verificada, sin
    membresía y sin token: tendría que repetir ClaveÚnica por un timeout del
    servidor.
    """
    grant = _grant()
    claims = membership_grant.verify(grant)

    async def failing_mint(**kwargs):
        return (False, None, None, "No se pudo confirmar el minteo on-chain.")

    monkeypatch.setattr(blockchain_service, "mint_sbt", failing_mint)
    failed = await _mint(client, CITIZEN, grant)
    assert failed.json()["ok"] is False

    # El jti está reservado —nadie más lo usa— pero NO consumido.
    reserved = await membership_grant.membership_grants_collection().find_one(
        {"jti": claims.jti}
    )
    assert reserved["status"] == membership_grant.CLAIMED
    assert reserved["last_error"] == "No se pudo confirmar el minteo on-chain."

    monkeypatch.undo()
    retry = await _mint(client, CITIZEN, grant)

    assert retry.json()["ok"] is True
    settled = await membership_grant.membership_grants_collection().find_one(
        {"jti": claims.jti}
    )
    assert settled["status"] == membership_grant.CONSUMED
    assert settled["attempts"] == 2


async def test_an_unavailable_deployment_does_not_spend_the_grant(client, monkeypatch):
    """Un 503 por configuración no debe costar una verificación civil."""
    monkeypatch.setattr(settings, "MINT_MODE", "disabled")
    grant = _grant()

    response = await _mint(client, CITIZEN, grant)
    assert response.status_code == 503

    assert await membership_grant.membership_grants_collection().count_documents({}) == 0

    monkeypatch.setattr(settings, "MINT_MODE", "demo")
    assert (await _mint(client, CITIZEN, grant)).json()["ok"] is True


async def test_the_service_gate_survives_a_caller_that_skips_the_router_check(
    monkeypatch,
):
    """`mint_sbt` repite el cierre por entorno: no depende del router."""
    monkeypatch.setattr(settings, "MINT_MODE", "disabled")

    with pytest.raises(MintingUnavailable):
        await blockchain_service.mint_sbt(
            wallet_address=CITIZEN.address,
            assurance_level="CLAVE_UNICA",
            doc_hash=SUBJECT,
        )


async def test_a_confirmed_mint_moves_the_membership_to_onchain_in_one_write(client):
    """La transición a `onchain` es una sola escritura, no una secuencia.

    `mark_confirmed` cierra la operación y refleja el SBT en `members` con un
    único `update_one` con upsert: no hay ventana en la que la fila esté a
    medio migrar, ni un borrado-y-reinserción que pierda el `created_at`.
    """
    nullifier = "0x" + "ab" * 32
    await mint_operations.mint_operations_collection().insert_one(
        {
            "nullifier_hash": nullifier,
            "wallet_address": CITIZEN_ADDRESS,
            "status": mint_operations.SUBMITTED,
            "created_at": datetime.now(timezone.utc),
        }
    )
    # Alta previa por la vía demo: es la fila que tiene que quedar promovida.
    grant = _grant()
    assert (await _mint(client, CITIZEN, grant)).json()["ok"] is True
    before = await members_collection().find_one({"wallet_address": CITIZEN_ADDRESS})
    assert before["issuance_mode"] == "demo"
    assert before["identity_verified"] is False

    await mint_operations.mark_confirmed(
        nullifier_hash=nullifier,
        wallet_address=CITIZEN_ADDRESS,
        tx_hash="0x" + "cd" * 32,
        token_id=42,
    )

    after = await members_collection().find_one({"wallet_address": CITIZEN_ADDRESS})
    assert after["issuance_mode"] == "onchain"
    assert after["identity_verified"] is True
    assert after["token_id"] == 42
    assert after["status"] == "active"
    assert after["created_at"] == before["created_at"]
    # Una sola fila: el upsert reconcilió la existente en vez de duplicarla.
    assert await members_collection().count_documents({}) == 1

    operation = await mint_operations.mint_operations_collection().find_one(
        {"nullifier_hash": nullifier}
    )
    assert operation["status"] == mint_operations.CONFIRMED


async def test_a_failed_onchain_operation_stays_retryable(client):
    """Reconciliación de la vía ZK: `failed` es reintentable, no un 409 eterno.

    Es la contraparte on-chain de la regla anterior: la identidad verificada
    (aquí, la credencial ya emitida) no se pierde porque una transacción no
    llegara a tener efecto.
    """
    nullifier = "0x" + "ef" * 32
    await mint_operations.mint_operations_collection().insert_one(
        {
            "nullifier_hash": nullifier,
            "wallet_address": CITIZEN_ADDRESS,
            "status": mint_operations.PENDING,
            "created_at": datetime.now(timezone.utc),
        }
    )
    await mint_operations.mark_failed(nullifier, "sin efecto on-chain")

    decision = await mint_operations.begin(nullifier, CITIZEN_ADDRESS)

    assert decision.action == "proceed"
    reclaimed = await mint_operations.mint_operations_collection().find_one(
        {"nullifier_hash": nullifier}
    )
    assert reclaimed["status"] == mint_operations.PENDING
    # El intento anterior se limpia: reintentar no arrastra un tx_hash muerto.
    assert "error" not in reclaimed
    assert "tx_hash" not in reclaimed
