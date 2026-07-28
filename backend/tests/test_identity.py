"""
Identity hashing (ADR 0001, decision D-2).

What matters here is not that the function returns a hash, but that it has the
three properties the design depends on: deterministic (the contract enforces
one membership per identity), unpredictable without the pepper (the previous
scheme was reversible in seconds), and fail-closed when unconfigured.
"""
import importlib

import pytest

from app.core import identity as identity_module
from app.core.config import settings
from app.core.identity import (
    IdentityPepperMissing,
    identity_hash,
    identity_hash_hex,
    lookup_key,
    normalize_rut,
)

RUT = "12.345.678-9"


def test_normalisation_makes_formats_equivalent():
    """Same person, three spellings — must not yield three memberships."""
    assert normalize_rut("12.345.678-9") == normalize_rut("12345678-9") == "123456789"
    assert normalize_rut(" 12.345.678-k ") == "12345678K"


def test_hash_is_deterministic_across_formats():
    """The contract's _usedIdentityHashes check depends on this."""
    assert identity_hash_hex("12.345.678-9") == identity_hash_hex("123456789")


def test_hash_is_32_bytes():
    """bytes32 on-chain, not a truncated hex string."""
    assert len(identity_hash(RUT)) == 32
    assert len(identity_hash_hex(RUT)) == 66  # '0x' + 64


def test_different_ruts_give_different_hashes():
    assert identity_hash_hex(RUT) != identity_hash_hex("11.111.111-1")


def test_pepper_changes_the_output(monkeypatch):
    """Without the pepper the hash must not be reproducible.

    This is the whole point: the previous sha256(RUT) could be brute-forced
    over the ~30M valid RUTs in seconds.
    """
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", "pepper-a", raising=False)
    with_a = identity_hash_hex(RUT)
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", "pepper-b", raising=False)
    with_b = identity_hash_hex(RUT)
    assert with_a != with_b


def test_fails_closed_without_pepper_in_production(monkeypatch):
    """No pepper outside development means no hashing at all."""
    monkeypatch.setattr(settings, "IDENTITY_PEPPER", "", raising=False)
    monkeypatch.setattr(settings, "DEBUG", False, raising=False)
    with pytest.raises(IdentityPepperMissing):
        identity_hash(RUT)


def test_lookup_key_is_domain_separated():
    """A leaked blind index must not correlate with the on-chain hashes."""
    assert lookup_key(RUT) != identity_hash(RUT).hex()


def test_lookup_key_is_case_insensitive():
    """Emails differing only in case are the same account."""
    assert lookup_key("Persona@Ejemplo.CL") == lookup_key("persona@ejemplo.cl")


def test_rejects_empty_input():
    with pytest.raises(ValueError):
        identity_hash("")
    with pytest.raises(ValueError):
        lookup_key("")
