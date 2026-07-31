"""
Sesión de wallet vía Sign-In With Ethereum (EIP-4361) + JWT corto.

Antes de esto, cualquier endpoint que recibiera un `wallet_address` en el
body confiaba ciegamente en que quien hacía el request controlaba esa
dirección -- nada impedía que Alice minteara o votara "como" Bob con solo
poner su dirección en el JSON (hallazgo C-1).

Ahora: el cliente pide un desafío (nonce de un solo uso), lo firma con
`personal_sign` desde su wallet, el backend recupera la dirección que
realmente firmó y, si coincide con la reclamada, emite un JWT corto que
autentica esa dirección para las siguientes acciones.
"""
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from eth_account.messages import encode_defunct
from eth_account import Account
from fastapi import HTTPException

from ..core.config import settings
from ..core.database import siwe_nonces_collection

DOMAIN = "dao-ciudadana"
STATEMENT = "Firma este mensaje para iniciar sesión en DAO Ciudadana. Esto no autoriza ninguna transacción ni gasta gas."


def _checksum(address: str) -> str:
    try:
        from eth_utils import to_checksum_address
        return to_checksum_address(address)
    except Exception:
        return address


def build_message(address: str, nonce: str, issued_at: str) -> str:
    """Mensaje EIP-4361 simplificado, determinístico a partir de (address,
    nonce, issued_at).

    No se parsea texto arbitrario en verify(): se reconstruye este mismo
    mensaje server-side con el nonce e issued_at GUARDADOS en create_challenge
    (nunca recalculados) y se compara la firma contra él. issued_at debe
    venir del registro guardado, no de `datetime.now()` en el momento de
    verify() -- si se recalculara ahí, el mensaje reconstruido nunca
    coincidiría con el que el cliente realmente firmó y toda firma válida
    fallaría.
    """
    return (
        f"{DOMAIN} quiere que inicies sesión con tu cuenta Ethereum:\n"
        f"{_checksum(address)}\n\n"
        f"{STATEMENT}\n\n"
        f"URI: https://{DOMAIN}\n"
        f"Version: 1\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}"
    )


async def create_challenge(address: str) -> dict:
    address = address.lower()
    nonce = secrets.token_hex(16)
    issued_at = datetime.now(timezone.utc).isoformat()
    await siwe_nonces_collection().insert_one({
        "nonce": nonce,
        "address": address,
        "issued_at": issued_at,
        "created_at": datetime.now(timezone.utc),
        "consumed": False,
    })
    return {"message": build_message(address, nonce, issued_at), "nonce": nonce}


async def verify(address: str, nonce: str, signature: str) -> str:
    """Verifica la firma y consume el nonce atómicamente (anti-replay).

    Devuelve la dirección (checksummed) si todo es válido, o lanza
    HTTPException 401 con un motivo específico.
    """
    address_lower = address.lower()

    # find_one_and_update con consumed=False -> True es atómico: dos
    # requests concurrentes con el mismo nonce, solo uno gana.
    record = await siwe_nonces_collection().find_one_and_update(
        {"nonce": nonce, "address": address_lower, "consumed": False},
        {"$set": {"consumed": True}},
    )
    if not record:
        raise HTTPException(
            status_code=401,
            detail="Desafío inválido, expirado o ya usado. Pide uno nuevo e inténtalo de nuevo.",
        )

    expected_message = build_message(address_lower, nonce, record["issued_at"])

    try:
        encoded = encode_defunct(text=expected_message)
        recovered = Account.recover_message(encoded, signature=signature)
    except Exception:
        raise HTTPException(status_code=401, detail="Firma inválida.")

    if recovered.lower() != address_lower:
        raise HTTPException(
            status_code=401,
            detail="La firma no corresponde a la dirección indicada.",
        )

    return _checksum(address_lower)


def issue_token(address: str) -> str:
    now = int(time.time())
    payload = {
        "sub": address.lower(),
        "iat": now,
        "exp": now + settings.SESSION_TOKEN_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def read_token(token: str) -> Optional[str]:
    """Devuelve la dirección (lowercase) del token, o None si es inválido/expiró."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
