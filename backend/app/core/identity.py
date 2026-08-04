"""
Identity hashing (D-2 del ADR).

Antes: el hash de identidad (RUT -> doc_hash) se calculaba con SHA-256
truncado sobre el valor plano, sin sal ni pepper — reversible por fuerza
bruta contra el universo de RUTs chilenos (8 dígitos, espacio pequeño).

Ahora: HMAC-SHA256 con un pepper de servidor (IDENTITY_PEPPER, nunca en el
repo) como llave. Sin el pepper no se puede recalcular ni verificar el
hash aunque se tenga la base de datos completa.

Falla cerrado: si falta IDENTITY_PEPPER y DEBUG=False, identity_hash()
lanza IdentityPepperMissing en vez de degradar silenciosamente a un hash
sin sal.
"""
import hashlib
import hmac
import re

from .config import settings


class IdentityPepperMissing(RuntimeError):
    """IDENTITY_PEPPER no está configurado y DEBUG=False (fail closed)."""


def _previous_pepper_bytes() -> bytes | None:
    """Pepper anterior durante una rotación, o None.

    Rotar `IDENTITY_PEPPER` invalida DE GOLPE todos los índices ciegos
    (`rut_key`, `email_key`, `subject_key`): son derivaciones determinísticas
    del pepper, así que con uno nuevo ningún registro existente se encuentra y
    todo el mundo queda fuera hasta terminar la migración.

    `IDENTITY_PEPPER_PREVIOUS` es la ventana que evita ese apagón: las
    búsquedas prueban también con el pepper viejo mientras
    `scripts/pii_maintenance.py reindex` recalcula las claves. Cuando `status`
    reporta 0 registros pendientes, la variable se retira.

    Nunca se usa para ESCRIBIR: lo nuevo siempre se indexa con el pepper
    vigente, o la migración no terminaría nunca.
    """
    previous = settings.IDENTITY_PEPPER_PREVIOUS.strip()
    return previous.encode("utf-8") if previous else None


def _pepper_bytes() -> bytes:
    pepper = settings.IDENTITY_PEPPER
    if not pepper:
        if settings.DEBUG:
            # Solo en desarrollo local: pepper determinístico y obvio para
            # que nadie lo confunda con uno real, pero permite trabajar sin
            # configurar secretos.
            pepper = "dev-only-insecure-pepper-do-not-use-in-production"
        else:
            raise IdentityPepperMissing(
                "IDENTITY_PEPPER no está configurado. Sin él no se puede "
                "calcular ni verificar ningún hash de identidad de forma "
                "segura, así que se rechaza en vez de usar un hash sin sal."
            )
    return pepper.encode("utf-8")


def normalize_rut(rut: str) -> str:
    """Quita puntos, guión y espacios; deja el dígito verificador en mayúscula."""
    cleaned = re.sub(r"[.\-\s]", "", rut or "").upper()
    return cleaned


def identity_hash(rut: str) -> bytes:
    """HMAC-SHA256(pepper, rut_normalizado) -> 32 bytes.

    Determinístico (mismo RUT -> mismo hash) para poder buscar por él,
    pero no reversible sin el pepper.
    """
    normalized = normalize_rut(rut)
    return hmac.new(_pepper_bytes(), normalized.encode("utf-8"), hashlib.sha256).digest()


def identity_hash_hex(rut: str) -> str:
    return "0x" + identity_hash(rut).hex()


def document_identity_hash(doc_hash: str) -> bytes:
    """HMAC-SHA256(pepper, "onchain-identity:" + doc_hash) -> 32 bytes.

    Es el valor que se sube on-chain como identityHash del SBT (ver
    services/chain_service.py y contracts/DAOCiudadanaSBT.sol). doc_hash ya
    es un hash del documento verificado por NFC (no PII cruda), pero se
    vuelve a peppear antes de publicarlo: así, aunque doc_hash se filtrara
    de la base de datos, nadie podría recalcular el mismo identityHash
    on-chain sin el pepper del servidor. Dominio separado del de
    identity_hash()/lookup_key() a propósito (mismo pepper, mensaje
    distinto) para que un mismo valor nunca produzca el mismo hash en dos
    contextos distintos.
    """
    normalized = (doc_hash or "").strip().lower()
    return hmac.new(
        _pepper_bytes(), b"onchain-identity:" + normalized.encode("utf-8"), hashlib.sha256
    ).digest()


def document_identity_hash_hex(doc_hash: str) -> str:
    return "0x" + document_identity_hash(doc_hash).hex()


def _lookup_key_with(pepper: bytes, value: str, domain: str) -> str:
    normalized = (value or "").strip().lower()
    digest = hmac.new(
        pepper,
        f"{domain}:".encode("utf-8") + normalized.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return digest.hex()


def lookup_key(value: str, domain: str = "lookup") -> str:
    """Índice ciego para buscar un valor cifrado sin descifrar toda la colección.

    Usa separación de dominio (prefijo) para que el mismo valor en dos
    dominios distintos (p.ej. email como email vs. email como rut) no
    produzca el mismo lookup_key.

    Siempre con el pepper VIGENTE: es la clave con la que se escribe.
    """
    return _lookup_key_with(_pepper_bytes(), value, domain)


def lookup_key_candidates(value: str, domain: str = "lookup") -> list[str]:
    """Claves con las que ese valor puede estar indexado ahora mismo.

    Durante una rotación de pepper hay dos: la vigente y la anterior. Las
    consultas usan `$in` sobre esta lista para que un registro todavía no
    migrado se siga encontrando; fuera de una rotación devuelve una sola y la
    consulta es idéntica a la de antes.
    """
    keys = [lookup_key(value, domain)]
    previous = _previous_pepper_bytes()
    if previous:
        stale = _lookup_key_with(previous, value, domain)
        if stale not in keys:
            keys.append(stale)
    return keys
