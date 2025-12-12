"""
Security Middleware
Rate limiting, CSRF protection, and security headers
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
from datetime import datetime, timedelta
import time
import hashlib
import secrets
import logging

logger = logging.getLogger(__name__)


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
        
        # Progressive slowdown for failed attempts
        if self.failed_attempts[client_ip] > 5:
            delay = min(self.failed_attempts[client_ip] * 0.5, 30)  # Max 30 seconds
            time.sleep(delay)
        
        # Record request
        self.requests[key].append(now)
        
        # Process request
        response = await call_next(request)
        
        # Track failed attempts
        if response.status_code in [401, 403, 422]:
            self.failed_attempts[client_ip] += 1
        elif response.status_code == 200:
            self.failed_attempts[client_ip] = max(0, self.failed_attempts[client_ip] - 1)
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Get real client IP, accounting for proxies"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
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
        Detect circular or excessively deep delegation chains
        """
        MAX_CHAIN_DEPTH = 3
        MAX_DELEGATORS = 10
        
        # Check if this would create a cycle
        chain = [delegator.lower()]
        current = delegate.lower()
        
        while current in self.delegation_chains:
            if current in chain:
                return True, "Circular delegation detected"
            chain.append(current)
            if len(chain) > MAX_CHAIN_DEPTH:
                return True, f"Delegation chain too deep (max {MAX_CHAIN_DEPTH})"
            # Get next in chain
            delegators = self.delegation_chains[current]
            if delegators:
                current = delegators[0]
            else:
                break
        
        # Check max delegators
        if len(self.delegation_chains[delegate.lower()]) >= MAX_DELEGATORS:
            return True, f"Delegate has too many delegators (max {MAX_DELEGATORS})"
        
        return False, ""
    
    def record_delegation(self, delegator: str, delegate: str):
        """Record a delegation for tracking"""
        self.delegation_chains[delegate.lower()].append(delegator.lower())


# Global fraud detector instance
fraud_detector = FraudDetector()
