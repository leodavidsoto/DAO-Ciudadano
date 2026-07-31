"""
Papeletas firmadas EIP-712 (D-3 del ADR): app/services/ballot_service.py.

Unit-level (no HTTP): firma con eth_account, verifica con el propio
servicio, y confirma que la firma de OTRA papeleta o de OTRA cuenta se
rechaza, y que el nonce no se puede reutilizar (anti-replay).
"""
import pytest
from eth_account import Account
from fastapi import HTTPException

from app.services import ballot_service

VOTER = Account.from_key("0x" + "5e" * 32)
OTHER = Account.from_key("0x" + "6f" * 32)


def _sign(account, proposal_id, choice, nonce):
    data = ballot_service.typed_data(proposal_id, account.address, choice, nonce)
    from eth_account.messages import encode_typed_data
    encoded = encode_typed_data(full_message=data)
    return account.sign_message(encoded).signature.hex()


async def test_verify_accepts_a_valid_signature(client):
    signature = _sign(VOTER, "prop-1", "for", "nonce-1")
    # No debe lanzar
    await ballot_service.verify("prop-1", VOTER.address, "for", "nonce-1", signature)


async def test_verify_rejects_signature_from_a_different_account(client):
    signature = _sign(OTHER, "prop-1", "for", "nonce-2")
    with pytest.raises(HTTPException) as exc:
        await ballot_service.verify("prop-1", VOTER.address, "for", "nonce-2", signature)
    assert exc.value.status_code == 401


async def test_verify_rejects_a_tampered_choice(client):
    """Firmado como "for", pero se intenta hacer valer como "against"."""
    signature = _sign(VOTER, "prop-1", "for", "nonce-3")
    with pytest.raises(HTTPException) as exc:
        await ballot_service.verify("prop-1", VOTER.address, "against", "nonce-3", signature)
    assert exc.value.status_code == 401


async def test_verify_rejects_a_reused_nonce(client):
    signature = _sign(VOTER, "prop-1", "for", "nonce-4")
    await ballot_service.verify("prop-1", VOTER.address, "for", "nonce-4", signature)

    replay = _sign(VOTER, "prop-2", "against", "nonce-4")
    with pytest.raises(HTTPException) as exc:
        await ballot_service.verify("prop-2", VOTER.address, "against", "nonce-4", replay)
    assert exc.value.status_code == 409
