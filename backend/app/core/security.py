"""
Security Module
Rate limiting, authentication helpers, and security utilities
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
import hashlib
import uuid
from collections import defaultdict
import time


class RateLimiter:
    """Simple in-memory rate limiter"""
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, list] = defaultdict(list)
    
    def is_allowed(self, client_id: str) -> bool:
        """Check if request is allowed for client"""
        now = time.time()
        window_start = now - self.window_seconds
        
        # Clean old requests
        self.requests[client_id] = [
            t for t in self.requests[client_id] if t > window_start
        ]
        
        # Check limit
        if len(self.requests[client_id]) >= self.max_requests:
            return False
        
        # Record request
        self.requests[client_id].append(now)
        return True
    
    def get_remaining(self, client_id: str) -> int:
        """Get remaining requests for client"""
        now = time.time()
        window_start = now - self.window_seconds
        
        current_requests = len([
            t for t in self.requests[client_id] if t > window_start
        ])
        
        return max(0, self.max_requests - current_requests)


def generate_hash(data: str) -> str:
    """Generate SHA256 hash of data"""
    return hashlib.sha256(data.encode()).hexdigest()


def generate_short_hash(data: str, length: int = 16) -> str:
    """Generate truncated hash for display"""
    return generate_hash(data)[:length]


def generate_unique_id() -> str:
    """Generate unique identifier"""
    return str(uuid.uuid4())


def generate_mock_address() -> str:
    """Generate mock wallet address for development.

    NOTE: scheduled for removal in ROADMAP task 1.7 together with
    POST /api/wallet/connect (MetaMask already handles connection client-side).
    """
    return f"0x{uuid.uuid4().hex[:8].upper()}...C1TY"


# Global rate limiter instance
rate_limiter = RateLimiter()
