"""
Identity hashing (ADR 0001, decision D-2).

The previous scheme was `sha256(RUT)[:16]` with no salt. Valid Chilean RUTs
number around 30 million: precomputing every hash takes seconds. Publishing
that on an immutable public ledger would expose the whole citizen registry,
permanently. An unsalted hash of a RUT is not anonymisation.

This module derives `HMAC-SHA256(RUT, pepper)` instead, 32 bytes, with the
pepper held outside the database (KMS in production).

A DELIBERATE CONSTRAINT: the hash must be DETERMINISTIC. The contract relies
on `_usedIdentityHashes[identityHash]` to stop one person minting twice, so a
per-user random salt — which would be more private — would break that
guarantee: two different hashes of the same person would both pass the check.

RESIDUAL RISK, stated in the ADR and repeated here because it matters: if the
pepper leaks, every already-minted identity becomes reversible retroactively
and permanently. On-chain values cannot be rotated. Treat the pepper as the
highest-value secret in the system.
"""
import hashlib
import hmac
import logging

from .config import settings

logger = logging.getLogger(__name__)


class IdentityPepperMissing(RuntimeError):
    """Raised when no pepper is configured outside development."""


def _pepper() -> bytes:
    pepper = settings.IDENTITY_PEPPER
    if not pepper:
        if settings.DEBUG:
            # Local development only. Deterministic so tests are reproducible,
            # and useless anywhere else because it is public knowledge.
            logger.warning(
                "IDENTITY_PEPPER not set; using the development pepper. "
                "NEVER run this configuration outside local development."
            )
            return b"dev-only-insecure-pepper"
        raise IdentityPepperMissing(
            "IDENTITY_PEPPER no está configurado. Sin pepper, el hash de "
            "identidad sería reversible por fuerza bruta (ver ADR 0001, D-2)."
        )
    return pepper.encode("utf-8")


def normalize_rut(rut: str) -> str:
    """Canonical form before hashing.

    `12.345.678-9`, `12345678-9` and `123456789` are the same person; without
    normalisation they would produce three different hashes and the same
    person could mint three memberships.
    """
    return rut.replace(".", "").replace("-", "").strip().upper()


def identity_hash(rut: str) -> bytes:
    """32-byte identity commitment for `rut`. Goes on-chain as bytes32."""
    if not rut:
        raise ValueError("rut vacío")
    return hmac.new(_pepper(), normalize_rut(rut).encode("utf-8"), hashlib.sha256).digest()


def identity_hash_hex(rut: str) -> str:
    """`identity_hash` as 0x-prefixed hex — the form the contract expects."""
    return "0x" + identity_hash(rut).hex()


def lookup_key(value: str) -> str:
    """Blind index for querying encrypted PII without decrypting the column.

    Same derivation, different domain separator, so a leaked index cannot be
    correlated with the on-chain identity hashes.
    """
    if not value:
        raise ValueError("valor vacío")
    return hmac.new(
        _pepper(), b"lookup:" + value.strip().lower().encode("utf-8"), hashlib.sha256
    ).hexdigest()
