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
import logging
import os

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Import app modules
from app.core.config import settings
from app.core.database import Database
from app.core.security_middleware import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    RequestValidationMiddleware
)
from app.routers import auth_router, wallet_router, membership_router, dashboard_router
from app.routers.governance import router as governance_router


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
    
    yield
    
    # Shutdown
    logger.info("Shutting down application")
    Database.close()


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Sistema de membresía digital ciudadana basado en blockchain - Secured",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,  # Disable docs in production
    redoc_url="/redoc" if settings.DEBUG else None,
)


# === Security Middleware Stack ===
# Order matters: first added = last executed

# 1. Rate Limiting (outermost - first line of defense)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=100,
    sensitive_paths_limit=10
)

# 2. Request Validation
app.add_middleware(RequestValidationMiddleware)

# 3. Security Headers
app.add_middleware(SecurityHeadersMiddleware)

# 4. CORS (innermost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)}
    )


# Root endpoint
@app.get("/")
async def root():
    """API health check and info"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "operational",
        "docs": "/docs"
    }


@app.get("/api")
async def api_root():
    """API root endpoint"""
    return {"message": "DAO Citizenship API"}


# Include routers with /api prefix
app.include_router(auth_router, prefix="/api")
app.include_router(wallet_router, prefix="/api")
app.include_router(membership_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(governance_router, prefix="/api")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "timestamp": __import__('datetime').datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )

