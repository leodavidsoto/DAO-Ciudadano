"""
Sesión web en cookie HttpOnly + CSRF de doble envío (tarea 1.13).

Lo que estos tests fijan como contrato para el frontend:

* `/wallet/verify` fija `dao_session` (HttpOnly) y `dao_csrf` (legible).
* Con la cookie basta para autenticar; los métodos con efectos exigen además
  la cabecera `X-CSRF-Token`.
* `Authorization: Bearer` sigue funcionando sin CSRF (app móvil).
* `/wallet/logout` borra ambas cookies.
"""
from eth_account import Account
from eth_account.messages import encode_defunct

from app.core import session
from app.core.config import settings

ACCOUNT = Account.from_key("0x" + "7a" * 32)
ADDRESS = ACCOUNT.address.lower()

PROPOSAL = {
    "title": "Propuesta con sesión en cookie",
    "description": "Una descripción suficientemente larga para validar.",
    "creator_address": ADDRESS,
    "duration_days": 7,
}


async def _verify(client, **extra):
    challenge = await client.post(
        "/api/wallet/challenge", json={"address": ACCOUNT.address}
    )
    body = challenge.json()
    signed = Account.sign_message(
        encode_defunct(text=body["message"]), private_key=ACCOUNT.key
    )
    return await client.post("/api/wallet/verify", json={
        "address": ACCOUNT.address,
        "nonce": body["nonce"],
        "signature": signed.signature.hex(),
        **extra,
    })


async def _become_member(client):
    """Mintea con la sesión ya establecida en el cliente (cookie + CSRF)."""
    response = await _verify(client)
    csrf = response.json()["csrf_token"]
    mint = await client.post("/api/membership/mint", json={
        "wallet_address": ADDRESS,
        "assurance_level": "AL2",
        "doc_hash": "0xdoc-cookie-session",
    }, headers={session.CSRF_HEADER: csrf})
    assert mint.json()["ok"] is True, mint.json()
    return csrf


def _set_cookie_header(response, name):
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{name}="):
            return header
    return None


async def test_verify_sets_httponly_session_and_readable_csrf_cookie(client):
    response = await _verify(client)

    session_cookie = _set_cookie_header(response, settings.SESSION_COOKIE_NAME)
    csrf_cookie = _set_cookie_header(response, settings.CSRF_COOKIE_NAME)

    assert "HttpOnly" in session_cookie
    assert "Path=/" in session_cookie
    assert "samesite=lax" in session_cookie.lower()
    # La mitad legible del doble envío: si fuera HttpOnly el cliente no podría
    # repetirla en la cabecera y ninguna petición con efectos funcionaría.
    assert "HttpOnly" not in csrf_cookie
    assert response.json()["csrf_token"] in csrf_cookie


async def test_cookie_session_authenticates_with_csrf_header(client):
    csrf = await _become_member(client)

    response = await client.post(
        "/api/governance/proposals",
        json=PROPOSAL,
        headers={session.CSRF_HEADER: csrf},
    )

    assert response.status_code == 200


async def test_cookie_session_without_csrf_header_is_rejected(client):
    await _become_member(client)

    response = await client.post("/api/governance/proposals", json=PROPOSAL)

    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


async def test_cookie_session_with_wrong_csrf_header_is_rejected(client):
    await _become_member(client)

    response = await client.post(
        "/api/governance/proposals",
        json=PROPOSAL,
        headers={session.CSRF_HEADER: "0" * 64},
    )

    assert response.status_code == 403


async def test_csrf_token_of_another_session_does_not_work(client):
    """El token CSRF está ligado a SU sesión, no es un valor global."""
    await _become_member(client)
    other_csrf = session.csrf_token_for("un.jwt.de.otra.sesion")

    response = await client.post(
        "/api/governance/proposals",
        json=PROPOSAL,
        headers={session.CSRF_HEADER: other_csrf},
    )

    assert response.status_code == 403


async def test_safe_methods_do_not_require_csrf(client):
    await _verify(client)

    response = await client.get("/api/wallet/session")

    assert response.status_code == 200
    assert response.json()["address"] == ADDRESS


async def test_bearer_header_still_works_without_csrf(client):
    """La app móvil no tiene cookies: su flujo no puede depender del CSRF."""
    response = await _verify(client)
    token = response.json()["token"]
    client.cookies.clear()

    mint = await client.post("/api/membership/mint", json={
        "wallet_address": ADDRESS,
        "assurance_level": "AL2",
        "doc_hash": "0xdoc-bearer",
    }, headers={"Authorization": f"Bearer {token}"})

    assert mint.json()["ok"] is True


async def test_cookie_transport_keeps_the_token_out_of_the_body(client):
    response = await _verify(client, session_transport="cookie")
    body = response.json()

    assert body["token"] is None
    # /verify responde en checksum (comportamiento previo); /session en
    # minúsculas, como el resto de la API.
    assert body["address"].lower() == ADDRESS
    assert body["csrf_token"]
    # La sesión sí existe: solo no viaja por un canal que un XSS pueda leer.
    assert client.cookies.get(settings.SESSION_COOKIE_NAME)
    assert (await client.get("/api/wallet/session")).status_code == 200


async def test_logout_clears_the_session(client):
    await _verify(client)
    assert (await client.get("/api/wallet/session")).status_code == 200

    logout = await client.post("/api/wallet/logout")

    assert logout.status_code == 200
    assert not client.cookies.get(settings.SESSION_COOKIE_NAME)
    assert (await client.get("/api/wallet/session")).status_code == 401


async def test_no_session_is_401(client):
    response = await client.get("/api/wallet/session")

    assert response.status_code == 401


async def test_production_cookies_are_secure_and_cross_site(client, monkeypatch):
    """Netlify y Render son sitios distintos: sin SameSite=None no hay sesión."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SIWE_DOMAIN", "estamosdao.cl")
    monkeypatch.setattr(settings, "SIWE_URI", "https://estamosdao.cl")
    monkeypatch.setattr(settings, "SECRET_KEY", "x" * 40)

    response = await _verify(client)

    session_cookie = _set_cookie_header(response, settings.SESSION_COOKIE_NAME)
    assert "Secure" in session_cookie
    assert "samesite=none" in session_cookie.lower()
    assert "HttpOnly" in session_cookie


async def test_samesite_none_without_secure_is_a_deployment_blocker(monkeypatch):
    from app.core import readiness

    monkeypatch.setattr(settings, "SESSION_COOKIE_SAMESITE", "none")
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", "false")

    blockers = readiness.deployment_blockers()

    assert any("SESSION_COOKIE_SAMESITE" in blocker for blocker in blockers)
