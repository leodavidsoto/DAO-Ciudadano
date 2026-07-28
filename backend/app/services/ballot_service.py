"""
Signed ballots (ROADMAP 3.2 and 3.3, ADR 0001 decision D-3).

Governance lived entirely in MongoDB: whoever ran the backend could edit the
results without leaving a trace. Requiring a session token fixed *who* can
vote, not *whether the recorded tally matches what people actually voted*.

Every ballot is now an EIP-712 typed message signed by the voter. The stored
signature lets any third party recompute the result without trusting the
server: they fetch the ballots, recover each signer, and count.

WHAT THIS DOES NOT SOLVE, stated plainly: signatures prevent the operator
from FABRICATING votes, not from CENSORING them — an omitted ballot leaves no
trace. Publishing a periodic Merkle root on-chain would make omission
detectable. Registered in the ADR as pending.
"""
import logging
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_typed_data

from ..core.config import settings
from ..core.database import get_collection

logger = logging.getLogger(__name__)

# Bumped whenever the typed structure changes: signatures are only valid for
# the exact schema they were produced against.
EIP712_DOMAIN = {
    "name": "DAO Ciudadana",
    "version": "1",
}

BALLOT_TYPES = {
    "Ballot": [
        {"name": "proposalId", "type": "string"},
        {"name": "voter", "type": "address"},
        {"name": "choice", "type": "string"},
        {"name": "nonce", "type": "string"},
    ],
}


def used_nonces_collection():
    return get_collection("used_nonces")


class BallotService:
    """Build, verify and replay-protect signed ballots."""

    @staticmethod
    def domain() -> dict:
        """EIP-712 domain, chain-bound so a Sepolia ballot is not valid on mainnet."""
        domain = dict(EIP712_DOMAIN)
        if settings.SBT_CHAIN_ID:
            domain["chainId"] = int(settings.SBT_CHAIN_ID)
        return domain

    @classmethod
    def typed_data(cls, proposal_id: str, voter: str, choice: str, nonce: str) -> dict:
        """The exact structure the wallet signs. Shared with the frontend."""
        return {
            "types": BALLOT_TYPES,
            "primaryType": "Ballot",
            "domain": cls.domain(),
            "message": {
                "proposalId": proposal_id,
                "voter": voter,
                "choice": choice,
                "nonce": nonce,
            },
        }

    @classmethod
    def recover_signer(
        cls, proposal_id: str, voter: str, choice: str, nonce: str, signature: str
    ) -> Optional[str]:
        """Address that produced `signature`, or None if it cannot be recovered."""
        try:
            data = cls.typed_data(proposal_id, voter, choice, nonce)
            message = encode_typed_data(full_message=data)
            return Account.recover_message(message, signature=signature).lower()
        except Exception as e:
            logger.warning(f"Could not recover ballot signer: {e}")
            return None

    @classmethod
    async def verify(
        cls, proposal_id: str, voter: str, choice: str, nonce: str, signature: str
    ) -> tuple[bool, Optional[str]]:
        """Verify signature and consume the nonce. Returns (ok, error).

        The nonce is consumed with an insert against a unique index rather
        than a read-then-write: two concurrent replays of the same signed
        ballot must not both be accepted (ROADMAP 3.3).
        """
        from pymongo.errors import DuplicateKeyError

        recovered = cls.recover_signer(proposal_id, voter, choice, nonce, signature)
        if recovered is None:
            return (False, "Firma inválida")
        if recovered != voter.lower():
            logger.warning(f"Ballot signed by {recovered}, submitted as {voter}")
            return (False, "La firma no corresponde a la dirección votante")

        try:
            await used_nonces_collection().insert_one({
                "scope": "ballot",
                "voter": voter.lower(),
                "nonce": nonce,
            })
        except DuplicateKeyError:
            return (False, "Esta papeleta ya fue utilizada")

        return (True, None)


ballot_service = BallotService()
