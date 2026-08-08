"""
Almacenes del rate limiter (ROADMAP 3.8).

Lo que importa comprobar, en orden:

1. Que la ventana deslizante de Redis cuenta bien y **expira**: sin EXPIRE,
   cada IP deja una clave para siempre y Redis acumula memoria igual que hacía
   el diccionario en proceso.
2. Que el límite es realmente COMPARTIDO. Es la razón entera de la migración:
   con contadores por proceso, dos workers duplican el límite efectivo.
3. Que si Redis cae se degrada a memoria pero **de forma visible**. Un
   fallback silencioso convertiría un límite global en uno por proceso sin que
   nadie se enterara.

El camino Redis se prueba con `fakeredis[lua]`, que ejecuta el mismo script
Lua que se enviará a un Redis real. No sustituye a una prueba contra un
servidor de verdad, pero verifica la lógica de la ventana en vez de asumirla.
"""

import fakeredis.aioredis
import pytest

from app.core.rate_limit_store import (
    FallbackRateLimitStore,
    InMemoryRateLimitStore,
    RedisRateLimitStore,
    build_store,
    describe,
)


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


# === Ventana deslizante ===


@pytest.mark.parametrize("store_factory", ["memory", "redis"])
async def test_allows_up_to_the_limit_and_then_refuses(store_factory, redis_client):
    """Mismo comportamiento observable en ambos almacenes."""
    store = (
        InMemoryRateLimitStore()
        if store_factory == "memory"
        else RedisRateLimitStore(redis_client)
    )

    verdicts = [await store.allow("ip-1", limit=3, window_seconds=60) for _ in range(5)]

    assert verdicts == [True, True, True, False, False]


@pytest.mark.parametrize("store_factory", ["memory", "redis"])
async def test_buckets_are_independent(store_factory, redis_client):
    store = (
        InMemoryRateLimitStore()
        if store_factory == "memory"
        else RedisRateLimitStore(redis_client)
    )

    assert await store.allow("ip-a", limit=1, window_seconds=60) is True
    assert await store.allow("ip-a", limit=1, window_seconds=60) is False
    # Otra IP no hereda el agotamiento de la primera.
    assert await store.allow("ip-b", limit=1, window_seconds=60) is True


async def test_redis_bucket_expires(redis_client):
    """Sin EXPIRE, una IP que no vuelve deja la clave para siempre."""
    store = RedisRateLimitStore(redis_client)
    await store.allow("ip-x", limit=5, window_seconds=60)

    ttl = await redis_client.ttl("rl:ip-x")

    assert 0 < ttl <= 61


async def test_redis_counts_requests_in_the_same_instant(redis_client):
    """Dos peticiones con el mismo score deben contar como DOS.

    Si compartieran miembro en el sorted set, ZADD sobrescribiría y el límite
    contaría de menos justo bajo la ráfaga que debe frenar.
    """
    store = RedisRateLimitStore(redis_client)

    for _ in range(4):
        await store.allow("burst", limit=10, window_seconds=60)

    assert await redis_client.zcard("rl:burst") == 4


# === La razón de la migración ===


async def test_redis_limit_is_shared_between_workers(redis_client):
    """Dos procesos contra el mismo Redis comparten la cuota.

    Es lo que la memoria de proceso no puede dar: hoy, con dos instancias en
    Render, el límite efectivo es el doble del configurado.
    """
    worker_a = RedisRateLimitStore(redis_client)
    worker_b = RedisRateLimitStore(redis_client)

    assert await worker_a.allow("ip", limit=2, window_seconds=60) is True
    assert await worker_b.allow("ip", limit=2, window_seconds=60) is True
    # El tercero excede aunque venga de otro worker.
    assert await worker_b.allow("ip", limit=2, window_seconds=60) is False


async def test_memory_limit_is_not_shared(redis_client):
    """Contraprueba: en memoria cada proceso tiene su propia cuota."""
    worker_a = InMemoryRateLimitStore()
    worker_b = InMemoryRateLimitStore()

    assert await worker_a.allow("ip", limit=1, window_seconds=60) is True
    # El mismo cliente pasa en el otro worker: el límite efectivo se duplica.
    assert await worker_b.allow("ip", limit=1, window_seconds=60) is True


# === Degradación visible ===


class _BrokenRedis:
    backend = "redis"

    async def allow(self, key, limit, window_seconds):
        raise ConnectionError("redis caído")

    async def reset(self):
        raise ConnectionError("redis caído")


async def test_falls_back_to_memory_when_redis_fails():
    store = FallbackRateLimitStore(_BrokenRedis(), InMemoryRateLimitStore())

    assert await store.allow("ip", limit=2, window_seconds=60) is True
    assert await store.allow("ip", limit=2, window_seconds=60) is True
    assert await store.allow("ip", limit=2, window_seconds=60) is False


async def test_the_degradation_is_visible_not_silent():
    """Un operador debe poder distinguir límite global de límite por proceso."""
    store = FallbackRateLimitStore(_BrokenRedis(), InMemoryRateLimitStore())

    assert describe(store)["shared_across_workers"] is True  # antes del fallo

    await store.allow("ip", limit=5, window_seconds=60)

    diagnostics = describe(store)
    assert diagnostics["degraded"] is True
    assert diagnostics["shared_across_workers"] is False
    assert "redis no disponible" in diagnostics["backend"]


# === Selección del almacén ===


def test_without_redis_url_uses_memory_without_pretending_to_be_degraded():
    """Un despliegue de un proceso no debe parecer roto por no usar Redis."""
    store = build_store("")

    assert isinstance(store, InMemoryRateLimitStore)
    assert describe(store) == {
        "backend": "memory",
        "shared_across_workers": False,
        "degraded": False,
    }


def test_with_redis_url_builds_a_fallback_store():
    store = build_store("redis://localhost:6379/0")

    assert isinstance(store, FallbackRateLimitStore)
    assert describe(store)["shared_across_workers"] is True


# === Memoria acotada ===


async def test_memory_store_forgets_silent_clients():
    """La contabilidad no puede crecer una entrada por IP para siempre."""
    import time

    store = InMemoryRateLimitStore()
    await store.allow("vieja", limit=5, window_seconds=1)
    assert store.tracked_keys == 1

    # Simula que pasó el tiempo de retención sin tráfico de esa IP.
    store._last_seen["vieja"] = time.time() - 1000
    store._last_sweep = 0
    await store.allow("nueva", limit=5, window_seconds=1)

    assert "vieja" not in store._last_seen
