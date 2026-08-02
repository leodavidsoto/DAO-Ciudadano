"""
DAO Ciudadana API - Main Server Entry Point
Professional modular FastAPI application with security hardening
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime, timezone
import asyncio
import logging
import os

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Import app modules
from app.core.config import settings
from app.core.database import Database
from app.core import readiness
from app.core.security_middleware import (
    RateLimitMiddleware,
    RequestBodyLimitMiddleware,
    SecurityHeadersMiddleware,
    RequestValidationMiddleware
)
from app.routers import auth_router, wallet_router, membership_router, dashboard_router
from app.routers.governance import router as governance_router
from app.routers.elections import router as elections_router
from app.routers.identity import router as identity_router
from app.routers.maci import router as maci_router
from app.routers.erc4337 import router as erc4337_router


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info(f"🚀 Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info("🔒 Security middleware enabled: Rate Limiting, Security Headers, Request Validation")
    
    # Connect to database
    mongo_url = os.environ.get('MONGO_URL', settings.MONGO_URL)
    db_name = os.environ.get('DB_NAME', settings.DB_NAME)
    Database.connect(mongo_url, db_name)
    await Database.ensure_indexes()
    readiness.report_at_startup()

    yield
    
    # Shutdown
    logger.info("Shutting down application")
    Database.close()


# Create FastAPI application
DOCS_ENABLED = settings.DEBUG and not settings.is_production

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="API piloto de membresía y gobernanza ciudadana",
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
)


# === Security Middleware Stack ===
# Order matters: first added = last executed

# El almacén se construye acá para conservar la referencia: /health/ready
# necesita reportar si el límite es global o por proceso.
from app.core.rate_limit_store import build_store as _build_rate_limit_store

rate_limit_store = _build_rate_limit_store(settings.REDIS_URL)

# El antifraude comparte el almacén: su historial de votos es una ventana
# deslizante por dirección, o sea exactamente un rate limit (ROADMAP 3.8).
from app.core.security_middleware import fraud_detector as _fraud_detector

_fraud_detector.bind(_build_rate_limit_store(settings.REDIS_URL))

# 1. Rate Limiting (outermost - first line of defense)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=settings.RATE_LIMIT_REQUESTS,
    # El bucket sensible ahora agrega challenge/verify/mint/votos por IP. Treinta
    # permite un flujo legítimo con más de una wallet sin recuperar el bypass
    # anterior por ruta o election_id.
    sensitive_paths_limit=settings.RATE_LIMIT_SENSITIVE_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    trusted_proxy_ips=settings.TRUSTED_PROXY_IPS,
    store=rate_limit_store,
)

# 2. Request Validation
app.add_middleware(RequestValidationMiddleware)

# 3. Request body limit (counts actual ASGI chunks, not only Content-Length)
app.add_middleware(RequestBodyLimitMiddleware)

# 4. Security Headers
app.add_middleware(SecurityHeadersMiddleware)

# 5. CORS (innermost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log the full detail server-side (with a correlation id), but never leak
    # internal error strings (paths, drivers, queries) to the client.
    import uuid
    error_id = uuid.uuid4().hex[:12]
    logger.error(f"Unhandled exception [{error_id}]: {exc}", exc_info=True)
    body = {"detail": "Internal server error", "error_id": error_id}
    if settings.DEBUG:
        body["error"] = str(exc)  # Only in local/debug mode
    return JSONResponse(status_code=500, content=body)


# Root endpoint
@app.get("/")
async def root():
    """API health check and info"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "operational",
        # Must mirror docs_url above: advertising /docs while FastAPI has it
        # disabled sends callers to a 404.
        "docs": "/docs" if DOCS_ENABLED else None,
    }


@app.get("/api")
async def api_root():
    """API root endpoint"""
    return {"message": "DAO Citizenship API"}


# Include routers with /api prefix
app.include_router(auth_router, prefix="/api")
# Emisión real de credenciales ZK: router aparte, sin el bloqueo de los demos.
app.include_router(identity_router, prefix="/api")
app.include_router(wallet_router, prefix="/api")
app.include_router(membership_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(governance_router, prefix="/api")
app.include_router(elections_router, prefix="/api")
app.include_router(maci_router, prefix="/api")
app.include_router(erc4337_router, prefix="/api")


# Process liveness: no external dependency checks. Orchestrators can use this
# only to decide whether the process itself should be restarted.
@app.get("/health/live")
async def liveness_check():
    return {
        "status": "alive",
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Deployment readiness. `/health` remains as a backwards-compatible alias.
@app.get("/health")
@app.get("/health/ready")
async def health_check():
    """Health check endpoint for monitoring.

    Incluye el estado de configuración (readiness.status()) para que un
    secreto faltante en producción sea diagnosticable desde aquí en vez
    de descubrirse como un error opaco en el primer request real.
    """
    from fastapi.responses import JSONResponse

    onchain_runtime = None
    if settings.MINT_MODE == "onchain":
        from app.services import chain_service

        if chain_service.is_configured():
            onchain_runtime = await asyncio.to_thread(chain_service.runtime_status)
    configuration = readiness.status(onchain_runtime)
    db_healthy = True
    try:
        await Database.get_db().command("ping")
    except Exception:
        db_healthy = False

    indexes_ready = Database.indexes_ready
    healthy = db_healthy and indexes_ready and configuration["ready"]

    # Estado del rate limiter: un operador tiene que poder distinguir "límite
    # global" de "límite por proceso" sin leer los logs (ROADMAP 3.8).
    from app.core.rate_limit_store import describe as describe_rate_limit

    rate_limit = describe_rate_limit(rate_limit_store)

    # Sonda del bundler solo si el transporte está habilitado: no hay que
    # golpear a un proveedor externo en cada health check de un despliegue
    # que ni siquiera lo usa.
    from app.services import paymaster_service

    erc4337 = await asyncio.to_thread(
        paymaster_service.status, paymaster_service.is_enabled()
    )
    status_label = (
        "healthy"
        if healthy and configuration["production_ready"]
        else "operational"
        if healthy
        else "degraded"
    )
    body = {
        "status": status_label,
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": {"healthy": db_healthy},
        "indexes": {"ready": indexes_ready},
        "rate_limit": rate_limit,
        "erc4337": erc4337,
        "configuration": configuration,
    }
    return JSONResponse(status_code=200 if healthy else 503, content=body)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
