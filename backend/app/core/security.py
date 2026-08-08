"""
Security Module — hashing helpers.

Rate limiting lives in `security_middleware.RateLimitMiddleware`, which is the
instance actually wired into the ASGI stack. A second, never-mounted
`RateLimiter` class used to sit here; it enforced nothing and only made the
codebase look like it had two limiters.
"""

import hashlib


def generate_hash(data: str) -> str:
    """Generate SHA256 hash of data"""
    return hashlib.sha256(data.encode()).hexdigest()


def generate_short_hash(data: str, length: int = 16) -> str:
    """Generate truncated hash for display"""
    return generate_hash(data)[:length]
