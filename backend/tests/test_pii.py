"""
PII at rest (ROADMAP 1.4, audit finding C-4).

The point is not that encryption runs, but that a database dump reveals
nothing: no RUT, no email, no name in plaintext anywhere in the collection.
"""
import pytest

from app.core.config import settings
from app.core.crypto import EncryptionKeyMissing, decrypt, encrypt
from app.core.database import Database

RUT = "12.345.678-5"
EMAIL = "persona@ejemplo.cl"


async def _register(client, rut=RUT, email=EMAIL):
    return await client.post("/api/auth/register", json={
        "rut": rut, "email": email, "nombre": "Ana", "apellido": "Pérez",
    })


# === El cifrado en sí ===

def test_roundtrip():
    assert decrypt(encrypt(RUT)) == RUT


def test_ciphertext_is_not_the_plaintext():
    assert RUT not in encrypt(RUT)


def test_encryption_is_non_deterministic():
    """Equal values must not produce equal ciphertexts: otherwise a dump
    reveals which users share a value even without the key."""
    assert encrypt(RUT) != encrypt(RUT)


def test_tampered_ciphertext_returns_none():
    """Authenticated encryption: a modified record must not be served."""
    assert decrypt("gAAAAABtampered-value") is None


def test_none_passes_through():
    assert encrypt(None) is None and decrypt(None) is None


def test_fails_closed_without_key_in_production(monkeypatch):
    monkeypatch.setattr(settings, "PII_ENCRYPTION_KEY", "", raising=False)
    monkeypatch.setattr(settings, "DEBUG", False, raising=False)
    with pytest.raises(EncryptionKeyMissing):
        encrypt(RUT)


# === Lo que de verdad importa: qué se ve en un volcado ===

async def test_database_dump_exposes_no_plaintext_pii(client):
    assert (await _register(client)).json()["ok"] is True

    doc = await Database.get_db()["users"].find_one({})
    dump = str(doc)

    for secret in (RUT, "12345678", EMAIL, "Ana", "Pérez"):
        assert secret not in dump, f"'{secret}' aparece en claro en la base"


async def test_registration_still_enforces_uniqueness(client):
    """Encrypted columns cannot be queried, so uniqueness rides on the blind
    index. If that broke, duplicates would slip through silently."""
    assert (await _register(client)).json()["ok"] is True

    same_rut = await _register(client, email="otro@ejemplo.cl")
    assert same_rut.json()["ok"] is False
    assert "RUT" in same_rut.json()["error"]

    same_email = await _register(client, rut="11.111.111-1")
    assert same_email.json()["ok"] is False
    assert "email" in same_email.json()["error"].lower()


async def test_login_works_against_encrypted_records(client):
    await _register(client)
    response = await client.post("/api/auth/login", json={"rut": RUT, "email": EMAIL})
    body = response.json()
    assert body["ok"] is True
    # decrypted for the response, never returned as ciphertext
    assert body["email"] == EMAIL
    assert body["nombre"] == "Ana"


async def test_identity_events_do_not_store_the_rut(client):
    """IdentityEvent used to keep the RUT in clear text as user_id."""
    await _register(client)
    events = [e async for e in Database.get_db()["identity_events"].find({})]
    assert events
    for event in events:
        assert RUT not in str(event)
        assert "12345678" not in str(event)
