from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    webhook_micro_batch_threshold: int = 10
    webhook_micro_batch_interval_seconds: int = 300
    database_url: str = "sqlite+aiosqlite:///./reconcile.db"
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    llm_timeout_seconds: int = 10
    llm_max_retries: int = 1

    # --- Security & Validation ---
    api_key: str = ""                          # X-API-Key for protected routes
    api_key_enabled: bool = False              # Toggle auth on/off (off for demo)
    rate_limit_capacity: int = 60              # Token bucket maximum burst capacity
    rate_limit_refill_rate: float = 1.0        # Tokens refilled per second (e.g. 1/s = 60/min)
    max_upload_size_bytes: int = 104_857_600   # 100 MB for large bank/ledger CSV files
    qa_max_question_length: int = 4000         # Max chars for QA input (accommodates detailed queries)
    redis_url: str = ""                        # Generic Redis URL (e.g. redis://..., rediss://..., AWS ElastiCache, Dragonfly, self-hosted)
    upstash_redis_rest_url: str = ""           # Optional Upstash Redis REST URL (HTTP/Serverless)
    upstash_redis_rest_token: str = ""         # Optional Upstash Redis REST Token
    cors_allowed_origins: str = "*"            # Comma-separated list of allowed origins or "*"
    use_fixtures: str = "0"                    # Testing/Demo mode: "1" = use synthetic fixtures, "0" = real Razorpay data

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.cors_allowed_origins or self.cors_allowed_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


settings = Settings()


