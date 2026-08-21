from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEMANTIC_DB_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://semantic:semantic@localhost:5432/semantic_db"
    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024

    # Off by default: a default install builds no providers and never warns about an
    # absent collector. The endpoint stays local — nothing is exported off the machine.
    telemetry_enabled: bool = False
    otlp_endpoint: str = "http://localhost:4318"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
