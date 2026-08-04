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
_PUBLIC_PEM = (
    _KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)


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

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo-del-estado",
            "state": body["state"],
        },
    )
    data = response.json()

    assert response.status_code == 200, data
    assert data["assurance_level"] == "CLAVE_UNICA"
    assert data["name"] == "Ana Pérez"

    # El grant es canjeable exactamente una vez, y solo con el binding.
    expected_subject = clave_unica.subject_key_for(f"{RUN_NUMBER}-{RUN_DV}")
    binding = clave_unica.hash_browser_binding(
        client.cookies[settings.CLAVE_UNICA_BINDING_COOKIE_NAME]
    )
    assert (
        await identity_grant.consume(data["identity_grant"], browser_binding=binding)
        == expected_subject
    )
    with pytest.raises(identity_grant.IdentityGrantError):
        await identity_grant.consume(data["identity_grant"], browser_binding=binding)


async def test_the_run_is_never_persisted(client, configured):
    """Del ciudadano solo queda un índice ciego, nunca su RUN."""
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"]))

    await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

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

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

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
    forged = _forge_hs256_with_public_key(
        {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "atacante",
            "exp": now + 300,
            "iat": now,
            "nonce": session["nonce"],
            "RolUnico": {"numero": RUN_NUMBER, "DV": RUN_DV},
        }
    )
    _stub_token_endpoint(configured, forged)

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert response.status_code == 401


async def test_an_unsigned_token_is_rejected(client, configured):
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"], alg="none"))

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "claim,value",
    [
        ("iss", "https://otro-emisor.example/openid"),
        ("aud", "otro-cliente"),
        ("exp", int(time.time()) - 3600),
    ],
)
async def test_tokens_from_elsewhere_or_expired_are_rejected(
    client, configured, claim, value
):
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"], **{claim: value}))

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert response.status_code == 401


async def test_a_token_from_another_login_is_rejected(client, configured):
    """El nonce ata el token al intento que lo pidió."""
    body = await _authorize(client)
    _stub_token_endpoint(configured, _id_token("nonce-de-otra-sesion"))

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert response.status_code == 401
    assert "nonce" in response.json()["detail"]


async def test_a_token_issued_for_another_client_is_rejected(client, configured):
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"], azp="otro-cliente"))

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert response.status_code == 401


# === Ataques contra el flujo ===


async def test_repeating_the_callback_returns_the_same_grant(client, configured):
    """Requisito 3: una respuesta HTTP perdida no puede dejar sin credencial.

    Repetir desde el MISMO navegador devuelve el mismo grant vigente — ni uno
    nuevo (duplicaría identidades) ni un 401 (dejaría a la persona fuera).
    """
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"]))
    first = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )
    assert first.status_code == 200

    replay = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert replay.status_code == 200
    assert replay.json()["identity_grant"] == first.json()["identity_grant"]
    # Y solo hay UN grant emitido, no dos.
    assert await get_collection("identity_grants").count_documents({}) == 1


async def test_a_consumed_grant_is_not_replayed(client, configured):
    """Si el grant ya se canjeó, repetir el callback no lo resucita."""
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"]))
    first = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )
    binding = clave_unica.hash_browser_binding(
        client.cookies[settings.CLAVE_UNICA_BINDING_COOKIE_NAME]
    )
    await identity_grant.consume(
        first.json()["identity_grant"], browser_binding=binding
    )

    replay = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert replay.status_code == 401
    assert "ya se emitió" in replay.json()["detail"]


async def test_an_unknown_state_is_rejected(client, configured):
    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": "state-que-nadie-emitio",
        },
    )

    assert response.status_code == 401


async def test_an_expired_login_attempt_is_rejected(client, configured):
    body = await _authorize(client)
    await get_collection("oidc_login_sessions").update_one(
        {"state": body["state"]},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

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

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

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
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )

    assert clave_unica.code_challenge_for(verifier) == expected


# === Binding de navegador (TAREA 6) ===


def _second_browser(client):
    """Otro cliente HTTP: mismas rutas, cookie jar distinto."""
    import httpx

    return httpx.AsyncClient(transport=client._transport, base_url="http://testserver")


async def test_authorize_sets_an_httponly_binding_cookie(client, configured):
    response = await client.post("/api/auth/clave-unica/authorize")

    raw = [
        h
        for h in response.headers.get_list("set-cookie")
        if h.startswith(settings.CLAVE_UNICA_BINDING_COOKIE_NAME + "=")
    ]
    assert raw, "no se fijó la cookie de binding"
    cookie = raw[0]
    assert "HttpOnly" in cookie  # un XSS no puede leerla ni reenviarla
    assert "Path=/api" in cookie  # también se exige en /identity-credential
    # El valor no viaja en el cuerpo: si estuviera, JavaScript lo leería.
    assert client.cookies[settings.CLAVE_UNICA_BINDING_COOKIE_NAME] not in response.text
    # Y en la base solo queda su hash.
    session = await _stored_session(response.json()["state"])
    assert session["browser_binding"] == clave_unica.hash_browser_binding(
        client.cookies[settings.CLAVE_UNICA_BINDING_COOKIE_NAME]
    )
    assert "code_verifier" in session


async def test_a_second_browser_with_the_same_code_gets_nothing(client, configured):
    """El ataque que bloqueaba la web: capturar code+state y canjearlo aparte."""
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"]))

    async with _second_browser(client) as attacker:
        stolen = await attacker.post(
            "/api/auth/clave-unica/callback",
            json={
                "code": "codigo-robado",
                "state": body["state"],
            },
        )

    assert stolen.status_code == 401
    assert "otro navegador" in stolen.json()["detail"]
    assert await get_collection("identity_grants").count_documents({}) == 0

    # Y el navegador legítimo sigue pudiendo completar su flujo: el intento del
    # atacante no le quemó el state.
    legit = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )
    assert legit.status_code == 200


async def test_a_forged_binding_cookie_is_rejected(client, configured):
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"]))
    client.cookies.set(settings.CLAVE_UNICA_BINDING_COOKIE_NAME, "binding-inventado")

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert response.status_code == 401


async def test_the_binding_is_checked_before_talking_to_the_provider(
    client, configured
):
    """Sin cookie no se gasta el código de autorización de nadie."""
    body = await _authorize(client)
    calls = []
    configured.setattr(
        clave_unica,
        "_exchange_code",
        lambda code, verifier: calls.append(code) or {"id_token": "x"},
    )
    client.cookies.clear()

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert response.status_code == 401
    assert calls == [], "se llamó al proveedor pese a faltar el binding"


async def test_the_grant_cannot_be_redeemed_from_another_browser(client, configured):
    """Requisito 4: copiar el grant (o el bearer) a otro navegador no basta."""
    body = await _authorize(client)
    session = await _stored_session(body["state"])
    _stub_token_endpoint(configured, _id_token(session["nonce"]))
    grant = (
        await client.post(
            "/api/auth/clave-unica/callback",
            json={
                "code": "codigo",
                "state": body["state"],
            },
        )
    ).json()["identity_grant"]

    otro_binding = clave_unica.hash_browser_binding("cookie-de-otro-navegador")
    with pytest.raises(identity_grant.IdentityGrantError):
        await identity_grant.consume(grant, browser_binding=otro_binding)

    # Sin cookie tampoco.
    with pytest.raises(identity_grant.IdentityGrantError):
        await identity_grant.consume(grant)

    # El grant sigue intacto para su dueño: los intentos no lo quemaron.
    mine = clave_unica.hash_browser_binding(
        client.cookies[settings.CLAVE_UNICA_BINDING_COOKIE_NAME]
    )
    assert await identity_grant.consume(grant, browser_binding=mine)


async def test_legacy_grants_without_binding_still_work(client):
    """Exigirlo retroactivamente dejaría sin credencial a quien ya lo tenía."""
    grant = await identity_grant.issue("sujeto-legacy", provider="otro-proveedor")

    assert await identity_grant.consume(grant) == "sujeto-legacy"


# === Telemetría (TAREA 6, punto 3) ===


async def test_status_returns_the_exact_contract(client, configured):
    response = await client.get("/api/auth/clave-unica/status")
    body = response.json()

    assert response.status_code == 200
    assert body == {
        "available": True,
        "protocol_version": "clave-unica-oidc-pkce-v1",
        "pkce_method": "S256",
        "browser_bound": True,
        "credential_exchange_browser_bound": True,
        "callback_idempotent": True,
        "grant_single_use": True,
        "redirect_transport": "frontend-post",
        "grant_ttl_seconds": settings.IDENTITY_GRANT_TTL_SECONDS,
    }


async def test_status_reports_unavailable_without_configuration(client):
    body = (await client.get("/api/auth/clave-unica/status")).json()

    # El resto de garantías siguen siendo ciertas; lo que falta es el proveedor.
    assert body["available"] is False
    assert body["browser_bound"] is True


async def test_status_is_public_and_leaks_nothing(client, configured):
    """La web lo consulta antes de redirigir, sin sesión."""
    client.cookies.clear()

    body = (await client.get("/api/auth/clave-unica/status")).json()

    assert "client_secret" not in str(body).lower()
    assert CLIENT_ID not in str(body)


# === Robustez del proveedor (TAREA 6, punto 7) ===


async def test_a_provider_timeout_is_not_a_successful_login(client, configured):
    body = await _authorize(client)

    def _timeout(code, verifier):
        raise TimeoutError("el proveedor no respondió")

    configured.setattr(clave_unica, "_exchange_code", _timeout)

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert response.status_code >= 400
    assert await get_collection("identity_grants").count_documents({}) == 0


async def test_an_invalid_json_body_from_the_provider_is_rejected(client, configured):
    body = await _authorize(client)
    configured.setattr(
        clave_unica,
        "_exchange_code",
        lambda code, verifier: {"no_hay": "id_token"},
    )

    response = await client.post(
        "/api/auth/clave-unica/callback",
        json={
            "code": "codigo",
            "state": body["state"],
        },
    )

    assert response.status_code >= 400
    assert await get_collection("identity_grants").count_documents({}) == 0


# === Readiness de producción (TAREA 6, punto 5) ===


def test_production_blocks_a_provider_that_is_not_clave_unica(monkeypatch):
    """Un nombre de sandbox olvidado en producción emitiría grants sin verificar."""
    from app.core import readiness

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "IDENTITY_PROVIDER", "clave-unica-sandbox")

    blockers = readiness.deployment_blockers()

    assert any("clave-unica" in b and "no corresponde" in b for b in blockers)


def test_production_blocks_clave_unica_with_incomplete_configuration(monkeypatch):
    from app.core import readiness

    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "IDENTITY_PROVIDER", "clave-unica")
    monkeypatch.setattr(settings, "CLAVE_UNICA_CLIENT_ID", "")

    blockers = readiness.deployment_blockers()

    assert any("configuración" in b and "ClaveÚnica" in b for b in blockers)


@pytest.mark.parametrize(
    "key",
    [
        "CLAVE_UNICA_ISSUER",
        "CLAVE_UNICA_TOKEN_ENDPOINT",
        "CLAVE_UNICA_JWKS_URI",
    ],
)
def test_plain_http_endpoints_are_a_configuration_error(monkeypatch, key):
    """En claro viajarían el código de autorización y el client_secret."""
    monkeypatch.setattr(settings, key, "http://accounts.example.gob.cl/openid")

    assert key in clave_unica.configuration_errors()
