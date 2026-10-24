import os
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_api_key: str = ""
    twilio_api_secret: str = ""
    twilio_phone_number: str = ""
    deepgram_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "outbound_calls"
    twilio_twiml_app_sid: str = ""
    whisper_model: str = "small"
    whisper_device: str = "cpu"  # "cpu" or "cuda"
    ai_provider: str = "groq"  # "groq" or "openai"
    transcription_provider: str = "deepgram"  # "deepgram" or "groq_whisper"

    # Model used for every Groq-backed agent call (analysis, domain
    # classification, project extraction, main in-call coaching) and the
    # OpenAI equivalent when ai_provider="openai" or a caller requests it
    # explicitly. groq_fast_model is only used by the suggestion agent's
    # low-latency project-intent gate, which always talks to Groq regardless
    # of ai_provider.
    groq_model: str = "openai/gpt-oss-120b"
    groq_fast_model: str = "openai/gpt-oss-20b"
    openai_model: str = "gpt-4o"
    suggestion_agent_enabled: bool = True
    base_url: str = "http://localhost:8080"

    # Lead research: runs in-process alongside live call audio, so the
    # concurrency cap is what keeps a batch of research from starving a call.
    lead_research_max_concurrent: int = 2
    lead_research_cache_days: int = 7
    lead_research_job_timeout_seconds: float = 150.0
    lead_research_fetch_timeout_seconds: float = 10.0
    lead_research_max_pages: int = 5
    lead_research_user_agent: str = "OutboundAI-LeadResearch/1.0 (+business research; respects robots.txt)"

    jwt_secret_key: str = "change-this-secret-key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720

    bootstrap_admin_name: str = "Admin"
    bootstrap_admin_email: str = "admin@outboundai.local"
    bootstrap_admin_password: str = "ChangeMe123!"

    class Config:
        env_file = str(BACKEND_DIR / ".env")
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
