"""
ClaveÚnica OIDC real (ROADMAP 4.1).

Ningún test toca la red: se sustituyen las TRES fronteras externas —canje del
código, obtención de la clave de firma y UserInfo— y todo lo demás se ejecuta
de verdad, incluida la validación completa del `id_token`.

Lo que se comprueba no es solo el camino feliz, sino que el flujo aguante lo
que un atacante intentaría: confusión de algoritmos, `alg: none`, emisor o
audiencia ajenos, nonce de otra sesión, reutilización del `state` y RUN con
dígito verificador falso.
"""
import base64
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.core.database import get_collection
from app.services import clave_unica, identity_grant

CLIENT_ID = "dao-ciudadana-test"
ISSUER = "https://accounts.example.gob.cl/openid"
RUN_NUMBER = 12345678
RUN_DV = "5"  # dígito verificador real de 12345678

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = _KEY.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()


@pytest.fixture
def configured(monkeypatch):
    """Despliegue con ClaveÚnica configurada y sin salir a la red."""
    monkeypatch.setattr(settings, "CLAVE_UNICA_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "CLAVE_UNICA_CLIENT_SECRET", "secreto-de-prueba")
    monkeypatch.setattr(
        settings, "CLAVE_UNICA_REDIRECT_URI", "https://estamosdao.cl/clave-unica"
    )
    monkeypatch.setattr(settings, "CLAVE_UNICA_ISSUER", ISSUER)
    monkeypatch.setattr(
        settings, "CLAVE_UNICA_AUTHORIZATION_ENDPOINT", f"{ISSUER}/authorize/"
    )
    monkeypatch.setattr(settings, "CLAVE_UNICA_TOKEN_ENDPOINT", f"{ISSUER}/token/")
    monkeypatch.setattr(
        settings, "CLAVE_UNICA_USERINFO_ENDPOINT", f"{ISSUER}/userinfo/"
    )
    monkeypatch.setattr(settings, "CLAVE_UNICA_JWKS_URI", f"{ISSUER}/jwks/")
    monkeypatch.setattr(settings, "CLAVE_UNICA_ID_TOKEN_ALG", "RS256")
    monkeypatch.setattr(settings, "IDENTITY_PROVIDER", "clave-unica")
    # La clave pública se entrega sin ir al JWKS del Estado.
    monkeypatch.setattr(clave_unica, "_signing_key", lambda token: _PUBLIC_PEM)
    return monkeypatch


def _id_token(nonce, *, alg="RS256", key=None, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "sujeto-estatal-1",
        "exp": now + 300,
        "iat": now,
        "nonce": nonce,
        "name": "Ana Pérez",
        "RolUnico": {"numero": RUN_NUMBER, "DV": RUN_DV, "tipo": "RUN"},
    }
    claims.update(overrides)
    signing_key = key if key is not None else _PRIVATE_PEM
    if alg == "none":
        return jwt.encode(claims, None, algorithm=None)
    return jwt.encode(claims, signing_key, algorithm=alg)


def _stub_token_endpoint(monkeypatch, id_token, access_token="at-1"):
    monkeypatch.setattr(
        clave_unica,
        "_exchange_code",
        lambda code, verifier: {"id_token": id_token, "access_token": access_token},
    )


async def _authorize(client):
    response = await client.post("/api/auth/clave-unica/authorize")
    assert response.status_code == 200, response.json()
    return response.json()


async def _stored_session(state):
    return await get_collection("oidc_login_sessions").find_one({"state": state})


# === Sin configuración no hay flujo ===

async def test_unconfigured_deployment_refuses_in_every_environment(client):
    """No hay modo demo: un simulador de identidad civil es lo que se elimina."""
    authorize = await client.post("/api/auth/clave-unica/authorize")
    callback = await client.post(
        "/api/auth/clave-unica/callback", json={"code": "x", "state": "y"}
    )

    assert authorize.status_code == 503
    assert callback.status_code == 503
    assert "CLAVE_UNICA_CLIENT_ID" in authorize.json()["detail"]


def test_rs256_without_jwks_is_a_configuration_error(monkeypatch):
    """Sin JWKS no se puede verificar nada, y no verificar no es una opción."""
    monkeypatch.setattr(settings, "CLAVE_UNICA_ID_TOKEN_ALG", "RS256")
    monkeypatch.setattr(settings, "CLAVE_UNICA_JWKS_URI", "")

    assert "CLAVE_UNICA_JWKS_URI" in clave_unica.configuration_errors()


def test_production_requires_an_https_redirect(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "CLAVE_UNICA_REDIRECT_URI", "http://localhost/cb")

    assert "CLAVE_UNICA_REDIRECT_URI" in clave_unica.configuration_errors()


# === PKCE ===

def test_code_challenge_matches_rfc7636():
    """Vector del propio RFC 7636 (apéndice B)."""
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    assert clave_unica.code_challenge_for(verifier) == (
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


async def test_the_verifier_never_leaves_the_server(client, configured):
    body = await _authorize(client)

    session = await _stored_session(body["state"])
    assert session["code_verifier"]
    # El navegador solo ve el reto, nunca el verificador: PKCE existe para eso.
    assert session["code_verifier"] not in body["authorization_url"]
    assert "code_challenge_method=S256" in body["authorization_url"]
    expected = clave_unica.code_challenge_for(session["code_verifier"])
    assert f"code_challenge={expected}" in body["authorization_url"]
    # El nonce tampoco: se compara contra el id_token en el servidor.
    assert session["nonce"] in body["authorization_url"]  # va en la URL por spec
    assert "response_type=code" in body["authorization_url"]


# === Camino feliz ===

async def test_a_valid_login_yields_a_single_use_grant(client, configured):
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"]))

    response = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo-del-estado", "state": body["state"],
    })
    data = response.json()

    assert response.status_code == 200, data
    assert data["assurance_level"] == "CLAVE_UNICA"
    assert data["name"] == "Ana Pérez"

    # El grant es canjeable exactamente una vez.
    expected_subject = clave_unica.subject_key_for(f"{RUN_NUMBER}-{RUN_DV}")
    assert await identity_grant.consume(data["identity_grant"]) == expected_subject
    with pytest.raises(identity_grant.IdentityGrantError):
        await identity_grant.consume(data["identity_grant"])


async def test_the_run_is_never_persisted(client, configured):
    """Del ciudadano solo queda un índice ciego, nunca su RUN."""
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"]))

    await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })

    grant_doc = await get_collection("identity_grants").find_one({})
    dumped = json.dumps(grant_doc, default=str)
    assert str(RUN_NUMBER) not in dumped
    assert f"{RUN_NUMBER}-{RUN_DV}" not in dumped
    assert grant_doc["subject_key"] == clave_unica.subject_key_for(
        f"{RUN_NUMBER}-{RUN_DV}"
    )


async def test_the_run_can_come_from_userinfo(client, configured):
    """Según el scope concedido, el RUN puede no venir en el id_token."""
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    token = _id_token(session["nonce"], RolUnico=None)
    _stub_token_endpoint(configured, token)
    configured.setattr(
        clave_unica,
        "_fetch_userinfo",
        lambda access_token: {
            "sub": "sujeto-estatal-1",
            "RolUnico": {"numero": RUN_NUMBER, "DV": RUN_DV},
        },
    )

    response = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })

    assert response.status_code == 200, response.json()


# === Ataques contra la validación del id_token ===

def _forge_hs256_with_public_key(claims: dict) -> str:
    """Token HS256 firmado con la clave PÚBLICA como secreto.

    Se construye a mano porque PyJWT se niega a firmarlo: detecta que le pasan
    material asimétrico. Un atacante no usa PyJWT, así que el test tampoco.
    """
    import hmac as _hmac

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps(claims).encode())
    signing_input = header + b"." + payload
    signature = b64(
        _hmac.new(_PUBLIC_PEM.encode(), signing_input, hashlib.sha256).digest()
    )
    return (signing_input + b"." + signature).decode()


async def test_algorithm_confusion_is_rejected(client, configured):
    """El clásico: firmar con HMAC usando la clave PÚBLICA, que es pública.

    Si el algoritmo se leyera de la cabecera del token, esto pasaría.
    """
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    now = int(time.time())
    forged = _forge_hs256_with_public_key({
        "iss": ISSUER, "aud": CLIENT_ID, "sub": "atacante",
        "exp": now + 300, "iat": now, "nonce": session["nonce"],
        "RolUnico": {"numero": RUN_NUMBER, "DV": RUN_DV},
    })
    _stub_token_endpoint(configured, forged)

    response = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })

    assert response.status_code == 401


async def test_an_unsigned_token_is_rejected(client, configured):
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"], alg="none"))

    response = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })

    assert response.status_code == 401


@pytest.mark.parametrize("claim,value", [
    ("iss", "https://otro-emisor.example/openid"),
    ("aud", "otro-cliente"),
    ("exp", int(time.time()) - 3600),
])
async def test_tokens_from_elsewhere_or_expired_are_rejected(
    client, configured, claim, value
):
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"], **{claim: value}))

    response = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })

    assert response.status_code == 401


async def test_a_token_from_another_login_is_rejected(client, configured):
    """El nonce ata el token al intento que lo pidió."""
    body = await _authorize(client)
    _stub_token_endpoint(configured, _id_token("nonce-de-otra-sesion"))

    response = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })

    assert response.status_code == 401
    assert "nonce" in response.json()["detail"]


async def test_a_token_issued_for_another_client_is_rejected(client, configured):
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"], azp="otro-cliente"))

    response = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })

    assert response.status_code == 401


# === Ataques contra el flujo ===

async def test_the_state_is_single_use(client, configured):
    """Reusar el state (o el código) no puede producir un segundo grant."""
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"]))
    first = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })
    assert first.status_code == 200

    replay = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })

    assert replay.status_code == 401
    assert "ya se usó" in replay.json()["detail"]


async def test_an_unknown_state_is_rejected(client, configured):
    response = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": "state-que-nadie-emitio",
    })

    assert response.status_code == 401


async def test_an_expired_login_attempt_is_rejected(client, configured):
    body = await _authorize(client)
    await get_collection("oidc_login_sessions").update_one(
        {"state": body["state"]},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )

    response = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })

    assert response.status_code == 401


# === RUN ===

def test_a_run_with_a_wrong_check_digit_is_rejected():
    """Un RUN cuyo DV no cuadra no es un RUN, lo firme quien lo firme."""
    with pytest.raises(clave_unica.ClaveUnicaError):
        clave_unica.extract_run({"RolUnico": {"numero": RUN_NUMBER, "DV": "0"}})


def test_a_flat_run_string_is_accepted():
    assert clave_unica.extract_run({"run": f"{RUN_NUMBER}-{RUN_DV}"}) == (
        f"{RUN_NUMBER}-{RUN_DV}"
    )


def test_a_response_without_run_fails_instead_of_inventing_one():
    with pytest.raises(clave_unica.ClaveUnicaError):
        clave_unica.extract_run({"sub": "solo-un-sujeto"})


async def test_a_userinfo_for_another_subject_is_rejected(client, configured):
    """Mezclar dos sujetos acreditaría a la persona equivocada."""
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"], RolUnico=None))
    configured.setattr(
        clave_unica,
        "_fetch_userinfo",
        lambda access_token: {
            "sub": "OTRO-sujeto",
            "RolUnico": {"numero": RUN_NUMBER, "DV": RUN_DV},
        },
    )

    response = await client.post("/api/auth/clave-unica/callback", json={
        "code": "codigo", "state": body["state"],
    })

    assert response.status_code == 401
    assert "no coincide" in response.json()["detail"]


def test_subject_key_is_a_blind_index():
    run = f"{RUN_NUMBER}-{RUN_DV}"
    key = clave_unica.subject_key_for(run)

    assert run not in key
    assert str(RUN_NUMBER) not in key
    assert key == clave_unica.subject_key_for(run)  # determinístico
    assert key != clave_unica.subject_key_for("11111111-1")


# === El bloqueo de los demos sigue en pie ===

async def test_the_demo_identity_flows_stay_blocked_in_production(client, monkeypatch):
    """Implementar ClaveÚnica no vuelve reales el NFC demo ni el liveness."""
    monkeypatch.setattr(settings, "APP_ENV", "production")

    nfc = await client.post("/api/auth/nfc", json={"chip_serial": "TAG"})

    assert nfc.status_code == 503


def test_health_reports_clave_unica_configuration(monkeypatch):
    from app.core import readiness

    monkeypatch.setattr(settings, "CLAVE_UNICA_CLIENT_ID", "")
    features = readiness.feature_status()

    assert features["clave_unica"]["available"] is False
    assert "CLAVE_UNICA_CLIENT_ID" in features["clave_unica"]["missing"]


def test_the_challenge_is_always_32_bytes():
    """S256 produce SHA-256, así que el reto siempre son 32 bytes."""
    challenge = clave_unica.code_challenge_for("a" * 43)

    assert len(base64.urlsafe_b64decode(challenge + "==")) == 32


def test_the_challenge_is_the_sha256_of_the_verifier():
    verifier = "verificador-de-prueba"
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")

    assert clave_unica.code_challenge_for(verifier) == expected
