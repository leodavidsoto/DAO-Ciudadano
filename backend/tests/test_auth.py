"""
Auth endpoints: RUT validation, registration, login, ClaveÚnica and NFC demos.
"""

import base64

from app.core.config import settings
from app.core.database import Database, users_collection


VALID_RUT = "11111111-1"  # Passes módulo-11 check digit validation
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


async def _identity_event_count():
    """Legacy collection stays empty; demo flows must not create evidence."""
    return await Database.get_db()["identity_events"].count_documents({})


async def _register(
    client, rut=VALID_RUT, email="ana@example.com", nombre="Ana", apellido="Rojas"
):
    return await client.post(
        "/api/auth/register",
        json={
            "rut": rut,
            "email": email,
            "nombre": nombre,
            "apellido": apellido,
        },
    )


async def test_register_valid_demo_user(client, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "demo")
    response = await _register(client)
    data = response.json()
    assert data["ok"] is True
    assert data["rut"] == "11.111.111-1"
    assert data["email"] == "ana@example.com"
    assert data["subject_id"].startswith("demo:user:")
    assert data["assurance_level"] == "DEMO_UNVERIFIED"
    assert await _identity_event_count() == 0


async def test_register_rejects_invalid_rut(client):
    response = await _register(client, rut="12345678-9")  # Wrong check digit
    data = response.json()
    assert data["ok"] is False
    assert "RUT" in data["error"]


async def test_register_rejects_invalid_email(client):
    response = await _register(client, email="not-an-email")
    data = response.json()
    assert data["ok"] is False


async def test_register_rejects_duplicate_rut(client):
    await _register(client)
    duplicate = await _register(client, email="otro@example.com")
    data = duplicate.json()
    assert data["ok"] is False
    assert "registrado" in data["error"]


async def test_login_with_registered_user(client):
    registration = await _register(client)
    response = await client.post(
        "/api/auth/login",
        json={
            "rut": VALID_RUT,
            "email": "ana@example.com",
        },
    )
    data = response.json()
    assert data["ok"] is True
    assert data["rut"] == "11.111.111-1"
    assert data["subject_id"] == registration.json()["subject_id"]
    assert data["assurance_level"] == "DEMO_UNVERIFIED"
    assert await _identity_event_count() == 0


async def test_login_unknown_user_fails(client):
    response = await client.post(
        "/api/auth/login",
        json={
            "rut": VALID_RUT,
            "email": "nadie@example.com",
        },
    )
    assert response.json()["ok"] is False


async def test_the_clave_unica_simulation_is_gone(client, monkeypatch):
    """Aceptaba cualquier RUT con formato válido y devolvía un sujeto demo.

    Ahora existe el flujo OIDC real (ROADMAP 4.1), así que el simulador se
    eliminó: dos puertas donde una finge identidad civil es peor que ninguna.
    Queda un 410 con la ruta correcta porque hay clientes desplegados
    llamando aquí.
    """
    monkeypatch.setattr(settings, "APP_ENV", "demo")

    response = await client.post("/api/auth/clave-unica", json={"rut": "11111111-1"})

    assert response.status_code == 410
    assert "authorize" in response.json()["detail"]
    assert await _identity_event_count() == 0


async def test_nfc_generates_demo_serial_without_body(client):
    response = await client.post("/api/auth/nfc")
    data = response.json()
    assert data["ok"] is True
    assert data["chip_serial"].startswith("DEMO-NFC-RANDOM-")
    assert data["doc_hash"].startswith("0x")
    assert await _identity_event_count() == 0


async def test_nfc_derives_demo_id_from_client_tag_when_provided(client):
    response = await client.post("/api/auth/nfc", json={"chip_serial": "CLIENT-TAG-01"})
    data = response.json()
    assert data["ok"] is True
    assert data["chip_serial"].startswith("DEMO-NFC-CLIENT-")
    assert "CLIENT-TAG-01" not in data["chip_serial"]
    assert await _identity_event_count() == 0


async def test_liveness_success_is_explicitly_demo_and_not_persisted(client):
    response = await client.post(
        "/api/auth/liveness",
        files={"file": ("selfie.png", TINY_PNG, "image/png")},
    )
    data = response.json()
    assert data["ok"] is True
    assert data["analysis"].startswith("DEMO:")
    assert "no verifica presencia en vivo" in data["analysis"]
    assert await _identity_event_count() == 0


async def test_liveness_rejects_non_image(client):
    response = await client.post(
        "/api/auth/liveness",
        files={"file": ("nota.txt", b"hola", "text/plain")},
    )
    data = response.json()
    assert data["ok"] is False
    assert "imagen" in data["error"]


async def test_production_blocks_every_unverified_identity_flow(client, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")

    responses = [
        await client.post("/api/auth/nfc", json={"chip_serial": "CLIENT-TAG-01"}),
        await client.post(
            "/api/auth/liveness",
            files={"file": ("selfie.png", TINY_PNG, "image/png")},
        ),
        await _register(client),
        await client.post(
            "/api/auth/login",
            json={
                "rut": VALID_RUT,
                "email": "ana@example.com",
            },
        ),
    ]

    for response in responses:
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "deshabilitados en producción" in detail
        assert "verificador de identidad real" in detail

    assert await users_collection().count_documents({}) == 0
    assert await _identity_event_count() == 0
