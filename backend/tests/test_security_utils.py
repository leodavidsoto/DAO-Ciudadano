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

async def test_fraud_detector_flags_rapid_voting():
    """El historial de votos vive ahora en el almacén compartido (ROADMAP 3.8)."""
    from app.core.rate_limit_store import InMemoryRateLimitStore

    detector = FraudDetector(store=InMemoryRateLimitStore())

    flagged = False
    for _ in range(15):
        suspicious, reason = await detector.check_rapid_voting("0xabc", "prop-1")
        if suspicious:
            flagged = True
            assert "Too many votes" in reason
            break

    assert flagged is True


async def test_rapid_voting_cannot_be_evaded_by_rotating_the_proposal():
    """El límite es por votante, no por propuesta.

    Si la propuesta formara parte de la clave, bastaría rotar el identificador
    para emitir la cuota entera contra cada una.
    """
    from app.core.rate_limit_store import InMemoryRateLimitStore

    detector = FraudDetector(store=InMemoryRateLimitStore())

    verdicts = [
        (await detector.check_rapid_voting("0xabc", f"prop-{i}"))[0]
        for i in range(12)
    ]

    assert any(verdicts), "rotar el proposal_id evadió el límite"


async def test_fraud_detector_without_a_store_fails_closed():
    """Sin almacén no se inventa un veredicto favorable.

    Dejar pasar en silencio desactivaría el antifraude sin que nadie lo note.
    """
    detector = FraudDetector(store=None)

    suspicious, reason = await detector.check_rapid_voting("0xabc", "prop-1")

    assert suspicious is True
    assert "no disponible" in reason


async def test_rapid_voting_state_is_shared_between_workers():
    """Dos procesos contra el mismo almacén comparten el historial.

    Es la razón de la migración: con estado por proceso, un votante duplicaba
    su cuota simplemente cayendo en otra instancia.
    """
    import fakeredis.aioredis

    from app.core.rate_limit_store import RedisRateLimitStore

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    worker_a = FraudDetector(store=RedisRateLimitStore(client))
    worker_b = FraudDetector(store=RedisRateLimitStore(client))

    for _ in range(FraudDetector.MAX_VOTES_PER_WINDOW):
        assert (await worker_a.check_rapid_voting("0xabc", "p"))[0] is False

    # El siguiente se marca aunque llegue al OTRO worker.
    suspicious, _ = await worker_b.check_rapid_voting("0xabc", "p")
    assert suspicious is True
