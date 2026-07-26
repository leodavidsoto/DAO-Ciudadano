"""
Unit tests for security helpers: address/nonce validation, vote hashing,
RUT validation and the fraud detector.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security_middleware import (  # noqa: E402
    FraudDetector,
    generate_nonce,
    hash_vote_data,
    verify_eth_address,
    verify_nonce,
)
from app.routers.auth import format_rut, validate_rut  # noqa: E402


# === Ethereum address validation ===

def test_verify_eth_address_accepts_valid():
    assert verify_eth_address("0x" + "ab" * 20) is True


def test_verify_eth_address_rejects_bad_input():
    assert verify_eth_address("") is False
    assert verify_eth_address("0x123") is False
    assert verify_eth_address("ab" * 21) is False
    assert verify_eth_address("0x" + "zz" * 20) is False


# === Nonces ===

def test_generate_nonce_is_valid_and_unique():
    first, second = generate_nonce(), generate_nonce()
    assert verify_nonce(first) is True
    assert first != second


def test_verify_nonce_rejects_bad_format():
    assert verify_nonce("") is False
    assert verify_nonce("abc") is False
    assert verify_nonce("g" * 64) is False  # Not hex


# === Vote hashing ===

def test_hash_vote_data_is_deterministic_and_case_insensitive():
    args = ("prop-1", "0x" + "AB" * 20, "for", "0" * 64)
    lower = ("prop-1", "0x" + "ab" * 20, "for", "0" * 64)
    assert hash_vote_data(*args) == hash_vote_data(*lower)
    assert hash_vote_data(*args) != hash_vote_data("prop-2", *args[1:])


# === Chilean RUT validation ===

def test_validate_rut_accepts_valid_check_digits():
    assert validate_rut("11111111-1") is True
    assert validate_rut("11.111.111-1") is True
    assert validate_rut("12345678-5") is True


def test_validate_rut_rejects_invalid():
    assert validate_rut("12345678-9") is False  # Wrong check digit
    assert validate_rut("1-9") is False  # Too short
    assert validate_rut("") is False
    assert validate_rut("abcdefgh-1") is False


def test_format_rut():
    assert format_rut("111111111") == "11.111.111-1"
    assert format_rut("12345678-5") == "12.345.678-5"


# === Fraud detector ===

def test_fraud_detector_flags_rapid_voting():
    detector = FraudDetector()
    flagged = False
    for i in range(15):
        suspicious, reason = detector.check_rapid_voting("0xabc", f"prop-{i}")
        if suspicious:
            flagged = True
            assert "Too many votes" in reason
            break
    assert flagged is True


def test_fraud_detector_flags_delegate_with_too_many_delegators():
    detector = FraudDetector()
    for i in range(10):
        detector.record_delegation(f"0xdelegator{i}", "0xpopular")
    suspicious, reason = detector.check_delegation_chain("0xnew", "0xpopular")
    assert suspicious is True
    assert "too many delegators" in reason.lower()
