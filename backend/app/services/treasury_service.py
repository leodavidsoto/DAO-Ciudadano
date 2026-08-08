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

3. **Solo se reporta lo que se consultó.** Se lee el ETH nativo y los ERC-20
   declarados en `TREASURY_TOKENS` — ni uno más. `assets_covered` enumera
   exactamente eso: si el Safe tiene otro token que nadie configuró, no
   aparece y el total no lo incluye. Los decimales y el símbolo se leen de la
   cadena; suponer 18 decimales mostraría el saldo de USDC un billón de veces
   mal.

4. **Un activo sin precio no vale cero.** Si algún activo con saldo no tiene
   precio conocido, `total_usd_value` es `null` con motivo, en vez de publicar
   una suma parcial que haría parecer la tesorería más pequeña de lo que es.

Las llamadas son bloqueantes (web3 y requests son síncronos): los llamadores
las ejecutan con `asyncio.to_thread`.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
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

# ABI mínima: solo lo que se consulta. No se usa la ABI completa de ERC-20
# para que quede explícito que este servicio LEE y nunca transfiere nada.
_ERC20_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
]

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

    # Los tokens se validan aquí y no solo al leer: una dirección con un typo
    # debe verse en /health/ready, no descubrirse cuando el panel deje de
    # mostrar la tesorería.
    declared = [t.strip() for t in settings.TREASURY_TOKENS.split(",") if t.strip()]
    invalid = [t for t in declared if not Web3.is_address(t)]
    if invalid:
        errors["TREASURY_TOKENS"] = "contiene direcciones inválidas: " + ", ".join(
            invalid[:3]
        )
    elif len(declared) > max(0, settings.TREASURY_MAX_TOKENS):
        errors["TREASURY_TOKENS"] = (
            f"declara {len(declared)} tokens y el máximo es "
            f"{settings.TREASURY_MAX_TOKENS}"
        )

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
        logger.error(
            "No se pudo leer el balance de la tesorería (%s)", type(exc).__name__
        )
        raise TreasuryUnavailable(
            "No se pudo consultar el balance on-chain de la tesorería."
        ) from exc

    tokens = read_token_balances(w3, address)

    return {
        "eth": Decimal(wei) / WEI_PER_ETH,
        "wei": wei,
        "chain_id": chain_id,
        "safe_address": address,
        # Un Safe es un contrato. Se reporta en vez de bloquear porque una
        # tesorería puede empezar en una EOA mientras se despliega el Safe;
        # lo que no se puede es callarlo.
        "is_contract": has_code,
        "tokens": tokens,
    }


def token_addresses() -> list[str]:
    """Direcciones ERC-20 configuradas, validadas y sin repetir.

    Una dirección inválida NO se ignora en silencio: eso publicaría un total
    al que le falta un activo sin que nadie se entere. Se rechaza la foto
    entera para que el operador lo arregle.
    """
    from web3 import Web3

    raw = [t.strip() for t in settings.TREASURY_TOKENS.split(",") if t.strip()]
    seen: list[str] = []
    for candidate in raw:
        if not Web3.is_address(candidate):
            raise TreasuryUnavailable(
                f"TREASURY_TOKENS contiene una dirección inválida: {candidate}"
            )
        checksummed = Web3.to_checksum_address(candidate)
        if checksummed not in seen:
            seen.append(checksummed)

    limit = max(0, settings.TREASURY_MAX_TOKENS)
    if len(seen) > limit:
        raise TreasuryUnavailable(
            f"TREASURY_TOKENS declara {len(seen)} tokens y el máximo es {limit}. "
            "Cada token son tres llamadas al RPC en un endpoint público."
        )
    return seen


def read_token_balances(w3, holder: str) -> list[dict]:
    """Balance de cada ERC-20 configurado. Bloqueante.

    Todo o nada: si UN token no se puede leer, se lanza `TreasuryUnavailable`
    y la respuesta entera queda sin balances. Devolver los que sí se leyeron
    daría un total silenciosamente incompleto, que es peor que no dar ninguno.

    `decimals()` se lee de la cadena y jamás se supone 18: USDC tiene 6, y
    asumir 18 mostraría un saldo un billón de veces menor.
    """
    addresses = token_addresses()
    if not addresses:
        return []

    balances = []
    for address in addresses:
        try:
            contract = w3.eth.contract(address=address, abi=_ERC20_ABI)
            raw_balance = int(contract.functions.balanceOf(holder).call())
            decimals = int(contract.functions.decimals().call())
        except Exception as exc:
            logger.error(
                "No se pudo leer el token %s (%s)", address, type(exc).__name__
            )
            raise TreasuryUnavailable(
                f"No se pudo consultar el balance del token {address}."
            ) from exc

        if not 0 <= decimals <= 36:
            raise TreasuryUnavailable(
                f"El token {address} declara {decimals} decimales, fuera de rango."
            )

        # `symbol()` es opcional en la práctica: algunos tokens antiguos lo
        # devuelven como bytes32 y la llamada falla. No es motivo para tirar la
        # lectura del saldo, que es el dato que importa; se etiqueta con la
        # dirección abreviada y se deja constancia de que es una etiqueta
        # nuestra y no lo que declara el contrato.
        try:
            symbol = str(contract.functions.symbol().call()).strip()
            symbol_source = "contract"
        except Exception:
            symbol = ""
            symbol_source = "address"
        if not symbol:
            symbol = f"{address[:6]}…{address[-4:]}"
            symbol_source = "address"

        balances.append(
            {
                "address": address,
                "symbol": symbol,
                "symbol_source": symbol_source,
                "decimals": decimals,
                "raw": raw_balance,
                "amount": Decimal(raw_balance) / (Decimal(10) ** decimals),
            }
        )

    return balances


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


class _TokenPriceCache:
    """Último precio conocido por dirección de token."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict = {}

    def get(self, address: str):
        with self._lock:
            return self._entries.get(address.lower())

    def set(self, address: str, price: Decimal) -> None:
        with self._lock:
            self._entries[address.lower()] = (price, time.time())

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_token_price_cache = _TokenPriceCache()

COINGECKO_TOKEN_PRICE_URL = (
    "https://api.coingecko.com/api/v3/simple/token_price/ethereum"
)


def _fetch_token_prices_usd(addresses: list[str]) -> dict:
    """Precios USD por contrato. Una petición POR TOKEN.

    El plan gratuito de CoinGecko admite **una sola dirección por petición**:
    agrupar varias devuelve 400 (`error_code 10012`). Se descubrió probando
    contra mainnet, no leyendo la documentación.

    Un token que falle no arrastra a los demás: queda sin precio, y el total
    consolidado ya sabe qué hacer con eso. Solo se propaga la excepción si
    fallan TODOS, para que el llamador pueda recurrir a la caché obsoleta.

    Solo CoinGecko: su endpoint indexa por dirección de contrato de mainnet.
    Binance publica pares de su propio mercado, no precios por contrato, así
    que con ese proveedor los tokens quedan sin precio en vez de emparejarlos
    por símbolo — dos tokens distintos pueden llamarse igual, y confundirlos
    falsearía el patrimonio.
    """
    import requests

    prices: dict = {}
    failures = 0
    for address in addresses:
        try:
            response = requests.get(
                COINGECKO_TOKEN_PRICE_URL,
                params={"contract_addresses": address, "vs_currencies": "usd"},
                timeout=5,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning(
                "Sin precio para el token %s (%s)", address, type(exc).__name__
            )
            failures += 1
            continue

        for key, quote in (payload or {}).items():
            raw = (quote or {}).get("usd")
            if raw is None:
                continue
            price = Decimal(str(raw))
            # Misma cota de cordura que el ETH: un feed roto no debe
            # multiplicar un saldo por un número cualquiera.
            if price <= 0 or price > MAX_PLAUSIBLE_ETH_USD:
                continue
            prices[key.lower()] = price

    if failures and not prices:
        raise RuntimeError("ningún precio de token pudo obtenerse")
    return prices


def token_prices_usd(addresses: list[str], chain_id: Optional[int]) -> dict:
    """Precios por token. Nunca lanza: lo que no tenga precio, no lo tiene.

    Devuelve `{direccion_minuscula: Decimal}`. Un token ausente del resultado
    es un token sin precio conocido, y el total consolidado lo tratará como
    tal en vez de contarlo como cero.
    """
    if not addresses:
        return {}

    provider = (settings.ETH_PRICE_PROVIDER or "coingecko").strip().lower()
    if provider != "coingecko":
        return {}
    if chain_id != MAINNET_CHAIN_ID:
        # Mismo motivo que con el ETH nativo: un token de testnet no tiene
        # precio de mercado, y su dirección ni siquiera existe en mainnet.
        return {}

    ttl = max(0, settings.ETH_PRICE_CACHE_TTL_SECONDS)
    now = time.time()
    resolved: dict = {}
    missing: list[str] = []
    for address in addresses:
        entry = _token_price_cache.get(address)
        if entry and now - entry[1] < ttl:
            resolved[address.lower()] = entry[0]
        else:
            missing.append(address)

    if not missing:
        return resolved

    try:
        fetched = _fetch_token_prices_usd(missing)
    except Exception as exc:
        logger.warning(
            "No se pudieron obtener precios de tokens (%s)", type(exc).__name__
        )
        # Degradación marcada, igual que con el ETH: se sirve lo último
        # conocido dentro de la ventana de obsolescencia admitida.
        stale_window = max(0, settings.ETH_PRICE_STALE_MAX_SECONDS)
        for address in missing:
            entry = _token_price_cache.get(address)
            if entry and now - entry[1] < stale_window:
                resolved[address.lower()] = entry[0]
        return resolved

    for address, price in fetched.items():
        _token_price_cache.set(address, price)
        resolved[address] = price
    return resolved


def eth_price_usd(chain_id: Optional[int] = None) -> PriceQuote:
    """Precio de ETH en USD. Bloqueante. Nunca lanza: informa por qué falta.

    `chain_id` decide si tiene sentido siquiera preguntarlo: el ETH de una
    testnet no tiene precio de mercado y no se le inventa uno.
    """
    provider = (settings.ETH_PRICE_PROVIDER or "coingecko").strip().lower()
    if provider in {"", "none", "disabled"}:
        return PriceQuote(
            None, provider or "none", None, False, "proveedor deshabilitado"
        )

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
            return PriceQuote(
                cached, provider, cached_at, True, "usando el último precio conocido"
            )
        return PriceQuote(
            None, provider, None, False, "el proveedor de precio no respondió"
        )

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
            "total_usd_unavailable_reason": None,
            # No se consultó nada, así que no se cubrió nada. Decir ["ETH"]
            # aquí insinuaría una lectura que no ocurrió.
            "assets_covered": [],
            "assets": [],
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
            "total_usd_unavailable_reason": None,
            "assets_covered": [],
            "assets": [],
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
    tokens = balance["tokens"]
    prices = token_prices_usd([t["address"] for t in tokens], balance["chain_id"])

    # Un activo cuenta para el total solo si tiene precio. Los que no lo
    # tienen no valen cero: valen "no lo sabemos", y esa diferencia decide si
    # el total consolidado se puede publicar.
    assets: list[dict[str, Any]] = [
        {
            "symbol": "ETH",
            "address": None,
            "decimals": 18,
            "amount": float(eth_amount),
            "usd_price": float(quote.usd) if quote.usd is not None else None,
            "usd_value": (
                float(eth_amount * quote.usd) if quote.usd is not None else None
            ),
        }
    ]
    for token in tokens:
        price = prices.get(token["address"].lower())
        assets.append(
            {
                "symbol": token["symbol"],
                "symbol_source": token["symbol_source"],
                "address": token["address"].lower(),
                "decimals": token["decimals"],
                "amount": float(token["amount"]),
                "usd_price": float(price) if price is not None else None,
                "usd_value": (
                    float(token["amount"] * price) if price is not None else None
                ),
            }
        )

    # Solo estorba para el total un activo SIN precio y CON saldo: si el saldo
    # es cero, aporta cero valor lo valga lo que valga.
    unpriced = [
        a["symbol"] for a in assets if a["usd_price"] is None and a["amount"] > 0
    ]
    if unpriced:
        total_usd = None
        total_usd_reason = (
            "no hay precio para "
            + ", ".join(unpriced)
            + "; publicar un total que los ignora daría una tesorería más "
            "pequeña de lo que es"
        )
    else:
        total_usd = float(sum(Decimal(str(a["usd_value"] or 0)) for a in assets))
        total_usd_reason = None

    balances = {"ETH": float(eth_amount)}
    for token in tokens:
        symbol = token["symbol"]
        # Dos tokens pueden declarar el mismo símbolo. Machacar la clave
        # perdería un saldo en silencio, así que se desambigua.
        if symbol in balances:
            symbol = f"{symbol} ({token['address'][:6]}…)"
        balances[symbol] = float(token["amount"])

    return {
        "configured": True,
        "balances": balances,
        # Sigue siendo el ETH NATIVO, no el patrimonio convertido a ETH: es lo
        # que el panel muestra junto al total en dólares.
        "total_eth_value": float(eth_amount),
        "total_usd_value": total_usd,
        "total_usd_unavailable_reason": total_usd_reason,
        # Exactamente lo que se consultó, ni más ni menos: si el Safe tuviera
        # otro token no declarado en TREASURY_TOKENS, no está aquí y el total
        # no lo incluye.
        "assets_covered": list(balances),
        "assets": assets,
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
