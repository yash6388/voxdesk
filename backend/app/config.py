from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, loaded from environment variables (and .env for local dev)."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "VoxDesk API"
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+asyncpg://voxdesk:voxdesk@localhost:5433/voxdesk"
    redis_url: str = "redis://localhost:6380/0"

    # --- LLM / embeddings (Gemini) ---
    google_api_key: str = ""
    chat_model: str = "gemini-2.5-flash"
    router_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768

    # --- RAG ---
    chunk_size: int = 1000
    chunk_overlap: int = 150
    retrieval_top_k: int = 5
    retrieval_candidates: int = 20
    max_upload_mb: int = 10

    # --- Booking ---
    slot_step_minutes: int = 30
    booking_horizon_days: int = 60

    # --- MCP server (booking tools) ---
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8001
    mcp_url: str = "http://127.0.0.1:8001/mcp"
    # Shared secret clients must send as `Authorization: Bearer <key>`.
    mcp_api_key: str = "dev-mcp-key-change-me"

    @property
    def psycopg_url(self) -> str:
        """Plain postgres URL for libraries using psycopg (LangGraph checkpointer)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
