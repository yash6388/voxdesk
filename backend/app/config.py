from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-secret-change-me-in-production-please"


class Settings(BaseSettings):
    """App settings, loaded from environment variables (and .env for local dev)."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "VoxDesk API"
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+asyncpg://voxdesk:voxdesk@localhost:5433/voxdesk"
    redis_url: str = "redis://localhost:6380/0"

    # --- Auth (business owners) ---
    jwt_secret: str = DEV_JWT_SECRET
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    # Cookie flags: in production (HTTPS) set COOKIE_SECURE=true; if the frontend and API
    # are on different sites, COOKIE_SAMESITE=none (requires secure).
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    public_app_url: str = "http://localhost:3000"

    # --- Tracing (Langfuse Cloud or self-hosted; off when keys are empty) ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # Langfuse's own snippet calls this LANGFUSE_BASE_URL; LANGFUSE_HOST is accepted too.
    # EU: https://cloud.langfuse.com · US: https://us.cloud.langfuse.com
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "LANGFUSE_HOST"),
    )

    # --- Rate limits (requests per minute) ---
    rate_limit_enabled: bool = True
    chat_limit_per_ip: int = 20
    chat_limit_per_business: int = 120
    auth_limit_per_ip: int = 10
    upload_limit_per_user: int = 20

    # --- LLM / embeddings (Gemini) ---
    google_api_key: str = ""
    chat_model: str = "gemini-2.5-flash"
    router_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "gemini-embedding-001"

    # --- Fallback LLM (any OpenAI-compatible provider: Groq, OpenRouter, Hugging Face…) ---
    # Used automatically when Gemini fails (e.g. free-tier 429). Off when no key is set.
    fallback_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "FALLBACK_API_KEY", "HF_TOKEN", "HUGGINGFACE_API_KEY", "HUGGINGFACEHUB_API_TOKEN"
        ),
    )
    fallback_base_url: str = "https://router.huggingface.co/v1"
    # Must support tool calling (the booking agent uses tools).
    fallback_model: str = "meta-llama/Llama-3.3-70B-Instruct"
    # "gemini" = Gemini first, fallback on failure; "fallback" = fallback model first,
    # Gemini as backup (handy while Gemini's free quota is exhausted).
    llm_primary: str = "gemini"
    # Circuit breaker on Gemini: after N outage errors in a row, skip it for the cooldown.
    breaker_failure_threshold: int = 3
    breaker_cooldown_seconds: float = 300
    embedding_dim: int = 768

    # --- RAG ---
    # Chosen by the evaluation suite (same 100-char overlap): 500-char chunks gave hybrid
    # Hit@1 86% / MRR 0.93 vs 82% / 0.90 at 1000 (and 73% at 1000 with 150 overlap).
    chunk_size: int = 500
    chunk_overlap: int = 100
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

    # --- A2A specialist agents ---
    agents_host: str = "127.0.0.1"
    knowledge_agent_port: int = 8101
    booking_agent_port: int = 8102
    knowledge_agent_url: str = "http://127.0.0.1:8101"
    booking_agent_url: str = "http://127.0.0.1:8102"
    # Shared secret the supervisor sends to the agents as `Authorization: Bearer <key>`.
    a2a_api_key: str = "dev-a2a-key-change-me"

    # --- Voice (Phase 4) ---
    # "local" = open-source models on this machine (free, private, no quotas);
    # "elevenlabs" = ElevenLabs API (best quality; needs ELEVENLABS_API_KEY).
    stt_provider: str = "local"
    tts_provider: str = "local"
    whisper_model: str = "base.en"  # tiny.en | base.en | small.en — bigger = better, slower
    kokoro_voice: str = "af_heart"
    voice_models_dir: str = "data/models"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    elevenlabs_tts_model: str = "eleven_flash_v2_5"  # lowest-latency ElevenLabs model
    elevenlabs_stt_model: str = "scribe_v1"

    def check_production_safety(self) -> None:
        """Refuse to run in production with development secrets."""
        if self.environment != "production":
            return
        if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
            raise RuntimeError("Set JWT_SECRET to a random value of at least 32 characters")
        if not self.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true in production (HTTPS)")

    @property
    def psycopg_url(self) -> str:
        """Plain postgres URL for libraries using psycopg (LangGraph checkpointer)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
