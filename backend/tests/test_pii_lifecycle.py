"""
Ciclo de vida de la PII: rotación de llaves, rotación de pepper, índice de
identidad y retención (ROADMAP 1.3, 1.4 y 1.11).

Lo que se comprueba aquí es lo que hace que una filtración sea recuperable:

* publicar una llave nueva NO deja ilegible lo ya cifrado,
* rotar el pepper NO deja fuera a los usuarios ya registrados,
* dos membresías de la MISMA persona no pueden coexistir,
* y la política de retención no borra por accidente lo que protege contra
  repetición.
"""

import pytest
from cryptography.fernet import Fernet
from pymongo.errors import DuplicateKeyError

from app.core import crypto, retention
from app.core.config import settings
from app.core.database import members_collection, users_collection
from app.core.identity import lookup_key, lookup_key_candidates

KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()


@pytest.fixture
def keys(monkeypatch):
    """Deja una sola llave (A) configurada y devuelve un ayudante para rotar."""
    monkeypatch.setattr(settings, "PII_ENCRYPTION_KEY", "")
    monkeypatch.setattr(settings, "PII_ENCRYPTION_KEYS", KEY_A)

    def set_keys(*values):
        monkeypatch.setattr(settings, "PII_ENCRYPTION_KEYS", ",".join(values))

    return set_keys


# === 1.3 — rotación de la llave de cifrado ===


def test_a_new_key_does_not_orphan_existing_data(keys):
    """El fallo que hace irrecuperable una filtración: reemplazar la llave."""
    ciphertext = crypto.encrypt("12.345.678-9")

    # Se publica la nueva DELANTE de la vieja, que es el procedimiento.
    keys(KEY_B, KEY_A)

    assert crypto.decrypt(ciphertext) == "12.345.678-9"
    # Lo nuevo ya se cifra con la primaria.
    assert crypto.is_current(crypto.encrypt("otro")) is True
    # Y lo viejo se detecta como pendiente de rotar.
    assert crypto.is_current(ciphertext) is False


def test_rotate_rewrites_without_exposing_plaintext(keys):
    ciphertext = crypto.encrypt("ana@example.com")
    keys(KEY_B, KEY_A)

    rotated = crypto.rotate(ciphertext)

    assert rotated != ciphertext
    assert crypto.is_current(rotated) is True
    assert crypto.decrypt(rotated) == "ana@example.com"


def test_removing_the_old_key_too_early_is_detectable(keys):
    """Retirar la llave vieja antes de terminar la rotación deja datos
    ilegibles: el error tiene que ser explícito, no un valor vacío."""
    ciphertext = crypto.encrypt("dato antiguo")
    keys(KEY_B)  # se retiró KEY_A sin haber rotado

    with pytest.raises(ValueError):
        crypto.decrypt(ciphertext)
    with pytest.raises(ValueError):
        crypto.rotate(ciphertext)


def test_key_status_reports_rotation_without_leaking_keys(keys):
    keys(KEY_B, KEY_A)

    status = crypto.key_status()

    assert status["usable"] == 2
    assert status["rotation_in_progress"] is True
    # Huellas, no llaves: este objeto se publica en /health/ready.
    assert status["primary"] == crypto.fingerprint(KEY_B)
    assert KEY_A not in str(status)
    assert KEY_B not in str(status)


def test_invalid_keys_are_reported_not_silently_ignored(keys):
    keys(KEY_B, "esto-no-es-una-llave-fernet")

    status = crypto.key_status()

    assert status["usable"] == 1
    assert status["invalid"] == 1


def test_legacy_single_key_setting_still_works(monkeypatch):
    """Un despliegue existente no tiene que renombrar nada para seguir vivo."""
    monkeypatch.setattr(settings, "PII_ENCRYPTION_KEYS", "")
    monkeypatch.setattr(settings, "PII_ENCRYPTION_KEY", KEY_A)

    assert crypto.decrypt(crypto.encrypt("rut")) == "rut"
    assert crypto.key_status()["usable"] == 1


# === 1.3 — rotación del pepper ===


def test_rotating_the_pepper_keeps_existing_records_findable(monkeypatch):
    monkeypatch.setattr(
        settings, "IDENTITY_PEPPER", "pepper-viejo-de-32-caracteres-xxxx"
    )
    monkeypatch.setattr(settings, "IDENTITY_PEPPER_PREVIOUS", "")
    stored = lookup_key("12.345.678-9", domain="rut")

    # Rotación: nuevo vigente, viejo declarado como anterior.
    monkeypatch.setattr(
        settings, "IDENTITY_PEPPER", "pepper-nuevo-de-32-caracteres-yyyy"
    )
    monkeypatch.setattr(
        settings, "IDENTITY_PEPPER_PREVIOUS", "pepper-viejo-de-32-caracteres-xxxx"
    )

    candidates = lookup_key_candidates("12.345.678-9", domain="rut")

    # La clave guardada sigue siendo alcanzable...
    assert stored in candidates
    # ...pero lo que se escriba ahora usa el pepper nuevo.
    assert lookup_key("12.345.678-9", domain="rut") != stored
    assert candidates[0] == lookup_key("12.345.678-9", domain="rut")


def test_without_rotation_the_lookup_is_a_single_key(monkeypatch):
    monkeypatch.setattr(
        settings, "IDENTITY_PEPPER", "pepper-unico-de-32-caracteres-zzz"
    )
    monkeypatch.setattr(settings, "IDENTITY_PEPPER_PREVIOUS", "")

    assert len(lookup_key_candidates("12.345.678-9", domain="rut")) == 1


async def test_login_works_during_a_pepper_rotation(client, monkeypatch):
    """Extremo a extremo: registrarse con un pepper y entrar con el siguiente."""
    old_pepper = "pepper-viejo-de-32-caracteres-xxxx"
    new_pepper = "pepper-nuevo-de-32-caracteres-yyyy"
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", old_pepper)
    monkeypatch.setattr(settings, "IDENTITY_PEPPER_PREVIOUS", "")

    registration = await client.post(
        "/api/auth/register",
        json={
            "rut": "12.345.678-5",
            "email": "rotacion@example.com",
            "nombre": "Ana",
            "apellido": "Pérez",
        },
    )
    assert registration.json()["ok"] is True, registration.json()

    # El pepper rota mientras el usuario ya existe indexado con el viejo.
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", new_pepper)
    monkeypatch.setattr(settings, "IDENTITY_PEPPER_PREVIOUS", old_pepper)

    login = await client.post(
        "/api/auth/login",
        json={
            "rut": "12.345.678-5",
            "email": "rotacion@example.com",
        },
    )

    assert login.json()["ok"] is True, login.json()


async def test_registration_during_rotation_does_not_duplicate(client, monkeypatch):
    """Sin mirar el pepper anterior, un registro existente parecería nuevo."""
    old_pepper = "pepper-viejo-de-32-caracteres-xxxx"
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", old_pepper)
    monkeypatch.setattr(settings, "IDENTITY_PEPPER_PREVIOUS", "")
    payload = {
        "rut": "12.345.678-5",
        "email": "duplicado@example.com",
        "nombre": "Ana",
        "apellido": "Pérez",
    }
    assert (await client.post("/api/auth/register", json=payload)).json()["ok"] is True

    monkeypatch.setattr(
        settings, "IDENTITY_PEPPER", "pepper-nuevo-de-32-caracteres-yyyy"
    )
    monkeypatch.setattr(settings, "IDENTITY_PEPPER_PREVIOUS", old_pepper)

    repeat = await client.post("/api/auth/register", json=payload)

    assert repeat.json()["ok"] is False
    assert "ya está registrado" in repeat.json()["error"]


# === 1.11 — unicidad por persona ===


async def test_two_memberships_for_the_same_person_are_impossible(client):
    """El nullifier identifica a la persona: no puede repetirse."""
    await members_collection().insert_one(
        {
            "wallet_address": "0x" + "a1" * 20,
            "token_id": 501,
            "nullifier_hash": "0x" + "ff" * 32,
            "status": "active",
        }
    )

    with pytest.raises(DuplicateKeyError):
        # Otra wallet, misma persona: es justo lo que el índice de
        # wallet_address NO podía impedir.
        await members_collection().insert_one(
            {
                "wallet_address": "0x" + "b2" * 20,
                "token_id": 502,
                "nullifier_hash": "0x" + "ff" * 32,
                "status": "active",
            }
        )


async def test_demo_rows_without_nullifier_do_not_collide(client):
    """El índice es parcial: varias filas legacy con None deben convivir."""
    await members_collection().insert_one(
        {
            "wallet_address": "0x" + "c3" * 20,
            "token_id": 601,
            "nullifier_hash": None,
        }
    )
    await members_collection().insert_one(
        {
            "wallet_address": "0x" + "d4" * 20,
            "token_id": 602,
            "nullifier_hash": None,
        }
    )

    assert await members_collection().count_documents({"nullifier_hash": None}) == 2


# === 1.4 — política de retención ===


def test_replay_protection_is_never_purged_by_age():
    keep_forever = {
        rule.collection for rule in retention.rules() if rule.ttl_seconds is None
    }

    # Borrar estos por antigüedad reabriría la ventana de repetición que cierran.
    assert "ballot_nonces" in keep_forever
    assert "mint_operations" in keep_forever


def test_citizen_records_are_not_deleted_automatically(monkeypatch):
    monkeypatch.setattr(settings, "INACTIVE_USER_RETENTION_DAYS", 0)

    users_rule = next(r for r in retention.rules() if r.collection == "users")

    assert users_rule.ttl_seconds is None
    assert users_rule.automatic is False
    assert not any(r.collection == "users" for r in retention.automatic_rules())


def test_enabling_user_retention_still_requires_the_script(monkeypatch):
    """Aun activada, la purga de registros civiles no la hace un TTL."""
    monkeypatch.setattr(settings, "INACTIVE_USER_RETENTION_DAYS", 365)

    users_rule = next(r for r in retention.rules() if r.collection == "users")

    assert users_rule.ttl_seconds == 365 * retention.SECONDS_PER_DAY
    assert users_rule.automatic is False
    assert any(r.collection == "users" for r in retention.manual_rules())
    assert not any(r.collection == "users" for r in retention.automatic_rules())


def test_short_lived_secrets_expire_automatically():
    automatic = {r.collection: r.ttl_seconds for r in retention.automatic_rules()}

    assert automatic["siwe_nonces"] == 600
    assert automatic["identity_grants"] == 30 * retention.SECONDS_PER_DAY


async def test_health_reports_key_custody_honestly(client):
    response = await client.get("/health/ready")
    pii = response.json()["configuration"]["features"]["pii_protection"]

    # No se afirma tener un KMS: las llaves están en el entorno.
    assert pii["key_custody"] == "environment"
    assert pii["retention_policy"]
    assert "primary_key" in pii


# === La herramienta de migración (services/pii_maintenance.py) ===


async def _seed_user(rut="12.345.678-9", email="ana@example.com", **overrides):
    doc = {
        "id": f"user-{rut}",
        "rut": crypto.encrypt(rut),
        "rut_key": lookup_key(rut, "rut"),
        "email": crypto.encrypt(email),
        "email_key": lookup_key(email, "email"),
        "nombre": crypto.encrypt("Ana"),
        "apellido": crypto.encrypt("Pérez"),
        "status": "active",
    }
    doc.update(overrides)
    await users_collection().insert_one(doc)
    return doc


async def test_dry_run_does_not_write(client, keys):
    from app.services import pii_maintenance as service

    await _seed_user()
    keys(KEY_B, KEY_A)
    before = await users_collection().find_one({"id": "user-12.345.678-9"})

    report = await service.rotate_encrypted_fields("users", apply=False)
    after = await users_collection().find_one({"id": "user-12.345.678-9"})

    assert report.changed == 1  # sabe lo que haría...
    assert after["rut"] == before["rut"]  # ...pero no lo hizo


async def test_rotation_rewrites_every_encrypted_field(client, keys):
    from app.services import pii_maintenance as service

    await _seed_user()
    keys(KEY_B, KEY_A)

    await service.rotate_encrypted_fields("users", apply=True)

    doc = await users_collection().find_one({"id": "user-12.345.678-9"})
    for field_name in service.ENCRYPTED_FIELDS["users"]:
        assert crypto.is_current(doc[field_name]), f"{field_name} quedó sin rotar"
    # El contenido no cambió: rotar no es reescribir datos.
    assert crypto.decrypt(doc["rut"]) == "12.345.678-9"
    assert crypto.decrypt(doc["nombre"]) == "Ana"
    assert (await service.scan("users"))["stale_cipher"] == 0


async def test_legacy_plaintext_pii_gets_encrypted(client, keys):
    """Migración 1.4: filas antiguas guardadas en claro."""
    from app.services import pii_maintenance as service

    await _seed_user(
        rut="11.111.111-1",
        email="legacy@example.com",
        nombre="EnClaro",
        apellido="SinCifrar",
    )
    assert (await service.scan("users"))["plaintext"] == 1

    await service.rotate_encrypted_fields("users", apply=True)

    doc = await users_collection().find_one({"id": "user-11.111.111-1"})
    assert service.looks_encrypted(doc["nombre"])
    assert crypto.decrypt(doc["nombre"]) == "EnClaro"
    assert (await service.scan("users"))["plaintext"] == 0


async def test_undecryptable_rows_are_reported_not_silently_skipped(client, keys):
    """Si falta la llave que cifró un dato, hay que enterarse ANTES de retirar
    ninguna otra: un fallo silencioso aquí pierde datos para siempre."""
    from app.services import pii_maintenance as service

    await _seed_user()
    keys(KEY_B)  # se retiró KEY_A sin haber rotado

    report = await service.rotate_encrypted_fields("users", apply=True)

    assert report.ok is False
    assert any("no lo descifra" in f for f in report.failures)
    assert (await service.scan("users"))["undecryptable"] == 1


async def test_reindex_closes_a_pepper_rotation(client, monkeypatch):
    from app.services import pii_maintenance as service

    old_pepper = "pepper-viejo-de-32-caracteres-xxxx"
    new_pepper = "pepper-nuevo-de-32-caracteres-yyyy"
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", old_pepper)
    monkeypatch.setattr(settings, "IDENTITY_PEPPER_PREVIOUS", "")
    await _seed_user()

    monkeypatch.setattr(settings, "IDENTITY_PEPPER", new_pepper)
    monkeypatch.setattr(settings, "IDENTITY_PEPPER_PREVIOUS", old_pepper)
    assert (await service.scan("users"))["stale_lookup"] == 1

    await service.reindex_lookup_keys("users", apply=True)

    doc = await users_collection().find_one({"id": "user-12.345.678-9"})
    assert doc["rut_key"] == lookup_key("12.345.678-9", "rut")
    assert doc["email_key"] == lookup_key("ana@example.com", "email")
    assert (await service.scan("users"))["stale_lookup"] == 0

    # Terminada la migración, el pepper anterior ya se puede retirar sin que
    # nadie quede fuera.
    monkeypatch.setattr(settings, "IDENTITY_PEPPER_PREVIOUS", "")
    assert doc["rut_key"] in lookup_key_candidates("12.345.678-9", "rut")


async def test_purge_is_a_no_op_while_user_retention_is_disabled(client, monkeypatch):
    from app.services import pii_maintenance as service

    monkeypatch.setattr(settings, "INACTIVE_USER_RETENTION_DAYS", 0)
    await _seed_user()

    assert await service.purge(apply=True) == {}
    assert await users_collection().count_documents({}) == 1
