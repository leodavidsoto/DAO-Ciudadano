"""
Cifrado de PII en reposo.

Antes: rut/email/nombre/apellido se guardaban en texto plano en MongoDB
(ver backend/app/routers/auth.py). Cualquiera con acceso de lectura a la
base de datos (backup, snapshot, empleado del hosting) veía datos
personales de ciudadanos chilenos sin ninguna barrera.

Ahora: Fernet (AES-128-CBC + HMAC-SHA256, de la librería `cryptography`)
sobre cada campo sensible, con PII_ENCRYPTION_KEY como llave simétrica.
La búsqueda por RUT/email sigue funcionando vía índices ciegos
(identity.lookup_key), no descifrando la colección entera.

Falla cerrado: sin PII_ENCRYPTION_KEY y DEBUG=False, encrypt()/decrypt()
lanzan EncryptionKeyMissing.
"""
from cryptography.fernet import Fernet, InvalidToken

from .config import settings


class EncryptionKeyMissing(RuntimeError):
    """PII_ENCRYPTION_KEY no está configurado y DEBUG=False (fail closed)."""


_DEV_ONLY_KEY = Fernet.generate_key().decode("utf-8")


def _fernet() -> Fernet:
    key = settings.PII_ENCRYPTION_KEY
    if not key:
        if settings.DEBUG:
            key = _DEV_ONLY_KEY
        else:
            raise EncryptionKeyMissing(
                "PII_ENCRYPTION_KEY no está configurado. Sin él no se puede "
                "cifrar ni descifrar PII de forma segura."
            )
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def generate_key() -> str:
    """Genera una llave Fernet nueva (para configurar PII_ENCRYPTION_KEY)."""
    return Fernet.generate_key().decode("utf-8")


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        return None
    token = _fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt(ciphertext: str) -> str:
    if ciphertext is None:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("No se pudo descifrar el valor (llave incorrecta o dato corrupto)") from exc
