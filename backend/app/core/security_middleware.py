"""
Security Middleware
Rate limiting, CSRF protection, and security headers
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
from datetime import datetime, timedelta
from ipaddress import ip_address, ip_network
import asyncio
import time
import hashlib
import secrets
import logging
import re

from .rate_limit_store import build_store

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware with progressive slowdown
    """
    
    _SENSITIVE_PATH_PATTERNS = (
        re.compile(r"^/api/auth(?:/|$)"),
        re.compile(r"^/api/wallet/(?:challenge|verify)/?$"),
        re.compile(r"^/api/governance/vote/?$"),
        re.compile(r"^/api/governance/delegate(?:/|$)"),
        re.compile(r"^/api/governance/elections/[^/]+/vote/?$"),
        re.compile(r"^/api/membership/mint/?$"),
        # Transporte anónimo de MACI: sin sesión, sin bearer y escribe en la
        # base. Es exactamente el endpoint que necesita un límite propio.
        re.compile(r"^/api/maci/polls/[^/]+/messages/?$"),
    )

    def __init__(
        self,
        app,
        requests_per_minute: int = 100,
        sensitive_paths_limit: int = 30,
        window_seconds: int = 60,
        trusted_proxy_ips: str = "",
        redis_url: str = "",
        store=None,
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.sensitive_paths_limit = sensitive_paths_limit
        self.window_seconds = max(1, window_seconds)
        # Los buckets viven en el almacén: memoria por defecto, Redis si está
        # configurado (ROADMAP 3.8). Sin Redis el límite es POR PROCESO.
        # Se acepta un almacén ya construido para que main pueda conservar la
        # referencia y exponer su estado en /health/ready. Starlette instancia
        # los middlewares de forma perezosa, así que buscarlo por
        # introspección desde el endpoint sería frágil.
        self.store = store if store is not None else build_store(redis_url)
        # Ya no queda estado en el proceso: la ventana y la penalización
        # progresiva viven en el almacén (ROADMAP 3.8). Con varios workers el
        # castigo por intentos fallidos también es compartido, así que rotar de
        # instancia deja de limpiarlo.
        self.trusted_proxy_networks = self._parse_trusted_proxy_networks(
            trusted_proxy_ips
        )

        # Health probes must remain observable even while an individual
        # client is being throttled. Otherwise an orchestrator can mistake a
        # rate-limit response for a dead or unready process.
        self.excluded_paths = {
            "/health",
            "/health/live",
            "/health/ready",
        }
        

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in self.excluded_paths:
            return await call_next(request)

        client_ip = self._get_client_ip(request)

        # Every request consumes the per-IP global budget. Sensitive endpoints
        # additionally share one stricter per-IP budget; using the path itself
        # as a key would let callers evade it by rotating election/proposal IDs.
        is_sensitive = self._is_sensitive_path(path)
        buckets = [(f"global:{client_ip}", self.requests_per_minute)]
        if is_sensitive:
            buckets.append((f"sensitive:{client_ip}", self.sensitive_paths_limit))

        # Se consultan TODOS los buckets aunque uno ya haya excedido: parar en
        # el primero dejaría el bucket sensible sin registrar la petición y una
        # IP podría agotar el global para no gastar el estricto.
        allowed = True
        for key, limit in buckets:
            if not await self.store.allow(key, limit, self.window_seconds):
                allowed = False

        if not allowed:
            logger.warning(f"Rate limit exceeded: {client_ip} on {path}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please wait before making more requests.",
                    "retry_after": self.window_seconds
                }
            )

        # Progressive slowdown for failed attempts.
        # Must be asyncio.sleep: time.sleep here would block the event loop
        # for every concurrent request, not just the abusive client.
        failures = await self.store.penalty(client_ip, 0, self.PENALTY_TTL_SECONDS)
        if failures > self.PENALTY_THRESHOLD:
            delay = min(failures * 0.5, 30)  # Max 30 seconds
            await asyncio.sleep(delay)
        
        # Process request
        response = await call_next(request)
        
        # Track failed attempts
        if response.status_code in [401, 403, 422]:
            await self.store.penalty(client_ip, 1, self.PENALTY_TTL_SECONDS)
        elif response.status_code == 200:
            await self.store.penalty(client_ip, -1, self.PENALTY_TTL_SECONDS)

        return response
    
    # Umbral y caducidad de la penalización progresiva. El TTL evita que un
    # contador quede vivo para siempre; el barrido manual que hacía falta con
    # los diccionarios en proceso desapareció con ellos.
    PENALTY_THRESHOLD = 5
    PENALTY_TTL_SECONDS = 3600

    @classmethod
    def _is_sensitive_path(cls, path: str) -> bool:
        """Match only the intended mutating endpoints, with optional slash."""
        return any(pattern.fullmatch(path) for pattern in cls._SENSITIVE_PATH_PATTERNS)

    @staticmethod
    def _parse_trusted_proxy_networks(value: str):
        """Parse explicitly trusted proxy IPs/CIDRs; invalid entries trust nobody.

        A wildcard is deliberately unsupported. Trusting every peer would make
        X-Forwarded-For caller-controlled again.
        """
        networks = []
        for raw_entry in value.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            try:
                networks.append(ip_network(entry, strict=False))
            except ValueError:
                logger.warning("Ignoring invalid TRUSTED_PROXY_IPS entry")
        return tuple(networks)

    def _is_trusted_proxy(self, value) -> bool:
        return any(value in network for network in self.trusted_proxy_networks)

    def _get_client_ip(self, request: Request) -> str:
        """Resolve a rate-limit identity without trusting caller headers.

        The direct TCP peer is authoritative by default. X-Forwarded-For is
        considered only when that peer belongs to an explicitly configured
        trusted proxy network. The chain is then walked from right to left so
        a value prepended by the original client cannot override the address
        appended by the trusted proxy.
        """
        peer_host = request.client.host if request.client else "unknown"
        try:
            peer_ip = ip_address(peer_host)
        except ValueError:
            return peer_host

        if not self._is_trusted_proxy(peer_ip):
            return peer_host

        forwarded = request.headers.get("X-Forwarded-For")
        if not forwarded:
            return peer_host

        try:
            chain = [
                ip_address(item.strip())
                for item in forwarded.split(",")
                if item.strip()
            ]
        except ValueError:
            # A malformed chain is not partially trusted.
            return peer_host

        for candidate in reversed(chain):
            if not self._is_trusted_proxy(candidate):
                return str(candidate)
        return peer_host


class RequestBodyLimitMiddleware:
    """Enforce a body limit while ASGI request chunks are consumed.

    Content-Length is only an optimization: callers may omit or forge it. The
    receive wrapper counts the actual bytes and aborts before an endpoint can
    assemble an oversized upload in memory.
    """

    MAX_BODY_SIZE = 10 * 1024 * 1024

    def __init__(self, app, max_body_size: int = MAX_BODY_SIZE):
        self.app = app
        self.max_body_size = max_body_size

    @staticmethod
    async def _respond(scope, receive, send, status_code: int, detail: str):
        response = JSONResponse(status_code=status_code, content={"detail": detail})
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.lower(): value
            for key, value in scope.get("headers", [])
        }
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except (TypeError, ValueError):
                await self._respond(
                    scope, receive, send, 400, "Invalid Content-Length header"
                )
                return
            if content_length < 0:
                await self._respond(
                    scope, receive, send, 400, "Invalid Content-Length header"
                )
                return
            if content_length > self.max_body_size:
                await self._respond(
                    scope, receive, send, 413, "Request body too large"
                )
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_size:
                    raise HTTPException(
                        status_code=413,
                        detail="Request body too large",
                    )
            return message

        await self.app(scope, limited_receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security headers to all responses
    """
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://*.infura.io wss://*.infura.io https://*.alchemy.com;"
        )
        
        return response


class RequestValidationMiddleware(BaseHTTPMiddleware):
    """
    Validate and sanitize incoming requests
    """
    
    # Blocked patterns (SQL injection, XSS attempts)
    BLOCKED_PATTERNS = [
        "UNION SELECT",
        "DROP TABLE",
        "DELETE FROM",
        "<script>",
        "javascript:",
        "onerror=",
        "onclick=",
    ]
    
    async def dispatch(self, request: Request, call_next):
        # Check for blocked patterns in URL
        url_str = str(request.url).upper()
        for pattern in self.BLOCKED_PATTERNS:
            if pattern.upper() in url_str:
                logger.warning(f"Blocked pattern detected in URL: {pattern}")
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid request"}
                )
        
        return await call_next(request)


# === Utility Functions ===

def generate_nonce() -> str:
    """Generate a secure random nonce for vote verification"""
    return secrets.token_hex(32)


def verify_nonce(nonce: str, expected_length: int = 64) -> bool:
    """Verify nonce format"""
    if not nonce or len(nonce) != expected_length:
        return False
    try:
        int(nonce, 16)  # Must be valid hex
        return True
    except ValueError:
        return False


def hash_vote_data(proposal_id: str, voter_address: str, vote: str, nonce: str) -> str:
    """Create deterministic hash of vote data for verification"""
    data = f"{proposal_id}:{voter_address.lower()}:{vote}:{nonce}"
    return hashlib.sha256(data.encode()).hexdigest()


def verify_eth_address(address: str) -> bool:
    """Verify Ethereum address format"""
    if not address:
        return False
    if not address.startswith("0x"):
        return False
    if len(address) != 42:
        return False
    try:
        int(address, 16)
        return True
    except ValueError:
        return False


# === Anti-Fraud Detection ===

class FraudDetector:
    """Detección de patrones de voto sospechosos (ROADMAP 3.8).

    Qué quedó aquí y qué se movió, y por qué
    ────────────────────────────────────────
    Antes esta clase guardaba TRES cosas en memoria de proceso: el historial
    de votos, el grafo de delegaciones y el mapa delegante→delegado. Solo la
    primera era estado propio.

    Las dos de delegación **duplicaban la colección `delegations` de MongoDB**.
    El router ya comprobaba ciclos con `GovernanceService.find_delegation_cycle`
    y el máximo de delegados con un `count_documents`, ambos contra la base y
    con el mismo límite. La copia en memoria solo añadía una versión más vieja
    de la misma verdad, que además se vaciaba en cada reinicio.

    Moverlas a Redis habría creado una TERCERA copia divergiendo de la fuente
    autoritativa. En su lugar se eliminaron, y la única heurística que
    aportaban de forma exclusiva —la profundidad máxima de cadena— vive ahora
    en `find_delegation_cycle`, que ya recorre el grafo real.

    El historial de votos sí era estado propio sin equivalente en la base, y
    es lo que pasa a Redis: es una ventana deslizante por dirección, o sea
    exactamente un rate limit, así que reutiliza el mismo almacén.
    """

    # Se permiten hasta 10 votos por ventana; el 11º se marca. La versión
    # anterior comparaba `> 10` DESPUÉS de excluir el actual, así que dejaba
    # pasar 11 y marcaba el 12º — una discrepancia con su propio umbral
    # documentado. Se corrige al valor que la constante siempre dijo.
    MAX_VOTES_PER_WINDOW = 10
    VOTE_WINDOW_SECONDS = 300  # 5 minutos

    def __init__(self, store=None):
        self._store = store

    def bind(self, store) -> None:
        """Conecta el almacén compartido. Lo llama main al arrancar."""
        self._store = store

    async def check_rapid_voting(
        self, voter_address: str, proposal_id: str
    ) -> tuple[bool, str]:
        """(sospechoso, motivo) para un intento de voto.

        `proposal_id` ya no participa en la clave: el límite es por votante y
        ventana, no por propuesta. Incluirlo permitiría emitir la cuota entera
        contra cada propuesta rotando el identificador.
        """
        if self._store is None:
            # Sin almacén no se inventa un veredicto: dejar pasar en silencio
            # desactivaría el antifraude sin que nadie lo note.
            logger.error(
                "FraudDetector sin almacén: no se puede evaluar el patrón de voto"
            )
            return True, "Antifraude no disponible"

        allowed = await self._store.allow(
            f"votes:{voter_address.lower()}",
            limit=self.MAX_VOTES_PER_WINDOW,
            window_seconds=self.VOTE_WINDOW_SECONDS,
        )
        if not allowed:
            return True, "Too many votes in short period"
        return False, ""

    async def reset(self) -> None:
        """Limpia el historial. Solo lo usan los tests."""
        if self._store is not None:
            await self._store.reset()


# Global fraud detector instance
fraud_detector = FraudDetector()
