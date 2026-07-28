"""
On-chain minting (ROADMAP 1.5, audit finding C-2).

Until now `mint_sbt` wrote a document to MongoDB and the UI showed "MINTEANDO
SBT" with confetti. `totalSupply()` on Sepolia stayed at 0: nothing had ever
touched the chain. This module is what makes that claim true.

Custody model (ADR 0001, decision D-1): the backend holds a key with
MINTER_ROLE only. A leak lets an attacker issue memberships, but not revoke,
pause or grant roles — those need ADMIN_ROLE, held by a multisig.

Configuration is deliberately fail-closed: without an RPC endpoint, a contract
address and a minter key, minting is DISABLED rather than silently falling
back to a database write. A fake success is worse than an honest failure.
"""
import logging
from typing import Optional

from ..core.config import settings

logger = logging.getLogger(__name__)

# Only what the backend calls. The frontend has the full generated ABI.
MINT_ABI = [
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
        "name": "hasMembership",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "identityHash", "type": "bytes32"}],
        "name": "isIdentityUsed",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "totalSupply",
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
]

RECEIPT_TIMEOUT_S = 180


class ChainNotConfigured(RuntimeError):
    """Raised when on-chain minting is requested without configuration."""


class ChainService:
    """Thin wrapper over web3 for the operations the backend performs."""

    def __init__(self):
        self._w3 = None
        self._contract = None
        self._account = None

    # === Configuration ===

    @property
    def enabled(self) -> bool:
        """True when every piece needed to mint on-chain is configured."""
        return bool(
            settings.SEPOLIA_RPC_URL
            and settings.SBT_CONTRACT_ADDRESS
            and settings.MINTER_PRIVATE_KEY
        )

    def _connect(self):
        if self._w3 is not None:
            return

        if not self.enabled:
            raise ChainNotConfigured(
                "El minteo on-chain no está configurado (faltan SEPOLIA_RPC_URL, "
                "SBT_CONTRACT_ADDRESS o MINTER_PRIVATE_KEY)."
            )

        from eth_account import Account
        from web3 import Web3

        self._w3 = Web3(Web3.HTTPProvider(settings.SEPOLIA_RPC_URL))
        self._account = Account.from_key(settings.MINTER_PRIVATE_KEY)
        self._contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(settings.SBT_CONTRACT_ADDRESS),
            abi=MINT_ABI,
        )
        logger.info(f"Chain service ready; minter {self._account.address}")

    # === Reads ===

    def has_membership(self, address: str) -> bool:
        self._connect()
        from web3 import Web3
        return self._contract.functions.hasMembership(
            Web3.to_checksum_address(address)
        ).call()

    def is_identity_used(self, identity_hash_hex: str) -> bool:
        self._connect()
        return self._contract.functions.isIdentityUsed(
            bytes.fromhex(identity_hash_hex.removeprefix("0x"))
        ).call()

    def total_supply(self) -> int:
        self._connect()
        return self._contract.functions.totalSupply().call()

    # === Write ===

    def mint(
        self,
        to: str,
        identity_hash_hex: str,
        assurance_level: str,
        token_uri: str = "",
    ) -> tuple[Optional[int], Optional[str]]:
        """Mint a membership. Returns (token_id, tx_hash).

        Blocking on purpose: the caller runs it in a thread. Returning before
        the receipt would mean reporting success for a transaction that can
        still revert, which is the class of lie this whole change removes.
        """
        self._connect()
        from web3 import Web3

        to_checksum = Web3.to_checksum_address(to)
        identity_bytes = bytes.fromhex(identity_hash_hex.removeprefix("0x"))
        if len(identity_bytes) != 32:
            raise ValueError("identityHash debe ser de 32 bytes")

        nonce = self._w3.eth.get_transaction_count(self._account.address)
        function = self._contract.functions.mintMembership(
            to_checksum, identity_bytes, assurance_level, token_uri
        )

        # estimate_gas reverts here if the mint would fail (already a member,
        # identity already used, contract paused), so we find out before
        # spending gas instead of after.
        gas = function.estimate_gas({"from": self._account.address})

        tx = function.build_transaction({
            "from": self._account.address,
            "nonce": nonce,
            "gas": int(gas * 1.2),
            **self._fee_params(),
        })

        signed = self._account.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        logger.info(f"Mint transaction sent: {tx_hash.hex()}")

        receipt = self._w3.eth.wait_for_transaction_receipt(
            tx_hash, timeout=RECEIPT_TIMEOUT_S
        )
        if receipt["status"] != 1:
            raise RuntimeError(f"La transacción revirtió: {tx_hash.hex()}")

        token_id = self._token_id_from(receipt)
        return (token_id, tx_hash.hex())

    def _fee_params(self) -> dict:
        """EIP-1559 where available, legacy pricing otherwise."""
        try:
            base = self._w3.eth.get_block("latest")["baseFeePerGas"]
            priority = self._w3.eth.max_priority_fee
            return {
                "maxFeePerGas": base * 2 + priority,
                "maxPriorityFeePerGas": priority,
            }
        except Exception:
            return {"gasPrice": self._w3.eth.gas_price}

    def _token_id_from(self, receipt) -> Optional[int]:
        """Read tokenId from the MembershipMinted event.

        Parsed from the receipt rather than from the function's return value:
        `mintMembership` returns a uint256, but a return value from a state-
        changing call is not available to an external caller — only events are.
        """
        try:
            events = self._contract.events.MembershipMinted().process_receipt(receipt)
            if events:
                return int(events[0]["args"]["tokenId"])
        except Exception as e:
            logger.error(f"Could not read tokenId from the receipt: {e}")
        return None


chain_service = ChainService()
