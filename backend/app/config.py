from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_service_key: str
    supabase_bucket: str = "documents"

    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "chunks"

    ollama_base_url: str = "http://ollama:11434"
    llm_model: str = "qwen3.5:0.8b"
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768

    max_upload_mb: int = 25
    chunk_size: int = 1000
    chunk_overlap: int = 150
    max_hops: int = 2  # requirement 2.2: one or two hops initially
    top_k: int = 5
    min_score: float = 0.3
    cors_origins: str = "http://localhost:3000,http://localhost:5173"


GLOBAL_SCOPE = "global"


@lru_cache
def get_settings() -> Settings:
    return Settings()
