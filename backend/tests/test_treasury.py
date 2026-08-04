"""
Tesorería real (ROADMAP 3.6): balance del Safe por RPC y precio de ETH por API.

Ningún test toca la red: el proveedor RPC de web3 y la llamada HTTP de precio
se sustituyen por dobles. Lo que se comprueba es justo lo que distingue un
dato real de un número inventado:

* los tres estados (sin configurar / no se pudo leer / leído) son distintos,
* un fallo del RPC no se convierte en un balance de 0,
* el ETH de testnet NO se convierte a USD,
* y ningún número de la respuesta está escrito en el código.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.core.database import treasury_transactions_collection
from app.services import treasury_service

SAFE = "0x" + "5a" * 20
MAINNET = 1
SEPOLIA = 11155111


@pytest.fixture(autouse=True)
def _clean_caches():
    treasury_service.clear_caches()
    yield
    treasury_service.clear_caches()


def _configure(monkeypatch, chain_id=MAINNET, wei=None, code=b"\x60\x60", fail=False,
               tokens=None, token_fails=False):
    """Sustituye la cadena por un doble y devuelve el balance esperado.

    `tokens` es {direccion: (symbol, decimals, raw_balance)}; se declara
    además en TREASURY_TOKENS para que el servicio los consulte.
    """
    monkeypatch.setattr(settings, "TREASURY_SAFE_ADDRESS", SAFE)
    monkeypatch.setattr(settings, "TREASURY_RPC_URL", "https://rpc.example/treasury")
    monkeypatch.setattr(settings, "TREASURY_TOKENS", ",".join(tokens or {}))
    wei = 2_500_000_000_000_000_000 if wei is None else wei  # 2.5 ETH

    class _Call:
        def __init__(self, value):
            self._value = value

        def call(self):
            if token_fails:
                raise ConnectionError("el nodo no respondió a la llamada del token")
            if isinstance(self._value, Exception):
                raise self._value
            return self._value

    class _TokenFunctions:
        def __init__(self, symbol, decimals, balance):
            self._symbol = symbol
            self._decimals = decimals
            self._balance = balance

        def balanceOf(self, holder):
            return _Call(self._balance)

        def decimals(self):
            return _Call(self._decimals)

        def symbol(self):
            return _Call(self._symbol)

    class _Contract:
        def __init__(self, functions):
            self.functions = functions

    class _Eth:
        chain_id = None

        def get_balance(self, address):
            return wei

        def get_code(self, address):
            return code

        def contract(self, address=None, abi=None):
            symbol, decimals, balance = (tokens or {})[address.lower()]
            return _Contract(_TokenFunctions(symbol, decimals, balance))

    class _Web3Double:
        def __init__(self):
            self.eth = _Eth()
            self.eth.chain_id = chain_id

    real_web3 = __import__("web3").Web3

    def _fake_web3(provider):
        if fail:
            raise ConnectionError("RPC caído")
        return _Web3Double()

    monkeypatch.setattr("web3.Web3.__new__", lambda cls, *a, **kw: _fake_web3(None))
    monkeypatch.setattr("web3.Web3.__init__", lambda self, *a, **kw: None)
    # `is_address` y `to_checksum_address` siguen siendo los reales: validan la
    # dirección de verdad, que es la mitad del valor de este servicio.
    monkeypatch.setattr("web3.Web3.is_address", staticmethod(real_web3.is_address))
    monkeypatch.setattr(
        "web3.Web3.to_checksum_address", staticmethod(real_web3.to_checksum_address)
    )
    return Decimal(wei) / treasury_service.WEI_PER_ETH


def _price(monkeypatch, value="2000.55", provider="coingecko"):
    monkeypatch.setattr(settings, "ETH_PRICE_PROVIDER", provider)
    monkeypatch.setattr(
        treasury_service, "_fetch_price_usd", lambda: Decimal(value)
    )


# === Estados de la respuesta ===

async def test_unconfigured_treasury_is_reported_not_faked(client):
    response = await client.get("/api/governance/treasury")
    body = response.json()

    assert body["configured"] is False
    assert body["balances"] is None
    assert body["total_usd_value"] is None
    assert "TREASURY_SAFE_ADDRESS" in body["error"]


async def test_configured_treasury_reports_the_real_balance(client, monkeypatch):
    expected = _configure(monkeypatch, chain_id=MAINNET)
    _price(monkeypatch, "2000")

    body = (await client.get("/api/governance/treasury")).json()

    assert body["configured"] is True
    assert body["balances"] == {"ETH": float(expected)}
    assert body["total_eth_value"] == float(expected)
    assert body["total_usd_value"] == pytest.approx(float(expected) * 2000)
    assert body["source"]["chain_id"] == MAINNET
    assert body["source"]["safe_address"] == SAFE
    assert body["price"]["eth_usd"] == 2000
    assert body["price"]["stale"] is False


async def test_rpc_failure_is_not_a_zero_balance(client, monkeypatch):
    _configure(monkeypatch, fail=True)

    body = (await client.get("/api/governance/treasury")).json()

    # Configurada sí está: lo que falló fue la lectura, y hay que poder
    # distinguirlo de una tesorería vacía.
    assert body["configured"] is True
    assert body["balances"] is None
    assert body["total_eth_value"] is None
    assert body["error"]


async def test_an_empty_treasury_is_zero_not_null(client, monkeypatch):
    _configure(monkeypatch, wei=0)
    _price(monkeypatch, "2000")

    body = (await client.get("/api/governance/treasury")).json()

    assert body["configured"] is True
    assert body["balances"] == {"ETH": 0.0}
    assert body["total_usd_value"] == 0.0


# === El ETH de testnet no vale dólares ===

async def test_testnet_eth_is_never_priced_in_usd(client, monkeypatch):
    expected = _configure(monkeypatch, chain_id=SEPOLIA)
    _price(monkeypatch, "2000")

    body = (await client.get("/api/governance/treasury")).json()

    assert body["total_eth_value"] == float(expected)  # el balance sí es real
    assert body["total_usd_value"] is None
    assert "mainnet" in body["price"]["unavailable_reason"]


async def test_price_provider_can_be_disabled_without_losing_the_balance(
    client, monkeypatch
):
    expected = _configure(monkeypatch, chain_id=MAINNET)
    monkeypatch.setattr(settings, "ETH_PRICE_PROVIDER", "none")

    body = (await client.get("/api/governance/treasury")).json()

    assert body["total_eth_value"] == float(expected)
    assert body["total_usd_value"] is None


# === Precio: caché, degradación y cordura ===

def test_price_is_cached_between_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "ETH_PRICE_PROVIDER", "coingecko")
    monkeypatch.setattr(settings, "ETH_PRICE_CACHE_TTL_SECONDS", 300)

    def _counted():
        calls.append(1)
        return Decimal("1800")

    monkeypatch.setattr(treasury_service, "_fetch_price_usd", _counted)

    first = treasury_service.eth_price_usd(MAINNET)
    second = treasury_service.eth_price_usd(MAINNET)

    assert first.usd == second.usd == Decimal("1800")
    assert len(calls) == 1


def test_a_failing_provider_serves_the_last_price_marked_stale(monkeypatch):
    monkeypatch.setattr(settings, "ETH_PRICE_PROVIDER", "coingecko")
    monkeypatch.setattr(settings, "ETH_PRICE_CACHE_TTL_SECONDS", 0)
    monkeypatch.setattr(settings, "ETH_PRICE_STALE_MAX_SECONDS", 3600)
    monkeypatch.setattr(treasury_service, "_fetch_price_usd", lambda: Decimal("1800"))
    treasury_service.eth_price_usd(MAINNET)

    def _down():
        raise ConnectionError("429")

    monkeypatch.setattr(treasury_service, "_fetch_price_usd", _down)
    quote = treasury_service.eth_price_usd(MAINNET)

    assert quote.usd == Decimal("1800")
    assert quote.stale is True


def test_a_price_too_old_is_dropped_instead_of_shown(monkeypatch):
    monkeypatch.setattr(settings, "ETH_PRICE_PROVIDER", "coingecko")
    monkeypatch.setattr(settings, "ETH_PRICE_CACHE_TTL_SECONDS", 0)
    monkeypatch.setattr(settings, "ETH_PRICE_STALE_MAX_SECONDS", 0)
    monkeypatch.setattr(treasury_service, "_fetch_price_usd", lambda: Decimal("1800"))
    treasury_service.eth_price_usd(MAINNET)

    def _down():
        raise ConnectionError("429")

    monkeypatch.setattr(treasury_service, "_fetch_price_usd", _down)
    quote = treasury_service.eth_price_usd(MAINNET)

    assert quote.usd is None
    assert quote.unavailable_reason


@pytest.mark.parametrize("absurd", ["0", "-5", "99999999"])
def test_implausible_prices_are_rejected(monkeypatch, absurd):
    """Un feed roto no debe multiplicar el balance por un número cualquiera."""
    import requests

    class _Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"ethereum": {"usd": absurd}}

    monkeypatch.setattr(settings, "ETH_PRICE_PROVIDER", "coingecko")
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _Response())

    with pytest.raises(ValueError):
        treasury_service._fetch_price_usd()


def test_binance_payload_is_parsed(monkeypatch):
    import requests

    class _Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"symbol": "ETHUSDT", "price": "1950.42"}

    monkeypatch.setattr(settings, "ETH_PRICE_PROVIDER", "binance")
    monkeypatch.setattr(settings, "ETH_PRICE_API_URL", "")
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _Response())

    assert treasury_service._fetch_price_usd() == Decimal("1950.42")


# === Caché del snapshot ===

async def test_snapshot_is_cached_so_the_public_endpoint_cannot_amplify(
    client, monkeypatch
):
    _configure(monkeypatch, chain_id=MAINNET)
    _price(monkeypatch, "2000")
    monkeypatch.setattr(settings, "TREASURY_CACHE_TTL_SECONDS", 60)
    reads = []
    real_read = treasury_service.read_balance

    def _counted():
        reads.append(1)
        return real_read()

    monkeypatch.setattr(treasury_service, "read_balance", _counted)

    for _ in range(4):
        await client.get("/api/governance/treasury")

    assert len(reads) == 1


# === Runway ===

async def _expense(days_ago: float, amount: float, currency: str = "ETH"):
    await treasury_transactions_collection().insert_one({
        "id": f"tx-{days_ago}-{amount}",
        "type": "expense",
        "amount": amount,
        "currency": currency,
        "description": "Gasto de prueba",
        "category": "operations",
        "timestamp": datetime.now(timezone.utc) - timedelta(days=days_ago),
    })


async def test_runway_is_computed_from_the_real_balance(client, monkeypatch):
    _configure(monkeypatch, wei=10_000_000_000_000_000_000)  # 10 ETH
    _price(monkeypatch, "2000")
    # 2 ETH gastados a lo largo de 60 días -> 1 ETH/mes -> 10 meses.
    await _expense(60, 1.0)
    await _expense(0, 1.0)

    analytics = (await client.get("/api/governance/treasury/analytics")).json()

    assert analytics["runway_months"] == pytest.approx(10.0, rel=0.05)
    assert analytics["runway_unavailable_reason"] is None


async def test_runway_is_null_without_expenses(client, monkeypatch):
    _configure(monkeypatch)
    _price(monkeypatch, "2000")

    analytics = (await client.get("/api/governance/treasury/analytics")).json()

    assert analytics["runway_months"] is None
    assert "gastos" in analytics["runway_unavailable_reason"]


async def test_runway_is_null_without_a_balance_source(client):
    await _expense(30, 1.0)

    analytics = (await client.get("/api/governance/treasury/analytics")).json()

    assert analytics["runway_months"] is None
    assert "balance" in analytics["runway_unavailable_reason"]


async def test_mixed_currencies_do_not_get_an_invented_conversion(client, monkeypatch):
    _configure(monkeypatch)
    _price(monkeypatch, "2000")
    await _expense(30, 1.0, currency="ETH")
    await _expense(10, 500.0, currency="USDC")

    analytics = (await client.get("/api/governance/treasury/analytics")).json()

    assert analytics["runway_months"] is None
    assert "USDC" in analytics["runway_unavailable_reason"]


# === Balances ERC-20 (ROADMAP 3.6b) ===

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"


def _token_prices(monkeypatch, **by_address):
    """Sustituye la consulta de precios por contrato."""
    monkeypatch.setattr(
        treasury_service,
        "_fetch_token_prices_usd",
        lambda addresses: {
            a.lower(): Decimal(str(p)) for a, p in by_address.items()
        },
    )


async def test_token_balances_are_read_with_their_real_decimals(client, monkeypatch):
    """USDC tiene 6 decimales: suponer 18 mostraría un billón de veces menos."""
    _configure(monkeypatch, tokens={USDC: ("USDC", 6, 1_500_000_000)})  # 1.500 USDC
    _price(monkeypatch, "2000")
    _token_prices(monkeypatch, **{USDC: "1.0"})

    body = (await client.get("/api/governance/treasury")).json()

    assert body["balances"]["USDC"] == 1500.0
    assert body["assets_covered"] == ["ETH", "USDC"]
    usdc = next(a for a in body["assets"] if a["symbol"] == "USDC")
    assert usdc["decimals"] == 6
    assert usdc["address"] == USDC


async def test_the_usd_total_consolidates_every_priced_asset(client, monkeypatch):
    expected_eth = _configure(monkeypatch, tokens={USDC: ("USDC", 6, 1_000_000_000)})
    _price(monkeypatch, "2000")
    _token_prices(monkeypatch, **{USDC: "1.0"})

    body = (await client.get("/api/governance/treasury")).json()

    # 2,5 ETH x 2000 + 1000 USDC x 1
    assert body["total_usd_value"] == pytest.approx(float(expected_eth) * 2000 + 1000)
    assert body["total_usd_unavailable_reason"] is None
    # total_eth_value sigue siendo el ETH nativo, no el patrimonio convertido.
    assert body["total_eth_value"] == float(expected_eth)


async def test_an_unpriced_token_voids_the_total_instead_of_counting_zero(
    client, monkeypatch
):
    """El fallo tentador: sumar solo lo que tiene precio y llamarlo total."""
    _configure(monkeypatch, tokens={DAI: ("DAI", 18, 500 * 10**18)})
    _price(monkeypatch, "2000")
    _token_prices(monkeypatch)  # ningún precio para DAI

    body = (await client.get("/api/governance/treasury")).json()

    assert body["balances"]["DAI"] == 500.0  # el saldo sí se conoce
    assert body["total_usd_value"] is None
    assert "DAI" in body["total_usd_unavailable_reason"]


async def test_an_unpriced_token_with_zero_balance_does_not_void_the_total(
    client, monkeypatch
):
    """Un saldo cero aporta cero valga lo que valga: no debe anular el total."""
    expected_eth = _configure(monkeypatch, tokens={DAI: ("DAI", 18, 0)})
    _price(monkeypatch, "2000")
    _token_prices(monkeypatch)

    body = (await client.get("/api/governance/treasury")).json()

    assert body["balances"]["DAI"] == 0.0
    assert body["total_usd_value"] == pytest.approx(float(expected_eth) * 2000)


async def test_a_failing_token_read_is_not_a_zero_balance(client, monkeypatch):
    """Todo o nada: un token ilegible no puede publicarse como saldo cero."""
    _configure(monkeypatch, tokens={USDC: ("USDC", 6, 1_000_000)}, token_fails=True)
    _price(monkeypatch, "2000")

    body = (await client.get("/api/governance/treasury")).json()

    assert body["configured"] is True
    assert body["balances"] is None  # tampoco se publica el ETH suelto
    assert body["total_usd_value"] is None
    assert USDC in body["error"].lower()


async def test_absurd_token_decimals_are_rejected(client, monkeypatch):
    """Un contrato que declara 200 decimales no da un saldo, da un disparate."""
    _configure(monkeypatch, tokens={USDC: ("USDC", 200, 1_000_000)})
    _price(monkeypatch, "2000")

    body = (await client.get("/api/governance/treasury")).json()

    assert body["balances"] is None
    assert "decimales" in body["error"]


async def test_a_token_without_symbol_is_labelled_by_address(client, monkeypatch):
    """Algunos tokens antiguos devuelven symbol() como bytes32 y la llamada
    falla. Eso no invalida el saldo, pero la etiqueta es nuestra, no suya."""
    _configure(monkeypatch, tokens={USDC: (ValueError("bytes32"), 6, 2_000_000)})
    _price(monkeypatch, "2000")
    _token_prices(monkeypatch, **{USDC: "1.0"})

    body = (await client.get("/api/governance/treasury")).json()

    asset = next(a for a in body["assets"] if a["address"] == USDC)
    assert asset["symbol_source"] == "address"
    assert asset["amount"] == 2.0


async def test_testnet_tokens_are_never_priced(client, monkeypatch):
    _configure(monkeypatch, chain_id=SEPOLIA, tokens={USDC: ("USDC", 6, 1_000_000)})
    _price(monkeypatch, "2000")
    _token_prices(monkeypatch, **{USDC: "1.0"})

    body = (await client.get("/api/governance/treasury")).json()

    assert body["balances"]["USDC"] == 1.0
    assert body["total_usd_value"] is None


async def test_an_invalid_token_address_is_a_configuration_error(client, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "TREASURY_TOKENS", "0xno-es-una-direccion")

    body = (await client.get("/api/governance/treasury")).json()

    assert body["configured"] is False
    assert "TREASURY_TOKENS" in body["error"]


async def test_too_many_tokens_are_refused(client, monkeypatch):
    """El endpoint es público: cada token son tres llamadas al RPC."""
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "TREASURY_MAX_TOKENS", 2)
    monkeypatch.setattr(
        settings, "TREASURY_TOKENS", ",".join([USDC, DAI, "0x" + "11" * 20])
    )

    body = (await client.get("/api/governance/treasury")).json()

    assert body["configured"] is False
    assert "máximo" in body["error"]


def test_binance_does_not_price_tokens_by_symbol(monkeypatch):
    """Dos tokens distintos pueden llamarse igual: emparejar por símbolo
    falsearía el patrimonio, así que con Binance quedan sin precio."""
    monkeypatch.setattr(settings, "ETH_PRICE_PROVIDER", "binance")

    assert treasury_service.token_prices_usd([USDC], MAINNET) == {}
