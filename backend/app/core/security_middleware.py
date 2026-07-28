"""
Security Middleware
Rate limiting, CSRF protection, and security headers
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio
import time
import hashlib
import secrets
import logging

logger = logging.getLogger(__name__)

# Ceiling on rate-limit buckets held in memory (audit finding N-10).
MAX_TRACKED_CLIENTS = 10000


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware with progressive slowdown
    """
    
    def __init__(self, app, requests_per_minute: int = 100, sensitive_paths_limit: int = 10):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.sensitive_paths_limit = sensitive_paths_limit
        self.requests = defaultdict(list)
        self.failed_attempts = defaultdict(int)
        # Hard ceiling on tracked clients. Without it, a burst from many
        # addresses grows these dicts until the process runs out of memory
        # (audit finding N-10). Evicting the oldest bucket is safe: it only
        # forgets history, and forgetting under pressure beats dying.
        self.max_tracked_clients = MAX_TRACKED_CLIENTS
        
        # Sensitive paths that need stricter limits
        self.sensitive_paths = [
            "/api/auth/",
            "/api/governance/vote",
            "/api/governance/delegate",
            "/api/membership/mint",
        ]
    
    async def dispatch(self, request: Request, call_next):
        client_ip = self._get_client_ip(request)
        path = request.url.path
        now = time.time()
        
        # Check if path is sensitive
        is_sensitive = any(path.startswith(sp) for sp in self.sensitive_paths)
        limit = self.sensitive_paths_limit if is_sensitive else self.requests_per_minute
        
        # Clean old requests (older than 1 minute)
        key = f"{client_ip}:{path}" if is_sensitive else client_ip
        self.requests[key] = [t for t in self.requests[key] if now - t < 60]
        
        # Check rate limit
        if len(self.requests[key]) >= limit:
            logger.warning(f"Rate limit exceeded: {client_ip} on {path}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please wait before making more requests.",
                    "retry_after": 60
                }
            )
        
        # Progressive slowdown for failed attempts.
        # Must be asyncio.sleep: time.sleep here would block the event loop
        # for every concurrent request, not just the abusive client.
        if self.failed_attempts[client_ip] > 5:
            delay = min(self.failed_attempts[client_ip] * 0.5, 30)  # Max 30 seconds
            await asyncio.sleep(delay)
        
        # Record request, evicting stale buckets first so the state cannot
        # grow without bound.
        self._evict_if_needed(now)
        self.requests[key].append(now)
        
        # Process request
        response = await call_next(request)
        
        # Track failed attempts
        if response.status_code in [401, 403, 422]:
            self.failed_attempts[client_ip] += 1
        elif response.status_code == 200:
            self.failed_attempts[client_ip] = max(0, self.failed_attempts[client_ip] - 1)
        
        return response
    
    def _evict_if_needed(self, now: float) -> None:
        """Drop buckets with no recent activity once the map grows too large."""
        if len(self.requests) < self.max_tracked_clients:
            return

        stale = [k for k, times in self.requests.items()
                 if not times or now - times[-1] >= 60]
        for key in stale:
            del self.requests[key]

        # Still over the ceiling: everything is active, so drop the oldest
        # buckets. Losing history for the least recent client is preferable
        # to unbounded growth.
        if len(self.requests) >= self.max_tracked_clients:
            oldest = sorted(self.requests.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)
            for key, _ in oldest[: len(self.requests) // 4]:
                del self.requests[key]

        if len(self.failed_attempts) >= self.max_tracked_clients:
            self.failed_attempts.clear()
            logger.warning("Cleared failed-attempt counters: tracking ceiling reached")

    def _get_client_ip(self, request: Request) -> str:
        """Client IP for rate-limiting purposes.

        X-Forwarded-For is CLIENT-CONTROLLED: anyone can set it to a random
        value on every request and get a fresh bucket, which turns the rate
        limiter off and — worse — grows the in-memory state without bound
        (audit finding N-10).

        It is honoured only when TRUSTED_PROXY_COUNT says a reverse proxy is
        in front, and even then we take the entry that proxy appended rather
        than the leftmost one, which is the part the client can forge.
        """
        trusted = settings.TRUSTED_PROXY_COUNT
        if trusted > 0:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                hops = [h.strip() for h in forwarded.split(",") if h.strip()]
                # The last `trusted` entries were appended by our own proxies;
                # the client address is the one just before them.
                if len(hops) >= trusted:
                    return hops[-trusted]
        return request.client.host if request.client else "unknown"


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
    
    # Maximum request body size (10MB)
    MAX_BODY_SIZE = 10 * 1024 * 1024
    
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
        # Check Content-Length
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_BODY_SIZE:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"}
            )
        
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
