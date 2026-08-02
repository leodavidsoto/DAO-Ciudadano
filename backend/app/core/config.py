"""
Core Configuration Module
Centralized configuration using Pydantic Settings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List, Literal, cast
from functools import lru_cache
import os


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # App
    APP_NAME: str = "DAO Ciudadana API"
    APP_VERSION: str = "1.0.0"
    # Safe defaults: an unconfigured server is production-like and cannot
    # create memberships. Local/demo environments must opt in explicitly.
    APP_ENV: Literal["development", "test", "demo", "production"] = cast(
        Literal["development", "test", "demo", "production"],
        os.environ.get("APP_ENV", "production"),
    )
    MINT_MODE: Literal["disabled", "demo", "onchain"] = cast(
        Literal["disabled", "demo", "onchain"],
        os.environ.get("MINT_MODE", "disabled"),
    )
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
    SIWE_CHALLENGE_EXPIRE_SECONDS: int = int(os.environ.get('SIWE_CHALLENGE_EXPIRE_SECONDS', '300'))
    SIWE_DOMAIN: str = os.environ.get('SIWE_DOMAIN', 'localhost')
    SIWE_URI: str = os.environ.get('SIWE_URI', 'http://localhost:3000')
    SIWE_CHAIN_ID: int = int(os.environ.get('SIWE_CHAIN_ID', '11155111'))

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

    # === Emisor de credenciales ZK (ADR-001, D-2) ===
    # Llave que firma la credencial EIP-191 que el cliente verifica contra
    # REACT_APP_ZK_IDENTITY_ISSUER_ADDRESS. Distinta de MINTER_PRIVATE_KEY a
    # propósito: firmar credenciales y enviar transacciones son poderes
    # separados, y una llave comprometida no debe dar ambos.
    IDENTITY_ISSUER_PRIVATE_KEY: str = os.environ.get('IDENTITY_ISSUER_PRIVATE_KEY', '')

    # Segundos de validez de un grant civil de un solo uso. Corto a propósito:
    # es la ventana en la que una verificación civil puede canjearse.
    IDENTITY_GRANT_TTL_SECONDS: int = int(os.environ.get('IDENTITY_GRANT_TTL_SECONDS', '300'))

    # === Transporte ERC-4337 (ADR-001, D-1) ===
    # Apagado por defecto: mientras no se decida la implementacion de cuenta
    # inteligente no se pueden firmar UserOperations, y el relayer EOA sigue
    # siendo el camino probado.
    ERC4337_ENABLED: bool = os.environ.get('ERC4337_ENABLED', 'false').lower() == 'true'
    BUNDLER_RPC_URL: str = os.environ.get('BUNDLER_RPC_URL', '')
    ERC4337_ENTRYPOINT_VERSION: str = os.environ.get('ERC4337_ENTRYPOINT_VERSION', '0.7')
    ERC4337_ACCOUNT_ADDRESS: str = os.environ.get('ERC4337_ACCOUNT_ADDRESS', '')
    # SimpleAccount | safe | kernel. Determina como se firma la UserOperation.
    ERC4337_ACCOUNT_IMPLEMENTATION: str = os.environ.get('ERC4337_ACCOUNT_IMPLEMENTATION', '')
    # Direccion del Safe4337Module. Es el verifyingContract del dominio
    # EIP-712: si falta o es otra, el modulo rechaza la firma.
    SAFE_4337_MODULE_ADDRESS: str = os.environ.get('SAFE_4337_MODULE_ADDRESS', '')
    # Llave del propietario de la Safe. Solo sirve para umbral 1.
    SAFE_OWNER_PRIVATE_KEY: str = os.environ.get('SAFE_OWNER_PRIVATE_KEY', '')
    # Direccion del Paymaster (informativa para el cliente).
    ERC4337_PAYMASTER_ADDRESS: str = os.environ.get('ERC4337_PAYMASTER_ADDRESS', '')
    # El nombre del metodo de patrocinio varia entre proveedores.
    PAYMASTER_SPONSOR_METHOD: str = os.environ.get('PAYMASTER_SPONSOR_METHOD', 'pm_sponsorUserOperation')

    # Contrato MACICoordinator desplegado. El cliente lo fija y contrasta.
    MACI_COORDINATOR_ADDRESS: str = os.environ.get('MACI_COORDINATOR_ADDRESS', '')

    # Proveedor civil real que emite los grants. Vacío = no hay ninguno, y la
    # emisión de credenciales falla cerrado en producción. Los simuladores de
    # ClaveÚnica/NFC/liveness NUNCA deben emitir grants.
    IDENTITY_PROVIDER: str = os.environ.get('IDENTITY_PROVIDER', '')

    # External Services
    EMERGENT_LLM_KEY: Optional[str] = None
    
    # Membership verification source for governance endpoints.
    # "mongo": members collection is the source of truth (current state).
    # "onchain": hasMembership() on the SBT contract (ROADMAP Fase 1.5,
    # not implemented yet — selecting it fails loudly instead of simulating).
    MEMBERSHIP_SOURCE: Literal["mongo", "onchain"] = cast(
        Literal["mongo", "onchain"],
        os.environ.get('MEMBERSHIP_SOURCE', 'mongo'),
    )
    
    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_SENSITIVE_REQUESTS: int = 30
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    # Lista explícita de IP/CIDR de proxies autorizados a aportar
    # X-Forwarded-For. Vacía por defecto: el peer TCP es la única identidad
    # confiable y un cliente no puede evadir límites inventando la cabecera.
    TRUSTED_PROXY_IPS: str = os.environ.get('TRUSTED_PROXY_IPS', '')

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"
    
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
