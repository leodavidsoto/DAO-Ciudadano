"""Regression tests for proxy-aware rate limits and streaming body limits."""

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.requests import Request as StarletteRequest

from app.core.security_middleware import (
    RateLimitMiddleware,
    RequestBodyLimitMiddleware,
)


async def _noop_app(scope, receive, send):
    return None


def _request(peer: str, forwarded_for: str | None = None) -> StarletteRequest:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return StarletteRequest(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("testserver", 443),
        }
    )


def test_untrusted_peer_cannot_spoof_forwarded_ip():
    limiter = RateLimitMiddleware(_noop_app)
    request = _request("203.0.113.10", "198.51.100.99")

    assert limiter._get_client_ip(request) == "203.0.113.10"


def test_trusted_proxy_chain_uses_nearest_untrusted_client():
    limiter = RateLimitMiddleware(
        _noop_app,
        trusted_proxy_ips="10.0.0.0/8,192.0.2.20",
    )
    request = _request(
        "10.0.0.2",
        # A caller-prepended value is leftmost. Walking from the trusted peer
        # backwards selects the address appended nearest to the proxy chain.
        "203.0.113.250, 198.51.100.42, 10.0.0.1",
    )

    assert limiter._get_client_ip(request) == "198.51.100.42"


def test_malformed_forwarded_chain_falls_back_to_direct_peer():
    limiter = RateLimitMiddleware(_noop_app, trusted_proxy_ips="10.0.0.0/8")
    request = _request("10.0.0.2", "not-an-ip, 198.51.100.42")

    assert limiter._get_client_ip(request) == "10.0.0.2"


@pytest.mark.parametrize(
    "path",
    [
        "/api/governance/elections/election-1/vote",
        "/api/governance/elections/election-1/vote/",
        "/api/governance/vote",
        "/api/wallet/challenge",
    ],
)
def test_sensitive_path_matching_includes_election_votes(path):
    assert RateLimitMiddleware._is_sensitive_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/api/governance/elections/election-1/results",
        "/api/governance/elections/election-1/vote/export",
        "/api/governance/elections//vote",
    ],
)
def test_sensitive_path_matching_rejects_near_misses(path):
    assert RateLimitMiddleware._is_sensitive_path(path) is False


def _rate_limit_app(
    requests_per_minute: int = 100,
    sensitive_paths_limit: int = 10,
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=requests_per_minute,
        sensitive_paths_limit=sensitive_paths_limit,
    )

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def ok(path: str):
        return {"path": path}

    return app


async def test_sensitive_bucket_cannot_be_evaded_by_rotating_election_id():
    app = _rate_limit_app(sensitive_paths_limit=1)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        first = await client.post("/api/governance/elections/election-1/vote")
        rotated = await client.post("/api/governance/elections/election-2/vote")

    assert first.status_code == 200
    assert rotated.status_code == 429


async def test_sensitive_request_also_consumes_global_budget():
    app = _rate_limit_app(requests_per_minute=1, sensitive_paths_limit=10)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        sensitive = await client.post("/api/governance/elections/election-1/vote")
        ordinary = await client.get("/ordinary")

    assert sensitive.status_code == 200
    assert ordinary.status_code == 429


def _body_limit_app(max_body_size: int = 8) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=max_body_size)

    @app.post("/consume")
    async def consume(request: Request):
        body = await request.body()
        return {"size": len(body)}

    return app


async def test_body_limit_rejects_declared_oversize_before_endpoint():
    app = _body_limit_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post("/consume", content=b"123456789")

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body too large"


async def test_body_limit_counts_chunks_without_content_length():
    app = _body_limit_app()

    async def chunks():
        yield b"1234"
        yield b"56789"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post("/consume", content=chunks())

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body too large"


async def test_body_limit_allows_chunked_body_at_limit():
    app = _body_limit_app()

    async def chunks():
        yield b"1234"
        yield b"5678"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post("/consume", content=chunks())

    assert response.status_code == 200
    assert response.json() == {"size": 8}


async def test_penalty_counter_lives_in_the_store_not_in_the_process():
    """La penalización progresiva ya no es estado de proceso (ROADMAP 3.8).

    Con contadores por instancia, rotar de worker limpiaba el castigo por
    intentos fallidos: bastaba reintentar hasta caer en otra.
    """
    from app.core.rate_limit_store import InMemoryRateLimitStore

    store = InMemoryRateLimitStore()
    middleware = RateLimitMiddleware(app=None, store=store)

    # El middleware no guarda nada propio.
    assert not hasattr(middleware, "failed_attempts")
    assert not hasattr(middleware, "requests")
    assert middleware.store is store


async def test_penalty_rises_with_failures_and_falls_with_successes():
    from app.core.rate_limit_store import InMemoryRateLimitStore

    store = InMemoryRateLimitStore()

    assert await store.penalty("ip", 1, 3600) == 1
    assert await store.penalty("ip", 1, 3600) == 2
    assert await store.penalty("ip", -1, 3600) == 1
    # No baja de cero: un cliente correcto no acumula crédito para gastarlo.
    assert await store.penalty("ip", -5, 3600) == 0
    assert await store.penalty("ip", 0, 3600) == 0


async def test_penalty_is_shared_between_workers():
    """Es la razón de moverlo: el castigo debe seguir al cliente, no al proceso."""
    import fakeredis.aioredis

    from app.core.rate_limit_store import RedisRateLimitStore

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    worker_a = RedisRateLimitStore(client)
    worker_b = RedisRateLimitStore(client)

    await worker_a.penalty("ip", 1, 3600)
    await worker_a.penalty("ip", 1, 3600)

    # El otro worker ve el mismo contador.
    assert await worker_b.penalty("ip", 0, 3600) == 2


async def test_penalty_key_expires():
    """Sin TTL, el contador de una IP quedaría vivo para siempre."""
    import fakeredis.aioredis

    from app.core.rate_limit_store import RedisRateLimitStore

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = RedisRateLimitStore(client)

    await store.penalty("ip", 1, 3600)

    assert 0 < await client.ttl("rl:penalty:ip") <= 3600
