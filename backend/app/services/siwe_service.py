"""
Sign-In With Ethereum (EIP-4361) — ROADMAP 1.1, audit findings C-1 and C-6.

Before this, the API had no authentication at all: `voter_address` arrived in
the request body and the backend believed it. Anyone could vote, propose or
mint as anybody else with a single curl. The RUT+email login was no better —
both are public or guessable, so knowing them was enough to impersonate.

Here the caller proves control of the address by signing a nonce we issued.
Nothing else grants a session.

Deliberately NOT a full EIP-4361 parser: we generate the message ourselves and
compare it verbatim, so there is no room for a parser discrepancy between what
we validate and what the user signed.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from eth_account import Account
from eth_account.messages import encode_defunct

from ..core.config import settings
from ..core.database import get_collection

logger = logging.getLogger(__name__)

NONCE_TTL_SECONDS = 300      # 5 min to sign; long enough for a hardware wallet
JWT_ALGORITHM = "HS256"


def nonces_collection():
    return get_collection("siwe_nonces")


class SiweService:
    """Issue nonces, verify signatures, mint and read session tokens."""

    @staticmethod
    def build_message(address: str, nonce: str, issued_at: str) -> str:
        """The exact text the wallet signs.

        Includes the domain and a statement in Spanish so the person reading
        the MetaMask prompt understands what they are approving — a blind
        signature request is how phishing works.
        """
        return (
            f"{settings.SIWE_DOMAIN} quiere que inicies sesión con tu wallet.\n\n"
            f"Al firmar este mensaje acreditas que controlas esta dirección.\n"
            f"No autoriza ninguna transacción ni gasto.\n\n"
            f"Dirección: {address}\n"
            f"Nonce: {nonce}\n"
            f"Emitido: {issued_at}"
        )

    @classmethod
    async def create_challenge(cls, address: str) -> dict:
        """Issue a single-use nonce bound to `address`."""
        address = address.lower()
        nonce = secrets.token_hex(16)
        now = datetime.now(timezone.utc)
        issued_at = now.isoformat()

        await nonces_collection().insert_one({
            "address": address,
            "nonce": nonce,
            "issued_at": issued_at,
            "expires_at": now + timedelta(seconds=NONCE_TTL_SECONDS),
            "used": False,
        })

        return {
            "address": address,
            "nonce": nonce,
            "issued_at": issued_at,
            "message": cls.build_message(address, nonce, issued_at),
            "expires_in": NONCE_TTL_SECONDS,
        }

    @classmethod
    async def verify(cls, address: str, signature: str) -> tuple[bool, Optional[str], Optional[str]]:
        """Verify a signed challenge. Returns (ok, token, error).

        The nonce is consumed atomically with find_one_and_update: two
        concurrent replays of the same signature must not both succeed.
        """
        address = address.lower()

        record = await nonces_collection().find_one_and_update(
            {"address": address, "used": False},
            {"$set": {"used": True}},
            sort=[("expires_at", -1)],
        )
        if not record:
            return (False, None, "No hay un desafío pendiente para esta dirección")

        expires_at = record["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            return (False, None, "El desafío expiró; solicita uno nuevo")

        message = cls.build_message(address, record["nonce"], record["issued_at"])
        try:
            recovered = Account.recover_message(
                encode_defunct(text=message), signature=signature
            )
        except Exception as e:
            logger.warning(f"Signature recovery failed for {address}: {e}")
            return (False, None, "Firma inválida")

        if recovered.lower() != address:
            logger.warning(f"Signature address mismatch: {recovered} != {address}")
            return (False, None, "La firma no corresponde a esta dirección")

        return (True, cls.issue_token(address), None)

    @staticmethod
    def issue_token(address: str) -> str:
        """Short-lived session token. `sub` is the proven address."""
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": address.lower(),
                "iat": now,
                "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            },
            settings.SECRET_KEY,
            algorithm=JWT_ALGORITHM,
        )

    @staticmethod
    def read_token(token: str) -> Optional[str]:
        """Return the address in a valid token, or None."""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload.get("sub")
        except jwt.ExpiredSignatureError:
            logger.info("Rejected an expired session token")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Rejected an invalid session token: {e}")
            return None


siwe_service = SiweService()
