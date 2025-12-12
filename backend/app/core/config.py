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
    DEBUG: bool = False
    
    # Database
    MONGO_URL: str
    DB_NAME: str = "dao_ciudadana"
    
    # CORS
    CORS_ORIGINS: str = "*"
    
    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # External Services
    EMERGENT_LLM_KEY: Optional[str] = None
    
    # Rate Limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    
    @property
    def cors_origins_list(self) -> List[str]:
        return self.CORS_ORIGINS.split(",")
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()


settings = get_settings()
