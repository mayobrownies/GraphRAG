"""
Load settings of env and hold tuning values (i.e. max upload size, chunk size/overlap, traversal hops, etc.)
Other modules should read settings from here
Values come from the environment first, then the repo-root .env (missing in Docker/Render, which is fine)
Secrets and URLs default to None so the app and unit tests import without a .env; code that needs one checks it when used
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    # extra="ignore": the shared .env also holds frontend and tooling keys (VITE_*, GOOGLE_*, AURA_*)
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    app_env: str = "development"
    log_level: str = "info"
    # Comma-separated, as in .env and render.yaml; use cors_origin_list
    cors_origins: str = ""

    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str | None = None

    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str = "graphrag_chunks"

    ollama_base_url: str | None = None
    ollama_llm_model: str | None = None
    ollama_embed_model: str | None = None

    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    supabase_secret_key: str | None = None
    supabase_jwks_url: str | None = None
    supabase_storage_bucket: str | None = None

    # Tuning
    max_upload_mb: int = 20
    # Lifetime of a download link for a source PDF
    signed_url_expires_s: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    # Cached so the environment is read once; tests override this dependency or call get_settings.cache_clear()
    return Settings()
