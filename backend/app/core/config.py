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
    # Domain shown in the message the wallet signs, so the person can see
    # which site is asking before approving.
    SIWE_DOMAIN: str = os.environ.get('SIWE_DOMAIN', 'DAO Ciudadana')
    
    # Liveness: minimum score to accept a capture as a live person.
    # Below this the flow must stop (ROADMAP 1.10 / audit N-9).
    LIVENESS_MIN_SCORE: float = float(os.environ.get('LIVENESS_MIN_SCORE', '0.75'))

    # Identity hashing (ADR 0001, D-2). Secreto de máximo valor: va en KMS,
    # nunca en el repositorio ni en la base. Si se filtra, las identidades ya
    # acuñadas quedan reversibles de forma retroactiva y sin rotación posible.
    IDENTITY_PEPPER: str = os.environ.get('IDENTITY_PEPPER', '')

    # PII encryption at rest (ROADMAP 1.4). Separada del pepper de identidad a
    # propósito: comprometer una no debe comprometer la otra.
    PII_ENCRYPTION_KEY: str = os.environ.get('PII_ENCRYPTION_KEY', '')

    # On-chain minting (ROADMAP 1.5, ADR 0001 D-1). Sin estas tres, el minteo
    # on-chain queda DESHABILITADO en vez de degradar a un registro en base.
    SEPOLIA_RPC_URL: str = os.environ.get('SEPOLIA_RPC_URL', '')
    SBT_CONTRACT_ADDRESS: str = os.environ.get('SBT_CONTRACT_ADDRESS', '')
    # Llave con MINTER_ROLE. En producción vive en un KMS, nunca aquí.
    MINTER_PRIVATE_KEY: str = os.environ.get('MINTER_PRIVATE_KEY', '')
    SBT_TOKEN_URI: str = os.environ.get('SBT_TOKEN_URI', '')
    # Chain the EIP-712 domain is bound to, so a ballot signed for one
    # network is not replayable on another.
    # Require every ballot to carry an EIP-712 signature. Off by default so
    # existing clients keep working; turn it on once the frontend signs
    # (ROADMAP 3.2). Until then the tally is only as trustworthy as the operator.
    SIGNED_BALLOTS_REQUIRED: bool = os.environ.get(
        'SIGNED_BALLOTS_REQUIRED', 'false').lower() == 'true'

    SBT_CHAIN_ID: int = int(os.environ.get('SBT_CHAIN_ID', '11155111'))

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

