"""
Tesorería real (ROADMAP 3.6).

Antes: `/governance/treasury` devolvía `configured: false` con balances `null`.
Era honesto, pero no era un dato: no había ninguna fuente conectada.

Ahora: el balance sale de `eth_getBalance` sobre la dirección del Safe
(`TREASURY_SAFE_ADDRESS`) y el precio de ETH de una API pública configurable.
Ninguno de los dos números vive en el código.

Tres reglas que este módulo no rompe
────────────────────────────────────

1. **ETH de testnet no vale dólares.** Si la cadena configurada no es mainnet,
   `total_usd_value` es `null` con motivo explícito. Convertir ETH de Sepolia a
   USD sería exactamente el "1432 miembros falsos" de la tesorería: un número
   con formato de dinero que no representa nada.

2. **Un fallo de lectura no es un balance de cero.** Si el RPC no responde, la
   respuesta dice que no se pudo leer; nunca devuelve 0.

3. **Solo se reporta lo que se sabe.** Este servicio lee ETH nativo. Los
   tokens ERC-20 que pueda tener el Safe NO se leen todavía, y por eso la
   respuesta declara `assets_covered: ["ETH"]` en vez de dejar creer que el
   total incluye todo lo que hay dentro.

Las llamadas son bloqueantes (web3 y requests son síncronos): los llamadores
las ejecutan con `asyncio.to_thread`.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from urllib.parse import urlparse
import logging
import threading
import time

from ..core.config import settings

logger = logging.getLogger(__name__)

MAINNET_CHAIN_ID = 1
WEI_PER_ETH = Decimal(10) ** 18

# Cota de cordura del feed externo: un precio fuera de este rango es un error
# del proveedor (o un formato cambiado), no una noticia de mercado. Preferimos
# no publicar precio a publicar uno absurdo multiplicado por el balance.
MIN_PLAUSIBLE_ETH_USD = Decimal("1")
MAX_PLAUSIBLE_ETH_USD = Decimal("1000000")

_PRICE_PROVIDERS = {
    "coingecko": (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=ethereum&vs_currencies=usd"
    ),
    "binance": "https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT",
}


class TreasuryUnavailable(RuntimeError):
    """No se pudo leer el balance. Distinto de "el balance es cero"."""


@dataclass(frozen=True)
class PriceQuote:
    usd: Optional[Decimal]
    source: str
    as_of: Optional[float]
    stale: bool
    unavailable_reason: Optional[str] = None


def rpc_url() -> str:
    """RPC de la tesorería; cae al de minteo si no se declara uno propio."""
    return (settings.TREASURY_RPC_URL or settings.SEPOLIA_RPC_URL).strip()


def configuration_errors() -> dict[str, str]:
    """Valida la configuración sin tocar la red."""
    from web3 import Web3

    errors: dict[str, str] = {}

    address = settings.TREASURY_SAFE_ADDRESS.strip()
    if not address:
        errors["TREASURY_SAFE_ADDRESS"] = "falta"
    elif not Web3.is_address(address):
        errors["TREASURY_SAFE_ADDRESS"] = "debe ser una dirección Ethereum válida"

    url = rpc_url()
    parsed = urlparse(url)
    if not url:
        errors["TREASURY_RPC_URL"] = "falta"
    elif parsed.scheme not in {"http", "https"} or not parsed.netloc:
        errors["TREASURY_RPC_URL"] = "debe ser una URL HTTP(S) válida"
    elif settings.is_production and parsed.scheme != "https":
        errors["TREASURY_RPC_URL"] = "debe usar HTTPS en producción"

    return errors


def is_configured() -> bool:
    return not configuration_errors()


def read_balance() -> dict:
    """Balance nativo del Safe leído del RPC. Bloqueante.

    Devuelve `{"eth": Decimal, "chain_id": int, "safe_address": str}` o lanza
    `TreasuryUnavailable`. Se comprueba además que la dirección tenga código:
    un Safe es un contrato, y apuntar sin querer a una EOA (o a una dirección
    con un typo) daría un balance real de la wallet equivocada.
    """
    from web3 import Web3

    if not is_configured():
        raise TreasuryUnavailable(
            "La tesorería no está configurada: faltan TREASURY_SAFE_ADDRESS "
            "o un RPC válido."
        )

    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url(), request_kwargs={"timeout": 10}))
        address = Web3.to_checksum_address(settings.TREASURY_SAFE_ADDRESS.strip())
        chain_id = int(w3.eth.chain_id)
        has_code = bool(w3.eth.get_code(address))
        wei = int(w3.eth.get_balance(address))
    except Exception as exc:
        # Sin el texto del error: la URL del RPC puede llevar una API key.
        logger.error("No se pudo leer el balance de la tesorería (%s)", type(exc).__name__)
        raise TreasuryUnavailable(
            "No se pudo consultar el balance on-chain de la tesorería."
        ) from exc

    return {
        "eth": Decimal(wei) / WEI_PER_ETH,
        "wei": wei,
        "chain_id": chain_id,
        "safe_address": address,
        # Un Safe es un contrato. Se reporta en vez de bloquear porque una
        # tesorería puede empezar en una EOA mientras se despliega el Safe;
        # lo que no se puede es callarlo.
        "is_contract": has_code,
    }


def _fetch_price_usd() -> Decimal:
    """Consulta el proveedor configurado. Lanza si no se puede obtener.

    Usa `requests` (dependencia dura de web3, ya instalada) en vez de añadir
    otro cliente HTTP a producción: `requirements.txt` está mínimo a propósito.
    """
    import requests

    provider = (settings.ETH_PRICE_PROVIDER or "coingecko").strip().lower()
    url = settings.ETH_PRICE_API_URL.strip() or _PRICE_PROVIDERS.get(provider)
    if not url:
        raise ValueError(f"Proveedor de precio desconocido: {provider}")

    response = requests.get(url, timeout=5, headers={"Accept": "application/json"})
    response.raise_for_status()
    payload = response.json()

    if provider == "coingecko":
        raw = payload["ethereum"]["usd"]
    elif provider == "binance":
        raw = payload["price"]
    else:
        raw = payload

    price = Decimal(str(raw))
    if not (MIN_PLAUSIBLE_ETH_USD <= price <= MAX_PLAUSIBLE_ETH_USD):
        raise ValueError(f"Precio fuera de rango plausible: {price}")
    return price


class _PriceCache:
    """Último precio conocido, con su antigüedad.

    Se sirve un valor viejo marcado como `stale` antes que ninguno: las APIs
    públicas gratuitas limitan por minuto y un 429 momentáneo no debería
    borrar el valor de la tesorería de la pantalla. Pasado
    `ETH_PRICE_STALE_MAX_SECONDS` deja de servirse: un precio de ayer sí sería
    engañoso.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._price: Optional[Decimal] = None
        self._at: Optional[float] = None

    def get(self) -> tuple[Optional[Decimal], Optional[float]]:
        with self._lock:
            return self._price, self._at

    def set(self, price: Decimal) -> None:
        with self._lock:
            self._price = price
            self._at = time.time()

    def clear(self) -> None:
        with self._lock:
            self._price = None
            self._at = None


_price_cache = _PriceCache()


def eth_price_usd(chain_id: Optional[int] = None) -> PriceQuote:
    """Precio de ETH en USD. Bloqueante. Nunca lanza: informa por qué falta.

    `chain_id` decide si tiene sentido siquiera preguntarlo: el ETH de una
    testnet no tiene precio de mercado y no se le inventa uno.
    """
    provider = (settings.ETH_PRICE_PROVIDER or "coingecko").strip().lower()
    if provider in {"", "none", "disabled"}:
        return PriceQuote(None, provider or "none", None, False, "proveedor deshabilitado")

    if chain_id is not None and chain_id != MAINNET_CHAIN_ID:
        return PriceQuote(
            None,
            provider,
            None,
            False,
            f"la red {chain_id} no es mainnet: su ETH no tiene precio de mercado",
        )

    cached, cached_at = _price_cache.get()
    now = time.time()
    if cached is not None and cached_at is not None:
        if now - cached_at < max(0, settings.ETH_PRICE_CACHE_TTL_SECONDS):
            return PriceQuote(cached, provider, cached_at, False)

    try:
        price = _fetch_price_usd()
    except Exception as exc:
        logger.warning("No se pudo obtener el precio de ETH (%s)", type(exc).__name__)
        if (
            cached is not None
            and cached_at is not None
            and now - cached_at < max(0, settings.ETH_PRICE_STALE_MAX_SECONDS)
        ):
            return PriceQuote(cached, provider, cached_at, True, "usando el último precio conocido")
        return PriceQuote(None, provider, None, False, "el proveedor de precio no respondió")

    _price_cache.set(price)
    return PriceQuote(price, provider, time.time(), False)


def _iso(timestamp: Optional[float]) -> Optional[str]:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def build_snapshot() -> dict:
    """Foto completa de la tesorería. Bloqueante; llamar en un hilo.

    Nunca lanza: un fallo se refleja en la respuesta (`error`) para que el
    cliente distinga "no configurada", "no se pudo leer" y "cero".
    """
    errors = configuration_errors()
    if errors:
        return {
            "configured": False,
            "balances": None,
            "total_eth_value": None,
            "total_usd_value": None,
            "assets_covered": ["ETH"],
            "source": None,
            "price": None,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "error": "; ".join(f"{k}: {v}" for k, v in errors.items()),
        }

    try:
        balance = read_balance()
    except TreasuryUnavailable as exc:
        return {
            # Configurada sí está; lo que falló es la lectura. Un cliente que
            # vea `configured: true` con `balances: null` sabe que hay una
            # fuente y que ahora mismo no responde.
            "configured": True,
            "balances": None,
            "total_eth_value": None,
            "total_usd_value": None,
            "assets_covered": ["ETH"],
            "source": {
                "safe_address": settings.TREASURY_SAFE_ADDRESS.strip().lower(),
                "chain_id": None,
                "provider": "rpc",
            },
            "price": None,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }

    quote = eth_price_usd(balance["chain_id"])
    eth_amount = balance["eth"]
    total_usd = float(eth_amount * quote.usd) if quote.usd is not None else None

    return {
        "configured": True,
        "balances": {"ETH": float(eth_amount)},
        "total_eth_value": float(eth_amount),
        "total_usd_value": total_usd,
        # Declarar el alcance evita que el total se lea como "todo lo que hay
        # en el Safe": los ERC-20 todavía no se consultan (ROADMAP 3.6b).
        "assets_covered": ["ETH"],
        "source": {
            "safe_address": balance["safe_address"].lower(),
            "chain_id": balance["chain_id"],
            "provider": "rpc",
            "is_contract": balance["is_contract"],
        },
        "price": {
            "eth_usd": float(quote.usd) if quote.usd is not None else None,
            "source": quote.source,
            "as_of": _iso(quote.as_of),
            "stale": quote.stale,
            "unavailable_reason": quote.unavailable_reason,
        },
        "as_of": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }


class _SnapshotCache:
    """Caché corta de la foto completa.

    `/governance/treasury` es público y sin autenticar: sin esto, refrescar el
    dashboard en bucle convierte a cualquier visitante en un amplificador de
    tráfico contra el RPC y contra la API de precios.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: Optional[dict] = None
        self._at: float = 0.0

    def get(self) -> Optional[dict]:
        ttl = max(0, settings.TREASURY_CACHE_TTL_SECONDS)
        if ttl <= 0:
            return None
        with self._lock:
            if self._value is None or time.monotonic() - self._at >= ttl:
                return None
            return dict(self._value)

    def set(self, value: dict) -> None:
        with self._lock:
            self._value = dict(value)
            self._at = time.monotonic()

    def clear(self) -> None:
        with self._lock:
            self._value = None
            self._at = 0.0


_snapshot_cache = _SnapshotCache()


def clear_caches() -> None:
    """Usado por los tests y por quien cambie la configuración en caliente."""
    _snapshot_cache.clear()
    _price_cache.clear()


async def snapshot() -> dict:
    """Foto de la tesorería, cacheada, sin bloquear el event loop."""
    import asyncio

    cached = _snapshot_cache.get()
    if cached is not None:
        return cached

    value = await asyncio.to_thread(build_snapshot)
    _snapshot_cache.set(value)
    return value
