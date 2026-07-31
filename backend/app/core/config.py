"""
Core Configuration Module
Centralized configuration using Pydantic Settings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List
from functools import lru_cache
import os


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # App
    APP_NAME: str = "DAO Ciudadana API"
    APP_VERSION: str = "1.0.0"
    # Safe default: production-off. Enable locally with DEBUG=true (exposes /docs).
    DEBUG: bool = os.environ.get('DEBUG', 'false').lower() == 'true'
    
    # Database - with fallback
    MONGO_URL: str = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    DB_NAME: str = os.environ.get('DB_NAME', 'dao_ciudadana')
    
    # CORS - must be set explicitly in production. Empty default = no cross-origin allowed.
    CORS_ORIGINS: str = os.environ.get('CORS_ORIGINS', '')
    # Optional regex for dynamic origins (e.g. Netlify deploy previews, whose
    # subdomain changes on every build). Scope it to your own domain; never '.*'.
    CORS_ORIGIN_REGEX: str = os.environ.get('CORS_ORIGIN_REGEX', '')
    
    # Security
    SECRET_KEY: str = os.environ.get('SECRET_KEY', 'dev-secret-key')
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Pepper para el hash de identidad HMAC (app/core/identity.py, D-2).
    # Nunca en el repo. Sin esto, en producción (DEBUG=false) el registro
    # y login fallan en vez de usar un hash sin sal.
    IDENTITY_PEPPER: str = os.environ.get('IDENTITY_PEPPER', '')

    # Llave Fernet para cifrar PII en reposo (app/core/crypto.py).
    # Generar con: python -c "from app.core.crypto import generate_key; print(generate_key())"
    PII_ENCRYPTION_KEY: str = os.environ.get('PII_ENCRYPTION_KEY', '')

    # Segundos de validez de una sesión de wallet (JWT emitido tras SIWE).
    SESSION_TOKEN_EXPIRE_SECONDS: int = int(os.environ.get('SESSION_TOKEN_EXPIRE_SECONDS', '3600'))

    # Si es True, /governance/vote rechaza votos sin firma EIP-712 válida.
    # Se deja en False por defecto para no romper el flujo actual hasta
    # confirmar que la firma funciona end-to-end desde una wallet real.
    SIGNED_BALLOTS_REQUIRED: bool = os.environ.get('SIGNED_BALLOTS_REQUIRED', 'false').lower() == 'true'

    # Minteo real on-chain (app/services/chain_service.py). Sin las tres,
    # ChainService.enabled es False y el minteo sigue en modo demo (sin
    # tx_hash), nunca con un fallback silencioso a un tx_hash inventado.
    SEPOLIA_RPC_URL: str = os.environ.get('SEPOLIA_RPC_URL', '')
    SBT_CONTRACT_ADDRESS: str = os.environ.get('SBT_CONTRACT_ADDRESS', '')
    MINTER_PRIVATE_KEY: str = os.environ.get('MINTER_PRIVATE_KEY', '')

    # External Services
    EMERGENT_LLM_KEY: Optional[str] = None
    
    # Membership verification source for governance endpoints.
    # "mongo": members collection is the source of truth (current state).
    # "onchain": hasMembership() on the SBT contract (ROADMAP Fase 1.5,
    # not implemented yet — selecting it fails loudly instead of simulating).
    MEMBERSHIP_SOURCE: str = os.environ.get('MEMBERSHIP_SOURCE', 'mongo')
    
    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    
    @property
    def cors_origins_list(self) -> List[str]:
        if not self.CORS_ORIGINS:
            return []
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()


settings = get_settings()

