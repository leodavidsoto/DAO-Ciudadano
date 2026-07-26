"""
Auth endpoints: RUT validation, registration, login, ClaveÚnica and NFC demos.
"""

VALID_RUT = "11111111-1"  # Passes módulo-11 check digit validation


async def _register(client, rut=VALID_RUT, email="ana@example.com",
                    nombre="Ana", apellido="Rojas"):
    return await client.post("/api/auth/register", json={
        "rut": rut, "email": email, "nombre": nombre, "apellido": apellido,
    })


async def test_register_valid_user(client):
    response = await _register(client)
    data = response.json()
    assert data["ok"] is True
    assert data["rut"] == "11.111.111-1"
    assert data["email"] == "ana@example.com"
    assert data["assurance_level"] == "AL1"


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
    await _register(client)
    response = await client.post("/api/auth/login", json={
        "rut": VALID_RUT, "email": "ana@example.com",
    })
    data = response.json()
    assert data["ok"] is True
    assert data["rut"] == "11.111.111-1"


async def test_login_unknown_user_fails(client):
    response = await client.post("/api/auth/login", json={
        "rut": VALID_RUT, "email": "nadie@example.com",
    })
    assert response.json()["ok"] is False


async def test_clave_unica_returns_subject(client):
    response = await client.post("/api/auth/clave-unica", json={"rut": "11111111-1"})
    data = response.json()
    assert data["ok"] is True
    assert data["subject_id"] == "claveunica:11111111-1"
    assert data["assurance_level"] == "AL2"


async def test_clave_unica_rejects_short_rut(client):
    response = await client.post("/api/auth/clave-unica", json={"rut": "123"})
    assert response.json()["ok"] is False


async def test_nfc_generates_demo_serial_without_body(client):
    response = await client.post("/api/auth/nfc")
    data = response.json()
    assert data["ok"] is True
    assert data["chip_serial"].startswith("NFC-CL-CH-")
    assert data["doc_hash"].startswith("0x")


async def test_nfc_uses_client_chip_serial_when_provided(client):
    response = await client.post("/api/auth/nfc", json={"chip_serial": "REAL-SERIAL-01"})
    data = response.json()
    assert data["ok"] is True
    assert data["chip_serial"] == "REAL-SERIAL-01"


async def test_liveness_rejects_non_image(client):
    response = await client.post(
        "/api/auth/liveness",
        files={"file": ("nota.txt", b"hola", "text/plain")},
    )
    data = response.json()
    assert data["ok"] is False
    assert "imagen" in data["error"]
