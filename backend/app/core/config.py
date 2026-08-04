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
    DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"

    # Database - with fallback
    MONGO_URL: str = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    DB_NAME: str = os.environ.get("DB_NAME", "dao_ciudadana")

    # CORS - must be set explicitly in production. Empty default = no cross-origin allowed.
    CORS_ORIGINS: str = os.environ.get("CORS_ORIGINS", "")
    # Optional regex for dynamic origins (e.g. Netlify deploy previews, whose
    # subdomain changes on every build). Scope it to your own domain; never '.*'.
    CORS_ORIGIN_REGEX: str = os.environ.get("CORS_ORIGIN_REGEX", "")

    # Security
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Pepper para el hash de identidad HMAC (app/core/identity.py, D-2).
    # Nunca en el repo. Sin esto, en producción (DEBUG=false) el registro
    # y login fallan en vez de usar un hash sin sal.
    IDENTITY_PEPPER: str = os.environ.get("IDENTITY_PEPPER", "")

    # Llave Fernet para cifrar PII en reposo (app/core/crypto.py).
    # Generar con: python -c "from app.core.crypto import generate_key; print(generate_key())"
    PII_ENCRYPTION_KEY: str = os.environ.get("PII_ENCRYPTION_KEY", "")
    # Rotación (ROADMAP 1.3/1.4): lista separada por comas, de la más NUEVA a
    # la más vieja. Se cifra con la primera y se descifra con cualquiera, así
    # que publicar una llave nueva no invalida lo ya guardado. Ver
    # scripts/pii_maintenance.py para reescribir los registros pendientes.
    PII_ENCRYPTION_KEYS: str = os.environ.get("PII_ENCRYPTION_KEYS", "")
    # Pepper anterior durante una rotación de IDENTITY_PEPPER. Solo se usa
    # para BUSCAR registros aún no reindexados; nunca para escribir. Retirar
    # en cuanto `pii_maintenance.py status` reporte 0 pendientes.
    IDENTITY_PEPPER_PREVIOUS: str = os.environ.get("IDENTITY_PEPPER_PREVIOUS", "")

    # Segundos de validez de una sesión de wallet (JWT emitido tras SIWE).
    SESSION_TOKEN_EXPIRE_SECONDS: int = int(
        os.environ.get("SESSION_TOKEN_EXPIRE_SECONDS", "3600")
    )

    # === Transporte de la sesión web en cookies (tarea 1.13) ===
    # El JWT viaja además en una cookie HttpOnly para que el frontend no
    # tenga que guardarlo en localStorage (legible por cualquier XSS).
    # Vacío = derivado del entorno; ver session_cookie_samesite/secure.
    SESSION_COOKIE_NAME: str = os.environ.get("SESSION_COOKIE_NAME", "dao_session")
    SESSION_COOKIE_SAMESITE: str = os.environ.get("SESSION_COOKIE_SAMESITE", "")
    SESSION_COOKIE_SECURE: str = os.environ.get("SESSION_COOKIE_SECURE", "")
    # Solo si el frontend y el backend comparten dominio registrable. Vacío =
    # cookie de host (la opción más estrecha y la correcta para Netlify+Render).
    SESSION_COOKIE_DOMAIN: str = os.environ.get("SESSION_COOKIE_DOMAIN", "")
    # Cookie legible por JS a propósito: es la mitad del doble envío CSRF, y su
    # valor no sirve para autenticar por sí solo.
    CSRF_COOKIE_NAME: str = os.environ.get("CSRF_COOKIE_NAME", "dao_csrf")
    SIWE_CHALLENGE_EXPIRE_SECONDS: int = int(
        os.environ.get("SIWE_CHALLENGE_EXPIRE_SECONDS", "300")
    )
    SIWE_DOMAIN: str = os.environ.get("SIWE_DOMAIN", "localhost")
    SIWE_URI: str = os.environ.get("SIWE_URI", "http://localhost:3000")
    SIWE_CHAIN_ID: int = int(os.environ.get("SIWE_CHAIN_ID", "11155111"))

    # Si es True, /governance/vote rechaza votos sin firma EIP-712 válida.
    # Se deja en False por defecto para no romper el flujo actual hasta
    # confirmar que la firma funciona end-to-end desde una wallet real.
    SIGNED_BALLOTS_REQUIRED: bool = (
        os.environ.get("SIGNED_BALLOTS_REQUIRED", "false").lower() == "true"
    )

    # Minteo real on-chain (app/services/chain_service.py). Sin las tres,
    # ChainService.enabled es False y el minteo sigue en modo demo (sin
    # tx_hash), nunca con un fallback silencioso a un tx_hash inventado.
    SEPOLIA_RPC_URL: str = os.environ.get("SEPOLIA_RPC_URL", "")
    SBT_CONTRACT_ADDRESS: str = os.environ.get("SBT_CONTRACT_ADDRESS", "")
    MINTER_PRIVATE_KEY: str = os.environ.get("MINTER_PRIVATE_KEY", "")

    # === Tesorería real (ROADMAP 3.6, app/services/treasury_service.py) ===
    # Dirección del Safe cuyo balance se lee. Vacía = la tesorería se reporta
    # como no configurada, nunca con números inventados.
    TREASURY_SAFE_ADDRESS: str = os.environ.get("TREASURY_SAFE_ADDRESS", "")
    # RPC propio de la tesorería. Vacío = se reutiliza SEPOLIA_RPC_URL. Se
    # separa porque el Safe puede vivir en otra red que el contrato del SBT.
    TREASURY_RPC_URL: str = os.environ.get("TREASURY_RPC_URL", "")
    # Tokens ERC-20 del Safe que se consultan, por dirección de contrato y
    # separados por comas. Vacío = solo se lee el ETH nativo, y la respuesta
    # lo declara en `assets_covered` para que el total no parezca completo.
    # Los decimales y el símbolo se leen de la cadena, nunca se suponen.
    TREASURY_TOKENS: str = os.environ.get("TREASURY_TOKENS", "")
    # Tope de tokens consultados por foto: cada uno son 3 llamadas al RPC y el
    # endpoint es público. Una lista larga lo convertiría en un amplificador.
    TREASURY_MAX_TOKENS: int = int(os.environ.get("TREASURY_MAX_TOKENS", "20"))
    # El endpoint es público: sin caché, refrescar el dashboard en bucle
    # convierte a cualquier visitante en un amplificador contra el RPC.
    TREASURY_CACHE_TTL_SECONDS: int = int(
        os.environ.get("TREASURY_CACHE_TTL_SECONDS", "60")
    )
    # coingecko | binance | none. `none` deshabilita el precio: los balances
    # se siguen publicando en ETH, que es el dato que sí se leyó de la cadena.
    ETH_PRICE_PROVIDER: str = os.environ.get("ETH_PRICE_PROVIDER", "coingecko")
    # Override del endpoint (proxy propio, plan de pago, mirror). Debe
    # responder el mismo JSON que el proveedor declarado arriba.
    ETH_PRICE_API_URL: str = os.environ.get("ETH_PRICE_API_URL", "")
    ETH_PRICE_CACHE_TTL_SECONDS: int = int(
        os.environ.get("ETH_PRICE_CACHE_TTL_SECONDS", "300")
    )
    # Cuánto se admite servir el último precio conocido marcándolo `stale`
    # cuando el proveedor falla. Pasado esto, el precio se reporta ausente.
    ETH_PRICE_STALE_MAX_SECONDS: int = int(
        os.environ.get("ETH_PRICE_STALE_MAX_SECONDS", "3600")
    )

    # === Emisor de credenciales ZK (ADR-001, D-2) ===
    # Llave que firma la credencial EIP-191 que el cliente verifica contra
    # REACT_APP_ZK_IDENTITY_ISSUER_ADDRESS. Distinta de MINTER_PRIVATE_KEY a
    # propósito: firmar credenciales y enviar transacciones son poderes
    # separados, y una llave comprometida no debe dar ambos.
    IDENTITY_ISSUER_PRIVATE_KEY: str = os.environ.get("IDENTITY_ISSUER_PRIVATE_KEY", "")

    # Segundos de validez de un grant civil de un solo uso. Corto a propósito:
    # es la ventana en la que una verificación civil puede canjearse.
    IDENTITY_GRANT_TTL_SECONDS: int = int(
        os.environ.get("IDENTITY_GRANT_TTL_SECONDS", "300")
    )

    # === Retención de datos (ROADMAP 1.4, app/core/retention.py) ===
    # Días que se conserva el digest de un grant DESPUÉS de expirar, para
    # poder investigar un canje anómalo. 0 = conservar indefinidamente.
    IDENTITY_GRANT_RETENTION_DAYS: int = int(
        os.environ.get("IDENTITY_GRANT_RETENTION_DAYS", "30")
    )
    # Borrado de registros de ciudadanos inactivos. 0 = DESACTIVADO, y es el
    # valor correcto por defecto: eliminar el registro civil de una persona es
    # una decisión de gobernanza, no un TTL que alguien configuró de paso.
    INACTIVE_USER_RETENTION_DAYS: int = int(
        os.environ.get("INACTIVE_USER_RETENTION_DAYS", "0")
    )

    # === Transporte ERC-4337 (ADR-001, D-1) ===
    # Apagado por defecto: mientras no se decida la implementacion de cuenta
    # inteligente no se pueden firmar UserOperations, y el relayer EOA sigue
    # siendo el camino probado.
    ERC4337_ENABLED: bool = os.environ.get("ERC4337_ENABLED", "false").lower() == "true"
    BUNDLER_RPC_URL: str = os.environ.get("BUNDLER_RPC_URL", "")
    ERC4337_ENTRYPOINT_VERSION: str = os.environ.get(
        "ERC4337_ENTRYPOINT_VERSION", "0.7"
    )
    ERC4337_ACCOUNT_ADDRESS: str = os.environ.get("ERC4337_ACCOUNT_ADDRESS", "")
    # SimpleAccount | safe | kernel. Determina como se firma la UserOperation.
    ERC4337_ACCOUNT_IMPLEMENTATION: str = os.environ.get(
        "ERC4337_ACCOUNT_IMPLEMENTATION", ""
    )
    # Direccion del Safe4337Module. Es el verifyingContract del dominio
    # EIP-712: si falta o es otra, el modulo rechaza la firma.
    SAFE_4337_MODULE_ADDRESS: str = os.environ.get("SAFE_4337_MODULE_ADDRESS", "")
    # Llave del propietario de la Safe. Solo sirve para umbral 1.
    SAFE_OWNER_PRIVATE_KEY: str = os.environ.get("SAFE_OWNER_PRIVATE_KEY", "")
    # Direccion del Paymaster (informativa para el cliente).
    ERC4337_PAYMASTER_ADDRESS: str = os.environ.get("ERC4337_PAYMASTER_ADDRESS", "")
    # El nombre del metodo de patrocinio varia entre proveedores.
    PAYMASTER_SPONSOR_METHOD: str = os.environ.get(
        "PAYMASTER_SPONSOR_METHOD", "pm_sponsorUserOperation"
    )

    # Contrato MACICoordinator desplegado. El cliente lo fija y contrasta.
    MACI_COORDINATOR_ADDRESS: str = os.environ.get("MACI_COORDINATOR_ADDRESS", "")

    # Proveedor civil real que emite los grants. Vacío = no hay ninguno, y la
    # emisión de credenciales falla cerrado en producción. Los simuladores de
    # ClaveÚnica/NFC/liveness NUNCA deben emitir grants.
    IDENTITY_PROVIDER: str = os.environ.get("IDENTITY_PROVIDER", "")

    # === ClaveÚnica / OIDC (ROADMAP 4.1) ===
    # NINGÚN valor por defecto, tampoco los endpoints: los entrega la División
    # de Gobierno Digital al habilitar el cliente, y escribir aquí una URL "de
    # memoria" sería exactamente inventar configuración de un tercero. Sin
    # estos valores el flujo responde 503 en cualquier entorno.
    CLAVE_UNICA_CLIENT_ID: str = os.environ.get("CLAVE_UNICA_CLIENT_ID", "")
    CLAVE_UNICA_CLIENT_SECRET: str = os.environ.get("CLAVE_UNICA_CLIENT_SECRET", "")
    # Debe coincidir EXACTAMENTE con la registrada ante el proveedor.
    CLAVE_UNICA_REDIRECT_URI: str = os.environ.get("CLAVE_UNICA_REDIRECT_URI", "")
    CLAVE_UNICA_ISSUER: str = os.environ.get("CLAVE_UNICA_ISSUER", "")
    CLAVE_UNICA_AUTHORIZATION_ENDPOINT: str = os.environ.get(
        "CLAVE_UNICA_AUTHORIZATION_ENDPOINT", ""
    )
    CLAVE_UNICA_TOKEN_ENDPOINT: str = os.environ.get("CLAVE_UNICA_TOKEN_ENDPOINT", "")
    CLAVE_UNICA_USERINFO_ENDPOINT: str = os.environ.get(
        "CLAVE_UNICA_USERINFO_ENDPOINT", ""
    )
    # RS256 exige JWKS; HS256 usa el client_secret. El algoritmo se FIJA aquí y
    # nunca se toma de la cabecera del token: dejar que el token elija su
    # propio algoritmo es la confusión de algoritmos, y con ella una firma
    # HMAC hecha con la clave pública se aceptaría como válida.
    CLAVE_UNICA_ID_TOKEN_ALG: str = os.environ.get("CLAVE_UNICA_ID_TOKEN_ALG", "RS256")
    CLAVE_UNICA_JWKS_URI: str = os.environ.get("CLAVE_UNICA_JWKS_URI", "")
    CLAVE_UNICA_SCOPES: str = os.environ.get("CLAVE_UNICA_SCOPES", "openid run name")
    # Ventana de vida de un intento de login (state/nonce/verifier PKCE).
    # Cookie HttpOnly que ata el canje al navegador que inició el flujo.
    CLAVE_UNICA_BINDING_COOKIE_NAME: str = os.environ.get(
        "CLAVE_UNICA_BINDING_COOKIE_NAME", "dao_cu_binding"
    )
    CLAVE_UNICA_LOGIN_TTL_SECONDS: int = int(
        os.environ.get("CLAVE_UNICA_LOGIN_TTL_SECONDS", "600")
    )

    # External Services
    EMERGENT_LLM_KEY: Optional[str] = None

    # Membership verification source for governance endpoints.
    # "mongo": members collection is the source of truth (current state).
    # "onchain": hasMembership() on the SBT contract (ROADMAP 3.1). Requires
    # SEPOLIA_RPC_URL y SBT_CONTRACT_ADDRESS; sin ellas falla cerrado.
    MEMBERSHIP_SOURCE: Literal["mongo", "onchain"] = cast(
        Literal["mongo", "onchain"],
        os.environ.get("MEMBERSHIP_SOURCE", "mongo"),
    )
    # Caché de hasMembership(). Corta a propósito: acota las llamadas RPC en el
    # camino caliente de votar sin que una revocación on-chain tarde en verse.
    # 0 desactiva la caché (cada verificación consulta la cadena).
    MEMBERSHIP_CACHE_TTL_SECONDS: int = int(
        os.environ.get("MEMBERSHIP_CACHE_TTL_SECONDS", "30")
    )
    MEMBERSHIP_CACHE_MAX_ENTRIES: int = int(
        os.environ.get("MEMBERSHIP_CACHE_MAX_ENTRIES", "5000")
    )

    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_SENSITIVE_REQUESTS: int = 30
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    # Lista explícita de IP/CIDR de proxies autorizados a aportar
    # X-Forwarded-For. Vacía por defecto: el peer TCP es la única identidad
    # confiable y un cliente no puede evadir límites inventando la cabecera.
    TRUSTED_PROXY_IPS: str = os.environ.get("TRUSTED_PROXY_IPS", "")
    # Redis compartido para el rate limiter (ROADMAP 3.8). Vacio = contadores
    # en memoria de proceso: el limite deja de ser global entre workers.
    REDIS_URL: str = os.environ.get("REDIS_URL", "")

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def session_cookie_samesite(self) -> str:
        """`lax` | `strict` | `none`, con un valor por defecto por entorno.

        En producción el frontend (Netlify) y la API (Render) están en sitios
        distintos, así que la cookie de sesión solo viaja con `SameSite=None`.
        En local ambos son `localhost` y `lax` es suficiente — y más estricto.
        """
        value = self.SESSION_COOKIE_SAMESITE.strip().lower()
        if value in {"lax", "strict", "none"}:
            return value
        return "none" if self.is_production else "lax"

    @property
    def session_cookie_secure(self) -> bool:
        """Los navegadores descartan `SameSite=None` sin `Secure`.

        Por eso el valor derivado nunca produce esa combinación; solo una
        configuración explícita puede hacerlo, y readiness la marca.
        """
        value = self.SESSION_COOKIE_SECURE.strip().lower()
        if value in {"true", "1", "yes"}:
            return True
        if value in {"false", "0", "no"}:
            return False
        return self.is_production or self.session_cookie_samesite == "none"

    @property
    def cors_origins_list(self) -> List[str]:
        if not self.CORS_ORIGINS:
            return []
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]

    # === Observabilidad (Fase 5.4) ===
    SENTRY_DSN: str = os.environ.get("SENTRY_DSN", "")
    # 1.0 envía el 100% de las transacciones: caro y ruidoso en producción.
    SENTRY_TRACES_SAMPLE_RATE: float = float(
        os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")
    )
    ENABLE_METRICS: bool = os.environ.get("ENABLE_METRICS", "false").lower() == "true"
    # Token para /metrics. Sin él, las métricas describen el sistema entero
    # (rutas, tráfico, latencias, errores) a cualquiera que las pida. En
    # producción, habilitar métricas sin token hace que el endpoint responda
    # 503 en vez de publicarse abierto.
    METRICS_TOKEN: str = os.environ.get("METRICS_TOKEN", "")

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
