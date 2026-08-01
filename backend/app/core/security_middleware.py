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
    )

    def __init__(
        self,
        app,
        requests_per_minute: int = 100,
        sensitive_paths_limit: int = 30,
        window_seconds: int = 60,
        trusted_proxy_ips: str = "",
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.sensitive_paths_limit = sensitive_paths_limit
        self.window_seconds = max(1, window_seconds)
        self.requests = defaultdict(list)
        self.failed_attempts = defaultdict(int)
        self.last_seen: dict[str, float] = {}
        self._last_sweep = time.time()
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
        now = time.time()
        self.last_seen[client_ip] = now
        self._sweep_expired(now)

        # Every request consumes the per-IP global budget. Sensitive endpoints
        # additionally share one stricter per-IP budget; using the path itself
        # as a key would let callers evade it by rotating election/proposal IDs.
        is_sensitive = self._is_sensitive_path(path)
        buckets = [
            (f"global:{client_ip}", self.requests_per_minute, "global"),
        ]
        if is_sensitive:
            buckets.append(
                (f"sensitive:{client_ip}", self.sensitive_paths_limit, "sensitive")
            )

        for key, _, _ in buckets:
            self.requests[key] = [
                timestamp
                for timestamp in self.requests[key]
                if now - timestamp < self.window_seconds
            ]

        exceeded_scope = next(
            (
                scope
                for key, limit, scope in buckets
                if len(self.requests[key]) >= limit
            ),
            None,
        )
        if exceeded_scope:
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
        if self.failed_attempts[client_ip] > 5:
            delay = min(self.failed_attempts[client_ip] * 0.5, 30)  # Max 30 seconds
            await asyncio.sleep(delay)
        
        # A sensitive request is recorded in both budgets.
        for key, _, _ in buckets:
            self.requests[key].append(now)
        
        # Process request
        response = await call_next(request)
        
        # Track failed attempts
        if response.status_code in [401, 403, 422]:
            self.failed_attempts[client_ip] += 1
        elif response.status_code == 200:
            self.failed_attempts[client_ip] = max(0, self.failed_attempts[client_ip] - 1)
        
        return response
    
    # An IP is forgotten once it has been silent for this many windows. It must
    # outlast the progressive-slowdown penalty, otherwise going quiet for one
    # window would be enough to clear a failed-attempt counter.
    _RETENTION_WINDOWS = 10

    def _sweep_expired(self, now: float) -> None:
        """Drop per-IP state for clients that stopped sending requests.

        Without this, every dict here grows one permanent entry per distinct
        source address: on a public API the bookkeeping itself becomes the
        memory-exhaustion vector the rate limiter is supposed to prevent.
        Amortized to once per window so the hot path stays O(1).
        """
        if now - self._last_sweep < self.window_seconds:
            return
        self._last_sweep = now

        cutoff = now - self.window_seconds * self._RETENTION_WINDOWS
        stale = [ip for ip, seen in self.last_seen.items() if seen < cutoff]
        for ip in stale:
            del self.last_seen[ip]
            self.failed_attempts.pop(ip, None)
            self.requests.pop(f"global:{ip}", None)
            self.requests.pop(f"sensitive:{ip}", None)

        # Timestamp lists of still-active clients are pruned on their own
        # requests; drop the ones that emptied out and were never refilled.
        for key in [k for k, stamps in self.requests.items() if not stamps]:
            del self.requests[key]

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
    """
    Detect suspicious voting and delegation patterns
    """
    
    def __init__(self):
        self.vote_history = defaultdict(list)  # address -> [(timestamp, proposal_id)]
        self.delegation_chains = defaultdict(list)  # delegate -> [delegators]
        self.delegated_to = {}  # delegator -> delegate (each address delegates at most once)
    
    def check_rapid_voting(self, voter_address: str, proposal_id: str) -> tuple[bool, str]:
        """
        Detect suspiciously rapid voting patterns
        Returns (is_suspicious, reason)
        """
        now = datetime.now()
        history = self.vote_history[voter_address.lower()]
        
        # Count votes in last 5 minutes
        recent_votes = [v for v in history if now - v[0] < timedelta(minutes=5)]
        
        if len(recent_votes) > 10:
            return True, "Too many votes in short period"
        
        # Record this vote
        history.append((now, proposal_id))
        
        # Keep only last 100 votes
        self.vote_history[voter_address.lower()] = history[-100:]
        
        return False, ""
    
    def check_delegation_chain(self, delegator: str, delegate: str) -> tuple[bool, str]:
        """
        Detect circular or excessively deep delegation chains.

        Walks the OUTGOING delegations starting from the proposed delegate
        (delegator -> delegate direction — the direction a vote travels).
        The previous implementation walked delegate -> delegators (backwards)
        and never detected a real a->b + b->a cycle (audit finding N-3).

        NOTE: state is in-process memory and empty after a restart (M-2);
        the authoritative cycle check runs against MongoDB in
        GovernanceService.find_delegation_cycle. This one adds the
        chain-depth and delegator-count heuristics.
        """
        MAX_CHAIN_DEPTH = 3
        MAX_DELEGATORS = 10
        
        seen = {delegator.lower()}
        current = delegate.lower()
        depth = 0
        
        while True:
            if current in seen:
                return True, "Circular delegation detected"
            seen.add(current)
            depth += 1
            if depth > MAX_CHAIN_DEPTH:
                return True, f"Delegation chain too deep (max {MAX_CHAIN_DEPTH})"
            # Follow where `current` has delegated its own vote, if anywhere
            nxt = self.delegated_to.get(current)
            if nxt is None:
                break
            current = nxt
        
        # Check max delegators
        if len(self.delegation_chains[delegate.lower()]) >= MAX_DELEGATORS:
            return True, f"Delegate has too many delegators (max {MAX_DELEGATORS})"
        
        return False, ""
    
    def record_delegation(self, delegator: str, delegate: str):
        """Record a delegation, replacing any previous one by the same delegator"""
        delegator = delegator.lower()
        delegate = delegate.lower()
        previous = self.delegated_to.get(delegator)
        if previous and delegator in self.delegation_chains[previous]:
            self.delegation_chains[previous].remove(delegator)
        self.delegated_to[delegator] = delegate
        if delegator not in self.delegation_chains[delegate]:
            self.delegation_chains[delegate].append(delegator)
    
    def remove_delegation(self, delegator: str):
        """Forget a revoked delegation so stale edges don't flag false cycles"""
        delegator = delegator.lower()
        previous = self.delegated_to.pop(delegator, None)
        if previous and delegator in self.delegation_chains[previous]:
            self.delegation_chains[previous].remove(delegator)


# Global fraud detector instance
fraud_detector = FraudDetector()
