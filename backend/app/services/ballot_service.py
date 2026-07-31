"""
Papeletas de voto firmadas con EIP-712 (D-3 del ADR).

Antes: un voto era un POST /governance/vote con voter_address en el body
-- sin nada que probara que el dueño de esa dirección efectivamente quiso
emitir ESE voto específico. Combinado con el hallazgo C-1 (nadie
verificaba que quien llamaba al endpoint controlara la dirección), el
recuento no era criptográficamente verificable.

Ahora: el cliente firma la papeleta con eth_signTypedData_v4 (EIP-712,
para que la wallet le muestre los campos legibles en vez de un blob
hexadecimal) y el backend recupera el firmante y lo compara contra
voter_address. El schema se sirve desde /governance/ballot-schema para
que frontend/móvil nunca mantengan una copia manual desincronizada.
"""
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi import HTTPException

from ..core.config import settings
from ..core.database import ballot_nonces_collection

BALLOT_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
    ],
    "Ballot": [
        {"name": "proposalId", "type": "string"},
        {"name": "voter", "type": "address"},
        {"name": "choice", "type": "string"},
        {"name": "nonce", "type": "string"},
    ],
}

DOMAIN_NAME = "DAO Ciudadana"
DOMAIN_VERSION = "1"
DEFAULT_CHAIN_ID = 11155111  # Sepolia


def domain(chain_id: int = DEFAULT_CHAIN_ID) -> dict:
    return {"name": DOMAIN_NAME, "version": DOMAIN_VERSION, "chainId": chain_id}


def typed_data(proposal_id: str, voter: str, choice: str, nonce: str, chain_id: int = DEFAULT_CHAIN_ID) -> dict:
    return {
        "types": BALLOT_TYPES,
        "primaryType": "Ballot",
        "domain": domain(chain_id),
        "message": {
            "proposalId": proposal_id,
            "voter": voter,
            "choice": choice,
            "nonce": nonce,
        },
    }


def recover_signer(proposal_id: str, voter: str, choice: str, nonce: str, signature: str, chain_id: int = DEFAULT_CHAIN_ID) -> str:
    data = typed_data(proposal_id, voter, choice, nonce, chain_id)
    encoded = encode_typed_data(full_message=data)
    return Account.recover_message(encoded, signature=signature)


async def verify(proposal_id: str, voter_address: str, choice: str, nonce: str, signature: str) -> None:
    """Lanza HTTPException 401/409 si la firma es inválida o el nonce ya se usó."""
    if not nonce:
        raise HTTPException(status_code=422, detail="Falta el nonce de la papeleta.")

    try:
        recovered = recover_signer(proposal_id, voter_address, choice, nonce, signature)
    except Exception:
        raise HTTPException(status_code=401, detail="Firma de la papeleta inválida.")

    if recovered.lower() != voter_address.lower():
        raise HTTPException(
            status_code=401,
            detail="La firma de la papeleta no corresponde a la dirección del votante.",
        )

    # Anti-replay: un (voter_address, nonce) solo se puede usar una vez.
    # El índice único en ballot_nonces es lo que realmente lo garantiza
    # bajo concurrencia; esta comprobación solo da un mensaje más claro.
    try:
        await ballot_nonces_collection().insert_one({
            "voter_address": voter_address.lower(),
            "nonce": nonce,
            "proposal_id": proposal_id,
        })
    except Exception:
        raise HTTPException(
            status_code=409,
            detail="Esta papeleta ya fue usada (nonce repetido). Genera una nueva.",
        )
