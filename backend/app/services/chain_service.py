"""
Minteo real on-chain (ROADMAP tarea 1.5, D-1).

Antes: mint_sbt() solo escribía en MongoDB y devolvía tx_hash=None siempre
-- "membership" no significaba nada fuera de esta base de datos.

Ahora: si SEPOLIA_RPC_URL, SBT_CONTRACT_ADDRESS y MINTER_PRIVATE_KEY están
configurados, mint_sbt() además envía una transacción real que llama a
DAOCiudadanaSBT.mintMembership(...) (contratos/DAOCiudadanaSBT.sol, con
AccessControl -- la llave del minter solo necesita MINTER_ROLE, no
DEFAULT_ADMIN_ROLE). Si no está configurado, se cae a modo demo
(blockchain_service.py ya lo hacía) -- nunca se fabrica un tx_hash falso.
"""
import logging
from typing import Optional, Tuple

from ..core.config import settings

logger = logging.getLogger(__name__)

# ABI mínima: solo lo que este servicio necesita, no el ABI completo del
# contrato. Evita depender del archivo de artifacts de Hardhat en runtime.
_MINT_ABI = [
    {
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "identityHash", "type": "bytes32"},
            {"name": "assuranceLevel", "type": "string"},
            {"name": "uri", "type": "string"},
        ],
        "name": "mintMembership",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "member", "type": "address"},
            {"indexed": True, "name": "tokenId", "type": "uint256"},
            {"indexed": False, "name": "assuranceLevel", "type": "string"},
            {"indexed": False, "name": "timestamp", "type": "uint256"},
        ],
        "name": "MembershipMinted",
        "type": "event",
    },
]


class ChainMintError(RuntimeError):
    """El envío de la transacción de minteo falló (RPC, gas, revert, etc.)."""


def is_configured() -> bool:
    return bool(settings.SEPOLIA_RPC_URL and settings.SBT_CONTRACT_ADDRESS and settings.MINTER_PRIVATE_KEY)


def _client():
    """Construye (w3, contract, account) bajo demanda.

    Import local de web3/eth_account: así los módulos que no mintean
    on-chain (la mayoría de los tests) no pagan el costo de importarlos.
    """
    from web3 import Web3
    from eth_account import Account

    w3 = Web3(Web3.HTTPProvider(settings.SEPOLIA_RPC_URL))
    account = Account.from_key(settings.MINTER_PRIVATE_KEY)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(settings.SBT_CONTRACT_ADDRESS),
        abi=_MINT_ABI,
    )
    return w3, contract, account


def mint_sbt_onchain(
    wallet_address: str,
    identity_hash_hex: str,
    assurance_level: str,
    token_uri: str = "",
) -> Tuple[str, Optional[int]]:
    """Envía la transacción de minteo real. Devuelve (tx_hash, token_id).

    token_id se lee del evento MembershipMinted en el recibo; si por algún
    motivo no aparece (RPC raro), se devuelve None y el llamador debe
    resolverlo vía getMembershipToken() en vez de asumir un valor.

    Lanza ChainMintError con el motivo si el RPC rechaza la transacción o si
    la transacción se revierte on-chain (revert del contrato: dirección ya
    tiene membresía, identityHash repetido, contrato pausado, etc.) -- nunca
    devuelve un tx_hash falso.
    """
    from web3 import Web3

    if not is_configured():
        raise ChainMintError("Minteo on-chain no está configurado (SEPOLIA_RPC_URL/SBT_CONTRACT_ADDRESS/MINTER_PRIVATE_KEY).")

    w3, contract, account = _client()

    try:
        to = Web3.to_checksum_address(wallet_address)
        identity_hash_bytes = bytes.fromhex(identity_hash_hex.removeprefix("0x"))
        if len(identity_hash_bytes) != 32:
            raise ChainMintError(f"identityHash debe ser bytes32 (32 bytes), recibido {len(identity_hash_bytes)}.")

        nonce = w3.eth.get_transaction_count(account.address, "pending")
        tx = contract.functions.mintMembership(
            to, identity_hash_bytes, assurance_level, token_uri
        ).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "chainId": w3.eth.chain_id,
        })

        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt.status != 1:
            raise ChainMintError(f"La transacción se revirtió on-chain (tx {tx_hash.hex()}).")

        token_id = None
        try:
            events = contract.events.MembershipMinted().process_receipt(receipt)
            if events:
                token_id = int(events[0]["args"]["tokenId"])
        except Exception as e:
            logger.warning(f"No se pudo leer el tokenId del recibo (tx {tx_hash.hex()}): {e}")

        return tx_hash.hex(), token_id

    except ChainMintError:
        raise
    except Exception as e:
        logger.error(f"Error minteando on-chain para {wallet_address}: {e}")
        raise ChainMintError(str(e))
