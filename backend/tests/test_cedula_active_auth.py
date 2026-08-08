"""
Anti-replay de la cédula: Autenticación Activa de punta a punta.

El agujero que cierran estos tests era real y explotable: la Autenticación
Pasiva prueba que Chile firmó esos datos, no que el chip esté delante. Quien
consiguiera los bytes de una lectura ajena —leyendo la cédula con el CAN, o
interceptando un payload— obtenía con un `curl` una membresía a nombre de otro.

Por eso el test que importa de verdad no es que una lectura buena funcione,
sino el de la dirección contraria: **reenviar una captura completa es
rechazado**. Sin esa segunda comprobación no se habría demostrado nada, porque
es literalmente el ataque que se cierra.
"""

import base64
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services import aa_challenge, cedula_nfc, csca_trust_store, membership_grant

import emrtd_fixtures as fx

RUN = "123456785"
DG1 = fx.dg1(fx.td1_mrz())
DG2 = b"\x75\x20" + b"\xab" * 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


@pytest.fixture
def csca():
    return fx.make_csca()


@pytest.fixture
def dsc(csca):
    return fx.make_dsc(csca)


@pytest.fixture
def trust_store(tmp_path, monkeypatch, csca):
    path = tmp_path / "csca_test.pem"
    path.write_bytes(fx.trust_store_pem(csca.certificate))
    monkeypatch.setattr(csca_trust_store.settings, "CSCA_TRUST_STORE_PATH", str(path))
    csca_trust_store.reset_cache()
    yield path
    csca_trust_store.reset_cache()


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(settings, "IDENTITY_PROVIDER", "cedula-nfc")


@pytest.fixture(scope="module")
def chip_key():
    """Clave de Autenticación Activa del chip. No sale del documento."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def dg15(chip_key):
    return fx.dg15(chip_key.public_key())


@pytest.fixture
def sod_with_dg15(dsc, dg15):
    """EF.SOD que declara el hash de DG15 además de los de DG1 y DG2.

    Es la mitad que hace que la Autenticación Activa signifique algo: sin ella
    la clave del chip sería una clave cualquiera que alguien adjuntó.
    """
    return fx.build_sod(dsc, {1: DG1, 2: DG2, 15: dg15})


async def _request_challenge(client) -> tuple[str, bytes]:
    response = await client.post("/api/auth/cedula/aa-challenge")
    assert response.status_code == 200
    body = response.json()
    return body["challenge_id"], base64.b64decode(body["challenge"])


async def _read_with_active_auth(client, sod, dg15, chip_key) -> dict:
    """Simula la lectura completa: pedir desafío, hacer que el chip lo firme."""
    challenge_id, challenge = await _request_challenge(client)
    return {
        "sod": _b64(sod),
        "data_groups": {"1": _b64(DG1), "2": _b64(DG2), "15": _b64(dg15)},
        "active_authentication": {
            "challenge_id": challenge_id,
            "signature": _b64(fx.iso9796_2_ds1_signature(chip_key, challenge)),
        },
    }


# ---------------------------------------------------------------------------
# El desafío
# ---------------------------------------------------------------------------


async def test_the_server_issues_an_eight_byte_challenge(client):
    challenge_id, challenge = await _request_challenge(client)

    assert challenge_id
    # 8 bytes es lo que el chip espera en INTERNAL AUTHENTICATE.
    assert len(challenge) == aa_challenge.CHALLENGE_BYTES


async def test_two_challenges_are_never_the_same(client):
    """Si fueran predecibles, una firma capturada valdría para la siguiente."""
    first = await _request_challenge(client)
    second = await _request_challenge(client)

    assert first[0] != second[0]
    assert first[1] != second[1]


async def test_a_challenge_can_only_be_consumed_once(client):
    challenge_id, challenge = await _request_challenge(client)

    assert await aa_challenge.consume(challenge_id) == challenge
    with pytest.raises(aa_challenge.ActiveAuthChallengeError):
        await aa_challenge.consume(challenge_id)


async def test_an_unknown_challenge_is_refused(client):
    with pytest.raises(aa_challenge.ActiveAuthChallengeError):
        await aa_challenge.consume("00000000000000000000000000000000")


async def test_an_expired_challenge_is_refused(client, monkeypatch):
    """La ventana corta no es cosmética: acota cuánto vive una firma capturada."""
    challenge_id, _ = await _request_challenge(client)

    later = datetime.now(timezone.utc) + timedelta(
        seconds=aa_challenge.ttl_seconds() + 60
    )
    monkeypatch.setattr(aa_challenge, "_now", lambda: later)

    with pytest.raises(aa_challenge.ActiveAuthChallengeError, match="expiró"):
        await aa_challenge.consume(challenge_id)


# ---------------------------------------------------------------------------
# El camino completo
# ---------------------------------------------------------------------------


async def test_a_real_reading_with_active_auth_raises_the_assurance_level(
    client, trust_store, provider, sod_with_dg15, dg15, chip_key
):
    payload = await _read_with_active_auth(client, sod_with_dg15, dg15, chip_key)

    response = await client.post("/api/auth/cedula/verify", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["assurance_level"] == cedula_nfc.ASSURANCE_LEVEL_ACTIVE
    # El nivel viaja en el JWT de alta, no solo en la respuesta: es lo que
    # `POST /membership/mint` lee, y el cliente no puede tocarlo.
    assert (
        membership_grant.verify(body["membership_grant"]).assurance_level
        == cedula_nfc.ASSURANCE_LEVEL_ACTIVE
    )
    detail = body["verification"]["active_authentication"]
    assert detail["scheme"] == "rsa-iso9796-2-ds1"
    assert detail["key_bits"] == 2048


async def test_without_active_auth_the_grant_says_only_passive(
    client, trust_store, provider, dsc
):
    """El nombre del nivel dice lo que se comprobó, ni más ni menos."""
    response = await client.post(
        "/api/auth/cedula/verify",
        json={
            "sod": _b64(fx.build_sod(dsc, {1: DG1, 2: DG2})),
            "data_groups": {"1": _b64(DG1), "2": _b64(DG2)},
        },
    )

    assert response.status_code == 200
    assert response.json()["assurance_level"] == cedula_nfc.ASSURANCE_LEVEL_PASSIVE


# ---------------------------------------------------------------------------
# El ataque
# ---------------------------------------------------------------------------


async def test_replaying_a_captured_reading_is_rejected(
    client, trust_store, provider, sod_with_dg15, dg15, chip_key
):
    """LA prueba. Un payload entero capturado, reenviado tal cual.

    Es lo que hoy funciona por el camino pasivo y lo que la Autenticación
    Activa cierra: el desafío ya está quemado, así que la misma captura no
    vuelve a pasar aunque cada byte sea idéntico.
    """
    captured = await _read_with_active_auth(client, sod_with_dg15, dg15, chip_key)

    first = await client.post("/api/auth/cedula/verify", json=captured)
    assert first.status_code == 200

    replayed = await client.post("/api/auth/cedula/verify", json=captured)

    assert replayed.status_code == 401
    body = replayed.json()
    assert "identity_grant" not in body
    assert "membership_grant" not in body


async def test_a_captured_signature_does_not_fit_a_fresh_challenge(
    client, trust_store, provider, sod_with_dg15, dg15, chip_key
):
    """El siguiente movimiento del atacante, y por qué tampoco funciona.

    Sabiendo que el desafío se quema, lo natural es pedir uno nuevo y reenviar
    la firma capturada. No sirve: la firma cubre el desafío anterior, y firmar
    el nuevo exige la clave privada del chip, que no se puede extraer.
    """
    captured = await _read_with_active_auth(client, sod_with_dg15, dg15, chip_key)
    assert (await client.post("/api/auth/cedula/verify", json=captured)).status_code == 200

    fresh_id, _ = await _request_challenge(client)
    forged = {**captured}
    forged["active_authentication"] = {
        "challenge_id": fresh_id,
        "signature": captured["active_authentication"]["signature"],
    }

    response = await client.post("/api/auth/cedula/verify", json=forged)

    assert response.status_code == 401


async def test_the_attackers_own_key_in_dg15_is_rejected(
    client, trust_store, provider, dsc, dg15, chip_key
):
    """Sin ligar DG15 al SOD, la Autenticación Activa sería un teatro caro.

    El atacante puede firmar cualquier desafío: le basta con poner SU clave
    pública en el DG15 que envía. Lo que lo impide es que el hash de DG15 esté
    declarado en un SOD que firmó el Registro Civil.
    """
    from cryptography.hazmat.primitives.asymmetric import rsa

    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker_dg15 = fx.dg15(attacker_key.public_key())

    # SOD auténtico: declara el DG15 del chip real, no el del atacante.
    sod = fx.build_sod(dsc, {1: DG1, 2: DG2, 15: dg15})

    challenge_id, challenge = await _request_challenge(client)
    response = await client.post(
        "/api/auth/cedula/verify",
        json={
            "sod": _b64(sod),
            "data_groups": {
                "1": _b64(DG1),
                "2": _b64(DG2),
                "15": _b64(attacker_dg15),
            },
            "active_authentication": {
                "challenge_id": challenge_id,
                # Firma impecable... con la clave equivocada.
                "signature": _b64(
                    fx.iso9796_2_ds1_signature(attacker_key, challenge)
                ),
            },
        },
    )

    assert response.status_code == 401


async def test_a_dg15_the_sod_does_not_declare_is_rejected(
    client, trust_store, provider, dsc, dg15, chip_key
):
    """Adjuntar un DG15 a un SOD que no lo menciona tampoco cuela."""
    sod = fx.build_sod(dsc, {1: DG1, 2: DG2})  # sin DG15

    challenge_id, challenge = await _request_challenge(client)
    response = await client.post(
        "/api/auth/cedula/verify",
        json={
            "sod": _b64(sod),
            "data_groups": {"1": _b64(DG1), "2": _b64(DG2), "15": _b64(dg15)},
            "active_authentication": {
                "challenge_id": challenge_id,
                "signature": _b64(fx.iso9796_2_ds1_signature(chip_key, challenge)),
            },
        },
    )

    assert response.status_code == 401


async def test_a_signature_without_dg15_cannot_be_checked(
    client, trust_store, provider, sod_with_dg15, chip_key
):
    """Una firma sin la clave con la que comprobarla no es «verificado»."""
    challenge_id, challenge = await _request_challenge(client)
    response = await client.post(
        "/api/auth/cedula/verify",
        json={
            "sod": _b64(sod_with_dg15),
            "data_groups": {"1": _b64(DG1), "2": _b64(DG2)},
            "active_authentication": {
                "challenge_id": challenge_id,
                "signature": _b64(fx.iso9796_2_ds1_signature(chip_key, challenge)),
            },
        },
    )

    assert response.status_code == 401


async def test_a_challenge_of_the_clients_choosing_is_not_accepted(client):
    """El contrato de API no tiene por dónde meter un desafío propio.

    Es una comprobación de forma, no de criptografía: si algún día alguien
    añadiera ese campo «por comodidad», la Autenticación Activa dejaría de
    probar nada y el test lo diría.
    """
    from app.routers.cedula import ActiveAuthenticationPayload

    assert set(ActiveAuthenticationPayload.model_fields) == {
        "challenge_id",
        "signature",
    }


# ---------------------------------------------------------------------------
# Política
# ---------------------------------------------------------------------------


async def test_production_refuses_a_reading_without_active_auth(
    client, trust_store, provider, dsc, monkeypatch
):
    """Decisión de política, tomada con el dueño: producción la EXIGE.

    Mientras el camino pasivo pueda emitir un grant, el replay sigue abierto
    para quien lo use — da igual que exista un camino mejor al lado.
    """
    monkeypatch.setattr(settings, "CEDULA_REQUIRE_ACTIVE_AUTH", "true")

    response = await client.post(
        "/api/auth/cedula/verify",
        json={
            "sod": _b64(fx.build_sod(dsc, {1: DG1, 2: DG2})),
            "data_groups": {"1": _b64(DG1), "2": _b64(DG2)},
        },
    )

    assert response.status_code == 401
    assert "Autenticación Activa" in str(response.json()["detail"])


async def test_production_still_accepts_a_reading_with_active_auth(
    client, trust_store, provider, sod_with_dg15, dg15, chip_key, monkeypatch
):
    monkeypatch.setattr(settings, "CEDULA_REQUIRE_ACTIVE_AUTH", "true")
    payload = await _read_with_active_auth(client, sod_with_dg15, dg15, chip_key)

    response = await client.post("/api/auth/cedula/verify", json=payload)

    assert response.status_code == 200
    assert response.json()["assurance_level"] == cedula_nfc.ASSURANCE_LEVEL_ACTIVE


def test_the_default_policy_is_to_require_it_in_production(monkeypatch):
    monkeypatch.setattr(settings, "CEDULA_REQUIRE_ACTIVE_AUTH", "")
    monkeypatch.setattr(settings, "APP_ENV", "production")
    assert settings.cedula_requires_active_auth is True

    monkeypatch.setattr(settings, "APP_ENV", "development")
    assert settings.cedula_requires_active_auth is False


def test_the_policy_can_be_forced_in_any_environment(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "CEDULA_REQUIRE_ACTIVE_AUTH", "true")
    assert settings.cedula_requires_active_auth is True

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "CEDULA_REQUIRE_ACTIVE_AUTH", "false")
    assert settings.cedula_requires_active_auth is False
