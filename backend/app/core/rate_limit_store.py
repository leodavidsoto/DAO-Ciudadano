"""
Almacenes del rate limiter (ROADMAP 3.8).

El problema que resuelve: los contadores viven en memoria de proceso, así que
se pierden al reiniciar y **no se comparten entre workers**. Con dos instancias
en Render, el límite efectivo es el doble del configurado, y un atacante que
provoque un reinicio recupera su cuota entera.

Dos implementaciones tras una interfaz:

* `InMemoryRateLimitStore` — comportamiento actual. Sigue siendo el correcto
  para tests y para un despliegue de un solo proceso.
* `RedisRateLimitStore` — ventana deslizante compartida sobre un sorted set.

Por qué Lua y no un pipeline
────────────────────────────
La decisión "¿cuántos hay en la ventana?" y la escritura "añade este" tienen
que ser **una sola operación atómica**. Con un pipeline, la comparación ocurre
en el cliente: dos workers pueden leer `count == limit-1` a la vez y ambos
admitir la petición, superando el límite justo cuando más importa. El script
Lua se ejecuta entero dentro de Redis, así que esa carrera no existe.

Qué pasa si Redis cae
─────────────────────
Se degrada al almacén en memoria, pero **de forma visible**: se registra en el
log y `/health/ready` lo expone en `rate_limit.backend`. Un fallback silencioso
convertiría un límite global en uno por proceso sin que nadie se enterara, que
es exactamente el tipo de degradación que este repositorio elimina.

No se falla cerrado (rechazar todo) a propósito: dejaría el servicio inaccesible
por una incidencia de la caché, que es peor que un límite temporalmente más laxo.
"""

import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

# Ventana deslizante atómica. Devuelve 1 si la petición se admite, 0 si excede.
#
#   KEYS[1] = clave del bucket
#   ARGV[1] = ahora (segundos, float)
#   ARGV[2] = tamaño de ventana en segundos
#   ARGV[3] = límite de peticiones
#   ARGV[4] = miembro único de esta petición (evita colisiones de score)
_SLIDING_WINDOW_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
    return 0
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
-- Expira el bucket entero: sin esto, una IP que no vuelve deja la clave para
-- siempre y Redis acumula memoria igual que hacía el diccionario en proceso.
redis.call('EXPIRE', KEYS[1], math.ceil(window) + 1)
return 1
"""

# Lectura sin escritura: cuántos eventos vivos hay en la ventana. Es lo que
# permite COMPROBAR sin consumir cuota (P-46).
_WINDOW_COUNT_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
return redis.call('ZCARD', KEYS[1])
"""


class RateLimitStore(ABC):
    """Un almacén decide si una petición cabe en la ventana de su bucket."""

    @property
    def backend(self) -> str:
        """Nombre del respaldo activo, para /health/ready.

        Es una propiedad y no un atributo de clase porque el almacén con
        respaldo lo CALCULA: si Redis se cayó tiene que decir "memory (redis
        no disponible)" en vez de seguir anunciando redis.
        """
        raise NotImplementedError

    @abstractmethod
    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        """True si la petición se admite y queda registrada."""

    @abstractmethod
    async def count(self, key: str, window_seconds: int) -> int:
        """Eventos vivos en la ventana, SIN registrar uno nuevo.

        Separar "cuántos van" de "apunta uno más" es lo que permite rechazar
        una petición inválida sin gastarle la cuota a quien la hizo (P-46).
        """
        raise NotImplementedError

    async def penalty(self, key: str, delta: int, ttl_seconds: int) -> int:
        """Ajusta y devuelve el contador de penalización de una clave.

        Separado de `allow` porque no es una ventana: es un contador que sube
        con cada fallo y baja con cada acierto, y debe sobrevivir entre
        peticiones igual que el resto del antifraude.
        """
        raise NotImplementedError

    async def reset(self) -> None:
        """Limpia el estado. Solo lo usan los tests."""


class InMemoryRateLimitStore(RateLimitStore):
    """Contadores en el proceso. Correcto para un solo worker."""

    @property
    def backend(self) -> str:
        return "memory"

    # Una IP se olvida tras este número de ventanas en silencio. Debe superar
    # la penalización progresiva: si no, callar una ventana bastaría para
    # limpiar el contador de intentos fallidos.
    RETENTION_WINDOWS = 10

    def __init__(self):
        self._buckets = defaultdict(list)
        self._penalties: dict[str, int] = {}
        self._last_seen: dict[str, float] = {}
        self._last_sweep = time.time()

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        self._last_seen[key] = now
        self._sweep(now, window_seconds)

        bucket = [t for t in self._buckets[key] if now - t < window_seconds]
        if len(bucket) >= limit:
            self._buckets[key] = bucket
            return False
        bucket.append(now)
        self._buckets[key] = bucket
        return True

    async def count(self, key: str, window_seconds: int) -> int:
        now = time.time()
        return len([t for t in self._buckets.get(key, []) if now - t < window_seconds])

    def _sweep(self, now: float, window_seconds: int) -> None:
        """Olvida claves inactivas. Amortizado a una vez por ventana.

        Sin esto, cada dirección distinta deja una entrada permanente: la
        contabilidad del propio limitador se convierte en el vector de
        agotamiento de memoria que debía prevenir.
        """
        if now - self._last_sweep < window_seconds:
            return
        self._last_sweep = now
        cutoff = now - window_seconds * self.RETENTION_WINDOWS
        for key in [k for k, seen in self._last_seen.items() if seen < cutoff]:
            self._last_seen.pop(key, None)
            self._buckets.pop(key, None)
            self._penalties.pop(key, None)
        for key in [k for k, stamps in self._buckets.items() if not stamps]:
            self._buckets.pop(key, None)

    async def penalty(self, key: str, delta: int, ttl_seconds: int) -> int:
        current = max(0, self._penalties.get(key, 0) + delta)
        if current == 0:
            self._penalties.pop(key, None)
        else:
            self._penalties[key] = current
        return current

    async def reset(self) -> None:
        self._buckets.clear()
        self._last_seen.clear()
        self._penalties.clear()
        self._last_sweep = time.time()

    # Introspección para los tests y el diagnóstico.
    @property
    def tracked_keys(self) -> int:
        return len(self._buckets)


class RedisRateLimitStore(RateLimitStore):
    """Ventana deslizante compartida entre workers."""

    @property
    def backend(self) -> str:
        return "redis"

    def __init__(self, client, namespace: str = "rl"):
        self._client = client
        self._namespace = namespace
        self._script = client.register_script(_SLIDING_WINDOW_LUA)
        self._count_script = client.register_script(_WINDOW_COUNT_LUA)
        self._counter = 0

    def _member(self) -> str:
        """Miembro único por petición.

        Dos peticiones en el mismo microsegundo tendrían el mismo score; si
        además compartieran miembro, ZADD sobrescribiría en vez de añadir y el
        límite contaría de menos.
        """
        self._counter += 1
        return f"{time.time_ns()}-{self._counter}"

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        result = await self._script(
            keys=[f"{self._namespace}:{key}"],
            args=[time.time(), window_seconds, limit, self._member()],
        )
        return bool(int(result))

    async def count(self, key: str, window_seconds: int) -> int:
        result = await self._count_script(
            keys=[f"{self._namespace}:{key}"],
            args=[time.time(), window_seconds],
        )
        return int(result)

    async def penalty(self, key: str, delta: int, ttl_seconds: int) -> int:
        """INCRBY + EXPIRE. El TTL evita que un contador quede para siempre."""
        full_key = f"{self._namespace}:penalty:{key}"
        value = int(await self._client.incrby(full_key, delta))
        if value <= 0:
            await self._client.delete(full_key)
            return 0
        await self._client.expire(full_key, ttl_seconds)
        return value

    async def reset(self) -> None:
        async for key in self._client.scan_iter(match=f"{self._namespace}:*"):
            await self._client.delete(key)


class FallbackRateLimitStore(RateLimitStore):
    """Usa Redis y, si falla, degrada a memoria dejando constancia.

    La degradación es visible a propósito: `backend` pasa a
    `"memory (redis no disponible)"` y eso llega a `/health/ready`. Un
    operador tiene que poder distinguir "límite global" de "límite por
    proceso" sin leer los logs.
    """

    def __init__(self, primary: RateLimitStore, fallback: RateLimitStore):
        self._primary = primary
        self._fallback = fallback
        self._degraded = False

    @property
    def backend(self) -> str:
        return (
            "memory (redis no disponible)" if self._degraded else self._primary.backend
        )

    @property
    def degraded(self) -> bool:
        return self._degraded

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        if not self._degraded:
            try:
                return await self._primary.allow(key, limit, window_seconds)
            except Exception as exc:
                self._degraded = True
                logger.error(
                    "Rate limiter degradado a memoria: Redis no responde (%s). "
                    "El límite deja de ser global y pasa a ser por proceso.",
                    type(exc).__name__,
                )
        return await self._fallback.allow(key, limit, window_seconds)

    async def count(self, key: str, window_seconds: int) -> int:
        if not self._degraded:
            try:
                return await self._primary.count(key, window_seconds)
            except Exception as exc:
                self._degraded = True
                logger.error(
                    "Rate limiter degradado a memoria al contar: Redis no "
                    "responde (%s).",
                    type(exc).__name__,
                )
        return await self._fallback.count(key, window_seconds)

    async def recover(self) -> bool:
        """Reintenta Redis. Devuelve True si volvió a estar disponible."""
        if not self._degraded:
            return True
        try:
            await self._primary.allow("__probe__", limit=10**9, window_seconds=1)
        except Exception:
            return False
        self._degraded = False
        logger.info("Rate limiter recuperado: Redis vuelve a responder")
        return True

    async def penalty(self, key: str, delta: int, ttl_seconds: int) -> int:
        if not self._degraded:
            try:
                return await self._primary.penalty(key, delta, ttl_seconds)
            except Exception as exc:
                self._degraded = True
                logger.error(
                    "Rate limiter degradado a memoria: Redis no responde (%s).",
                    type(exc).__name__,
                )
        return await self._fallback.penalty(key, delta, ttl_seconds)

    async def reset(self) -> None:
        await self._fallback.reset()
        try:
            await self._primary.reset()
        except Exception:
            pass


def build_store(redis_url: str) -> RateLimitStore:
    """Elige el almacén según la configuración.

    Sin `REDIS_URL` devuelve el de memoria sin ruido: un despliegue de un solo
    proceso no necesita Redis y no debería parecer degradado por no tenerlo.
    """
    memory = InMemoryRateLimitStore()
    url = (redis_url or "").strip()
    if not url:
        return memory

    try:
        import redis.asyncio as redis_asyncio
    except ImportError:
        logger.error(
            "REDIS_URL está configurada pero falta el paquete `redis`. "
            "El rate limiter sigue en memoria: el límite NO es global."
        )
        return memory

    try:
        client = redis_asyncio.from_url(url, decode_responses=True)
        return FallbackRateLimitStore(RedisRateLimitStore(client), memory)
    except Exception as exc:
        logger.error(
            "No se pudo construir el cliente de Redis (%s). El rate limiter "
            "sigue en memoria: el límite NO es global.",
            type(exc).__name__,
        )
        return memory


def describe(store: Optional[RateLimitStore]) -> dict:
    """Diagnóstico para /health/ready."""
    if store is None:
        return {"backend": "none", "shared_across_workers": False}
    backend = store.backend
    return {
        "backend": backend,
        # Lo que de verdad importa saber: si el límite es global o por proceso.
        "shared_across_workers": backend == "redis",
        "degraded": getattr(store, "degraded", False),
    }
