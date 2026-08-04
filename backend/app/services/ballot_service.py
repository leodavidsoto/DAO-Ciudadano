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

import logging
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError, PyMongoError

from ..core.config import settings
from ..core.database import ballot_nonces_collection

logger = logging.getLogger(__name__)

# Papeleta de ELECCIÓN. `primaryType` distinto de "Ballot" a propósito: el
# structHash de EIP-712 incluye el nombre del tipo, así que una firma de
# propuesta no puede reutilizarse como voto de elección ni al revés. Sin esa
# separación, quien firmara "a favor" en una propuesta estaría firmando
# también un voto en cualquier elección con el mismo nonce.
ELECTION_BALLOT_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
    ],
    "ElectionBallot": [
        {"name": "electionId", "type": "string"},
        {"name": "voter", "type": "address"},
        {"name": "candidate", "type": "address"},
        {"name": "nonce", "type": "string"},
    ],
}

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


def domain(chain_id: Optional[int] = None) -> dict:
    effective_chain_id = settings.SIWE_CHAIN_ID if chain_id is None else chain_id
    return {
        "name": DOMAIN_NAME,
        "version": DOMAIN_VERSION,
        "chainId": effective_chain_id,
    }


def typed_data(
    proposal_id: str,
    voter: str,
    choice: str,
    nonce: str,
    chain_id: Optional[int] = None,
) -> dict:
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


def recover_signer(
    proposal_id: str,
    voter: str,
    choice: str,
    nonce: str,
    signature: str,
    chain_id: Optional[int] = None,
) -> str:
    data = typed_data(proposal_id, voter, choice, nonce, chain_id)
    encoded = encode_typed_data(full_message=data)
    return Account.recover_message(encoded, signature=signature)


async def verify(
    proposal_id: str, voter_address: str, choice: str, nonce: str, signature: str
) -> None:
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
    #
    # Solo DuplicateKeyError significa "nonce repetido". Un fallo de red o de
    # Mongo tiene que propagarse como indisponibilidad: decirle al votante que
    # su papeleta ya se usó lo haría firmar una nueva que fallaría igual, y
    # dejaría un voto legítimo sin registrar bajo una explicación falsa.
    try:
        await ballot_nonces_collection().insert_one(
            {
                "voter_address": voter_address.lower(),
                "nonce": nonce,
                "proposal_id": proposal_id,
            }
        )
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Esta papeleta ya fue usada (nonce repetido). Genera una nueva.",
        )
    except PyMongoError as exc:
        logger.error(
            "No se pudo registrar el nonce de la papeleta: %s", type(exc).__name__
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "No se pudo registrar la papeleta por un problema de "
                "almacenamiento. Tu voto NO quedó emitido; intenta de nuevo."
            ),
        ) from exc


# === Papeletas de elección (ROADMAP 3.2 / 3.3) ===============================


def election_typed_data(
    election_id: str,
    voter: str,
    candidate: str,
    nonce: str,
    chain_id: Optional[int] = None,
) -> dict:
    return {
        "types": ELECTION_BALLOT_TYPES,
        "primaryType": "ElectionBallot",
        "domain": domain(chain_id),
        "message": {
            "electionId": election_id,
            "voter": voter,
            "candidate": candidate,
            "nonce": nonce,
        },
    }


def recover_election_signer(
    election_id: str,
    voter: str,
    candidate: str,
    nonce: str,
    signature: str,
    chain_id: Optional[int] = None,
) -> str:
    encoded = encode_typed_data(
        full_message=election_typed_data(election_id, voter, candidate, nonce, chain_id)
    )
    return Account.recover_message(encoded, signature=signature)


async def verify_election_ballot(
    election_id: str,
    voter_address: str,
    candidate_address: str,
    nonce: str,
    signature: str,
) -> None:
    """Verifica la firma y consume el nonce. 401/409/503 según el motivo.

    El nonce se comparte con las papeletas de propuestas (misma colección y
    mismo índice único por votante). Es más estricto de lo necesario —un nonce
    gastado en una propuesta no sirve en una elección— pero evita tener dos
    espacios de nonces que razonar por separado, y el cliente los genera al
    azar de todas formas.
    """
    if not nonce:
        raise HTTPException(status_code=422, detail="Falta el nonce de la papeleta.")

    try:
        recovered = recover_election_signer(
            election_id, voter_address, candidate_address, nonce, signature
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Firma de la papeleta inválida.")

    if recovered.lower() != voter_address.lower():
        raise HTTPException(
            status_code=401,
            detail="La firma de la papeleta no corresponde a la dirección del votante.",
        )

    # Mismo criterio que en las propuestas: solo DuplicateKeyError significa
    # replay. Un fallo de almacenamiento que se reportara como "ya usada"
    # dejaría un voto legítimo sin registrar bajo una explicación falsa.
    try:
        await ballot_nonces_collection().insert_one(
            {
                "voter_address": voter_address.lower(),
                "nonce": nonce,
                "scope": "election",
                "election_id": election_id,
            }
        )
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Esta papeleta ya fue usada (nonce repetido). Genera una nueva.",
        )
    except PyMongoError as exc:
        logger.error(
            "No se pudo registrar el nonce de la papeleta de elección: %s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "No se pudo registrar la papeleta por un problema de "
                "almacenamiento. Tu voto NO quedó emitido; intenta de nuevo."
            ),
        ) from exc
