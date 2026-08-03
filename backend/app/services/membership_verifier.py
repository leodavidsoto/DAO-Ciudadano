"""
Membership Verifier Service

Single source of truth for "is this address an active DAO member?".
Governance endpoints (proposals, votes, delegation, elections) depend on this
check to close audit finding C-3 (zero-cost Sybil voting).

Two implementations behind one interface so switching the source of truth is a
configuration change, not a rewrite:

- MongoMembershipVerifier: checks the `members` collection. Source of truth
  while minting is off-chain (totalSupply() on Sepolia is still 0).
- OnChainMembershipVerifier: calls hasMembership() on the SBT contract
  (ROADMAP 3.1), behind a short-lived cache so a vote does not cost an RPC
  round trip per request.

Selection is driven by settings.MEMBERSHIP_SOURCE ("mongo" | "onchain").

Ninguna de las dos devuelve False cuando la consulta falla: la implementación
on-chain lanza `MembershipVerificationUnavailable` y el llamador responde 503.
"No pude verificar" y "no es miembro" son respuestas distintas y solo una de
ellas justifica un 403.
"""
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Iterable, Optional
import asyncio
import logging
import threading
import time

from ..core.config import settings
from ..core.database import members_collection
from . import chain_service

logger = logging.getLogger(__name__)


class MembershipVerificationUnavailable(RuntimeError):
    """La fuente de verdad no pudo consultarse.

    No implica que la dirección no sea miembro; implica que no lo sabemos.
    """


class MembershipVerifier(ABC):
    """Interface for membership checks used by governance endpoints."""

    @abstractmethod
    async def is_member(self, address: str) -> bool:
        """Return True if `address` holds an active DAO membership."""
        raise NotImplementedError

    @abstractmethod
    async def filter_members(self, addresses: Iterable[str]) -> set[str]:
        """Subset of `addresses` (lowercase) with an active membership.

        Exists so callers that need to check many addresses at once (voting
        weight from delegators) use the SAME definition of membership as the
        single-address gate instead of writing their own weaker query.
        """
        raise NotImplementedError


def _active_member_query() -> dict:
    """Filtro Mongo de una membresía que da derechos de gobernanza."""
    query: dict = {"status": "active"}
    if settings.is_production:
        # Legacy documents have neither field and are therefore quarantined
        # automatically. Demo rows also remain ineligible even if the same
        # MongoDB database is promoted to production.
        query.update({
            "issuance_mode": "onchain",
            "identity_verified": True,
            "tx_hash": {"$type": "string", "$ne": ""},
        })
    return query


class MongoMembershipVerifier(MembershipVerifier):
    """Checks the members collection. Source of truth until on-chain minting exists.

    A member counts as active only when its document has status == "active"
    (revoked memberships must not grant governance rights).
    """

    async def is_member(self, address: str) -> bool:
        if not address:
            return False
        query = _active_member_query()
        query["wallet_address"] = address.lower()
        member = await members_collection().find_one(query)
        return member is not None

    async def filter_members(self, addresses: Iterable[str]) -> set[str]:
        wanted = sorted({a.lower() for a in addresses if a})
        if not wanted:
            return set()
        query = _active_member_query()
        query["wallet_address"] = {"$in": wanted}
        cursor = members_collection().find(query)
        found = await cursor.to_list(length=len(wanted))
        return {m["wallet_address"] for m in found}


def membership_is_onchain(member: dict) -> bool:
    """True only for explicit on-chain provenance with a stored transaction."""
    return member.get("issuance_mode") == "onchain" and bool(member.get("tx_hash"))


def membership_is_valid(member: dict) -> bool:
    """Whether a stored membership is eligible in the current environment.

    Non-production environments retain pilot behavior for active demo rows.
    Production uses the same provenance requirements as the governance gate.
    Missing fields are intentionally treated as legacy/unverified.
    """
    if member.get("status") != "active":
        return False
    if not settings.is_production:
        return True
    return (
        membership_is_onchain(member)
        and member.get("identity_verified") is True
    )


class _MembershipCache:
    """Caché corta de `hasMembership()` por dirección (ROADMAP 3.1).

    El TTL se lee en cada acceso en vez de congelarse al construir la caché:
    así un operador puede bajarlo (o ponerlo en 0) sin reiniciar el proceso.

    La clave incluye contrato y RPC porque son lo que define qué cadena
    respondió; si cambian, las respuestas anteriores dejan de ser válidas.

    Vive en memoria de proceso. Con varias instancias cada una mantiene la
    suya: no hay coherencia entre ellas más allá del TTL, que por eso es corto.
    """

    def __init__(self) -> None:
        self._entries: "OrderedDict[tuple, tuple[float, bool]]" = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(address: str) -> tuple:
        return (
            settings.SBT_CONTRACT_ADDRESS.strip().lower(),
            settings.SEPOLIA_RPC_URL.strip(),
            address.lower(),
        )

    def get(self, key: tuple) -> Optional[bool]:
        ttl = settings.MEMBERSHIP_CACHE_TTL_SECONDS
        if ttl <= 0:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if time.monotonic() - stored_at >= ttl:
                self._entries.pop(key, None)
                return None
            return value

    def set(self, key: tuple, value: bool) -> None:
        if settings.MEMBERSHIP_CACHE_TTL_SECONDS <= 0:
            return
        max_entries = max(1, settings.MEMBERSHIP_CACHE_MAX_ENTRIES)
        with self._lock:
            self._entries[key] = (time.monotonic(), value)
            self._entries.move_to_end(key)
            # Cota dura de memoria: sin esto, una ráfaga de direcciones
            # inventadas haría crecer la caché sin límite.
            while len(self._entries) > max_entries:
                self._entries.popitem(last=False)

    def invalidate(self, address: str) -> None:
        """Olvida una dirección (p.ej. tras mintear su SBT).

        Sin esto, quien acaba de recibir su credencial seguiría viendo 403
        durante el resto del TTL por una respuesta negativa ya cacheada.
        """
        target = address.lower()
        with self._lock:
            for key in [k for k in self._entries if k[2] == target]:
                self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_cache = _MembershipCache()


def invalidate_cached_membership(address: str) -> None:
    """Punto de entrada público para invalidar una dirección."""
    _cache.invalidate(address)


def clear_membership_cache() -> None:
    _cache.clear()


class OnChainMembershipVerifier(MembershipVerifier):
    """Calls hasMembership() on the SBT contract (ROADMAP 3.1).

    El contrato es la única fuente de verdad en este modo: un registro en
    Mongo sin SBT no da derechos, y un SBT vivo los da aunque Mongo no lo
    sepa. Las respuestas se cachean por `MEMBERSHIP_CACHE_TTL_SECONDS` en
    ambos sentidos — también las negativas, porque una dirección sin SBT
    reintentando es exactamente el caso que no debe llegar al RPC.
    """

    async def is_member(self, address: str) -> bool:
        if not address:
            return False
        from eth_utils import is_address

        if not is_address(address):
            # Una dirección malformada no es un fallo de la cadena: no hay
            # nada que consultar y la respuesta correcta es "no es miembro".
            return False

        key = _cache.key(address)
        cached = _cache.get(key)
        if cached is not None:
            return cached

        try:
            # web3 es síncrono: sin el hilo, una consulta lenta bloquearía el
            # event loop y con él todos los demás requests del proceso.
            result = await asyncio.to_thread(chain_service.has_membership, address)
        except chain_service.ChainReadError as exc:
            raise MembershipVerificationUnavailable(str(exc)) from exc

        _cache.set(key, result)
        return result

    async def filter_members(self, addresses: Iterable[str]) -> set[str]:
        wanted = sorted({a.lower() for a in addresses if a})
        if not wanted:
            return set()
        # Secuencial a propósito: son llamadas RPC y el proveedor gratuito
        # limita por segundo. La caché absorbe el caso repetido, que es el
        # habitual cuando el mismo delegado vota varias veces.
        members = set()
        for address in wanted:
            if await self.is_member(address):
                members.add(address)
        return members


def get_membership_verifier() -> MembershipVerifier:
    """Factory: choose the verifier from settings.MEMBERSHIP_SOURCE.

    Defaults to "mongo". Unknown values fail loudly at call time rather
    than silently falling back to a weaker check.
    """
    source = (settings.MEMBERSHIP_SOURCE or "mongo").strip().lower()
    if source == "mongo":
        return MongoMembershipVerifier()
    if source == "onchain":
        return OnChainMembershipVerifier()
    raise ValueError(
        f"Invalid MEMBERSHIP_SOURCE '{settings.MEMBERSHIP_SOURCE}'. "
        "Expected 'mongo' or 'onchain'."
    )
