"""
Minteo real on-chain (ROADMAP tarea 1.5, D-1).

Antes: mint_sbt() solo escribía en MongoDB y devolvía tx_hash=None siempre
-- "membership" no significaba nada fuera de esta base de datos.

Ahora: si SEPOLIA_RPC_URL, SBT_CONTRACT_ADDRESS y MINTER_PRIVATE_KEY están
configurados, mint_sbt() además envía una transacción real que llama a
DAOCiudadanaSBT.mintMembership(...) (contratos/DAOCiudadanaSBT.sol, con
AccessControl -- la llave del minter solo necesita MINTER_ROLE, no
DEFAULT_ADMIN_ROLE). La selección se hace explícitamente con `MINT_MODE`;
una configuración incompleta o inválida falla y nunca degrada a demo ni
fabrica un `tx_hash`.
"""
import logging
import threading
import time
from typing import Optional, Tuple
from urllib.parse import urlparse

from ..core.config import settings

logger = logging.getLogger(__name__)

SEPOLIA_CHAIN_ID = 11155111
_runtime_cache = None
_RUNTIME_CACHE_SECONDS = 30
_nonce_lock = threading.Lock()

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
        "inputs": [{"name": "member", "type": "address"}],
        "name": "getMembershipToken",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
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
    {
        "inputs": [],
        "name": "MINTER_ROLE",
        "outputs": [{"name": "", "type": "bytes32"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "role", "type": "bytes32"},
            {"name": "account", "type": "address"},
        ],
        "name": "hasRole",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class ChainMintError(RuntimeError):
    """El envío de la transacción de minteo falló (RPC, gas, revert, etc.)."""


def configuration_errors() -> dict[str, str]:
    """Validate on-chain inputs without making a network request."""
    from web3 import Web3
    from eth_account import Account

    errors: dict[str, str] = {}

    rpc_url = settings.SEPOLIA_RPC_URL.strip()
    parsed_rpc = urlparse(rpc_url)
    if not rpc_url:
        errors["SEPOLIA_RPC_URL"] = "falta"
    elif parsed_rpc.scheme not in {"http", "https"} or not parsed_rpc.netloc:
        errors["SEPOLIA_RPC_URL"] = "debe ser una URL HTTP(S) válida"
    elif settings.is_production and parsed_rpc.scheme != "https":
        errors["SEPOLIA_RPC_URL"] = "debe usar HTTPS en producción"

    contract_address = settings.SBT_CONTRACT_ADDRESS.strip()
    if not contract_address:
        errors["SBT_CONTRACT_ADDRESS"] = "falta"
    elif not Web3.is_address(contract_address):
        errors["SBT_CONTRACT_ADDRESS"] = "debe ser una dirección Ethereum válida"

    private_key = settings.MINTER_PRIVATE_KEY.strip()
    if not private_key:
        errors["MINTER_PRIVATE_KEY"] = "falta"
    else:
        try:
            Account.from_key(private_key)
        except (TypeError, ValueError):
            errors["MINTER_PRIVATE_KEY"] = "debe ser una llave privada Ethereum válida"

    return errors


def is_configured() -> bool:
    return not configuration_errors()


def _client():
    """Construye (w3, contract, account) bajo demanda.

    Import local de web3/eth_account: así los módulos que no mintean
    on-chain (la mayoría de los tests) no pagan el costo de importarlos.
    """
    from web3 import Web3
    from eth_account import Account

    w3 = Web3(
        Web3.HTTPProvider(
            settings.SEPOLIA_RPC_URL,
            request_kwargs={"timeout": 5},
        )
    )
    account = Account.from_key(settings.MINTER_PRIVATE_KEY)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(settings.SBT_CONTRACT_ADDRESS),
        abi=_MINT_ABI,
    )
    return w3, contract, account


def runtime_status() -> dict:
    """Probe the selected chain, contract and minter without sending a tx.

    Results are cached briefly because `/health/ready` may be polled often;
    an unauthenticated health check must not amplify traffic to the RPC.
    Error messages are deliberately generic so an RPC URL containing an API
    key is never reflected to callers.
    """
    global _runtime_cache

    cache_key = (
        settings.SEPOLIA_RPC_URL,
        settings.SBT_CONTRACT_ADDRESS,
        settings.MINTER_PRIVATE_KEY,
    )
    now = time.monotonic()
    if _runtime_cache:
        cached_key, cached_at, cached_value = _runtime_cache
        if cached_key == cache_key and now - cached_at < _RUNTIME_CACHE_SECONDS:
            return dict(cached_value)

    errors = configuration_errors()
    result = {
        "checked": True,
        "ready": False,
        "chain_id": None,
        "minter_address": None,
        "errors": list(errors.values()),
    }
    if errors:
        _runtime_cache = (cache_key, now, result)
        return dict(result)

    try:
        w3, contract, account = _client()
        result["minter_address"] = account.address

        if not w3.is_connected():
            result["errors"] = ["RPC de Sepolia no disponible"]
        else:
            chain_id = int(w3.eth.chain_id)
            result["chain_id"] = chain_id
            if chain_id != SEPOLIA_CHAIN_ID:
                result["errors"] = [
                    f"chainId inesperado: {chain_id}; se requiere {SEPOLIA_CHAIN_ID}"
                ]
            elif not w3.eth.get_code(contract.address):
                result["errors"] = ["la dirección configurada no contiene bytecode"]
            else:
                minter_role = contract.functions.MINTER_ROLE().call()
                has_role = contract.functions.hasRole(
                    minter_role,
                    account.address,
                ).call()
                if not has_role:
                    result["errors"] = ["la wallet configurada no tiene MINTER_ROLE"]
                elif w3.eth.get_balance(account.address) <= 0:
                    result["errors"] = ["la wallet minter no tiene saldo para gas"]
                else:
                    result["errors"] = []
                    result["ready"] = True
    except Exception:
        logger.error("On-chain readiness probe failed", exc_info=True)
        result["errors"] = ["no se pudo validar RPC, contrato, ABI y MINTER_ROLE"]

    _runtime_cache = (cache_key, now, result)
    return dict(result)


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

    operational = runtime_status()
    if not operational.get("ready"):
        raise ChainMintError(
            "La precondición operativa on-chain falló; revisa RPC, red, "
            "contrato, MINTER_ROLE y saldo."
        )

    w3, contract, account = _client()

    try:
        to = Web3.to_checksum_address(wallet_address)
        identity_hash_bytes = bytes.fromhex(identity_hash_hex.removeprefix("0x"))
        if len(identity_hash_bytes) != 32:
            raise ChainMintError(f"identityHash debe ser bytes32 (32 bytes), recibido {len(identity_hash_bytes)}.")

        # Serialize nonce allocation/submission within this process. A real
        # production release still needs a distributed nonce manager or
        # relayer for multiple workers; readiness remains blocked until then.
        with _nonce_lock:
            nonce = w3.eth.get_transaction_count(account.address, "pending")
            tx = contract.functions.mintMembership(
                to, identity_hash_bytes, assurance_level, token_uri
            ).build_transaction({
                "from": account.address,
                "nonce": nonce,
                "chainId": SEPOLIA_CHAIN_ID,
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
            logger.warning(
                "No se pudo leer el tokenId del recibo (tx %s, %s)",
                tx_hash.hex(),
                type(e).__name__,
            )

        if token_id is None:
            # Never fabricate an off-chain id after a successful transaction.
            # Resolve the authoritative value from contract state; if the RPC
            # cannot do so, fail loudly so a reconciler can recover by tx hash.
            try:
                resolved = int(contract.functions.getMembershipToken(to).call())
            except Exception as exc:
                raise ChainMintError(
                    "La transacción fue confirmada, pero no se pudo resolver "
                    "su tokenId on-chain; requiere reconciliación."
                ) from exc
            if resolved <= 0:
                raise ChainMintError(
                    "La transacción fue confirmada sin un tokenId on-chain válido; "
                    "requiere reconciliación."
                )
            token_id = resolved

        return tx_hash.hex(), token_id

    except ChainMintError:
        raise
    except Exception as e:
        logger.error(
            "Error minteando on-chain para %s (%s)",
            wallet_address,
            type(e).__name__,
        )
        raise ChainMintError("Fallo interno al enviar o confirmar la transacción") from e
