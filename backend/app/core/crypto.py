"""
PII encryption at rest (ROADMAP 1.4, audit finding C-4).

The `users` collection stored RUT, email and full name in plaintext while the
README claimed "Datos PII nunca expuestos". A database dump — a misconfigured
Atlas network rule, a stolen backup — handed over the citizen registry.

Fernet (AES-128-CBC + HMAC-SHA256) from `cryptography`: authenticated, so a
tampered ciphertext fails to decrypt instead of silently returning garbage.

Encrypted values cannot be queried directly. Lookups go through the blind
index in app.core.identity.lookup_key, which is derived with a separate
domain so a leaked index cannot be correlated with the on-chain hashes.
"""
import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

logger = logging.getLogger(__name__)


class EncryptionKeyMissing(RuntimeError):
    """Raised when no encryption key is configured outside development."""


def _fernet() -> Fernet:
    key = settings.PII_ENCRYPTION_KEY
    if not key:
        if settings.DEBUG:
            logger.warning(
                "PII_ENCRYPTION_KEY not set; using the development key. "
                "NEVER run this configuration outside local development."
            )
            key = "dev-only-insecure-key"
        else:
            raise EncryptionKeyMissing(
                "PII_ENCRYPTION_KEY no está configurada. Sin ella, RUT, email "
                "y nombre quedarían en texto plano (hallazgo C-4)."
            )
    # Accept either a proper Fernet key or an arbitrary passphrase, so
    # operators cannot accidentally weaken it by supplying a short string.
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        return Fernet(derived)


def encrypt(value: Optional[str]) -> Optional[str]:
    """Encrypt a PII field. `None` stays `None` so optional fields work."""
    if value is None:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: Optional[str]) -> Optional[str]:
    """Decrypt a PII field.

    Returns None on a value that cannot be authenticated: a tampered or
    key-rotated record must not be served as if it were valid.
    """
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.error("Could not decrypt a PII field (tampered or rotated key)")
        return None


def generate_key() -> str:
    """Generate a fresh Fernet key. For operators, not used at runtime."""
    return Fernet.generate_key().decode("ascii")
