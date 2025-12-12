"""
Core Configuration Module
Centralized configuration using Pydantic Settings
"""
from pydantic_settings import BaseSettings
from typing import Optional, List
from functools import lru_cache
import os


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # App
    APP_NAME: str = "DAO Ciudadana API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True  # Enable docs for now
    
    # Database - with fallback
    MONGO_URL: str = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
    DB_NAME: str = os.environ.get('DB_NAME', 'dao_ciudadana')
    
    # CORS - Allow all for now to debug
    CORS_ORIGINS: str = os.environ.get('CORS_ORIGINS', '*')
    
    # Security
    SECRET_KEY: str = os.environ.get('SECRET_KEY', 'dev-secret-key')
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # External Services
    EMERGENT_LLM_KEY: Optional[str] = None
    
    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    
    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()


settings = get_settings()

