from pathlib import Path
from functools import lru_cache
import secrets
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_env: str = "local"
    database_url: str = "sqlite:///./data/recruiter.db"
    checkpoint_url: str = "sqlite:///./data/checkpoints.db"
    auth_mode: str = "local"
    ai_mode: str = "demo"
    external_mode: str = "preview"
    app_secret: str = ""
    frontend_url: str = "http://localhost:5173"
    api_url: str = "http://localhost:8000"
    local_storage_dir: str = "./data/documents"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    storage_bucket: str = "resumes"
    gemini_api_key: str = ""
    gemini_model: str = ""
    resend_api_key: str = ""
    resend_test_inbox: str = ""
    calendar_allowed_emails: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/integrations/calendar/callback"
    token_encryption_key: str = ""
    enable_demo_reset: bool = False
    worker_enabled: bool = True
    seed_demo: bool = True

    @field_validator("database_url", mode="before")
    @classmethod
    def postgres_driver(cls, value):
        if isinstance(value, str):
            if value.startswith("postgres://"):
                value = "postgresql://" + value.removeprefix("postgres://")
            if value.startswith("postgresql://"):
                value = "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    @field_validator("checkpoint_url", mode="before")
    @classmethod
    def checkpoint_driver(cls, value):
        if isinstance(value, str) and value.startswith("postgres://"):
            return "postgresql://" + value.removeprefix("postgres://")
        return value

    @model_validator(mode="after")
    def safety(self):
        if self.app_env not in {"local", "test", "production"}:
            raise ValueError("APP_ENV must be local, test, or production")
        if self.auth_mode not in {"local", "supabase"}:
            raise ValueError("AUTH_MODE must be local or supabase")
        if self.auth_mode == "local":
            for url in (self.database_url, self.checkpoint_url):
                if (urlsplit(url).hostname or "").lower().endswith((".supabase.co", ".supabase.com")):
                    raise ValueError("Set AUTH_MODE=supabase before connecting to a hosted Supabase database")
        if self.ai_mode not in {"demo", "gemini"}:
            raise ValueError("AI_MODE must be demo or gemini")
        if self.external_mode not in {"preview", "live"}:
            raise ValueError("EXTERNAL_MODE must be preview or live")
        if self.token_encryption_key:
            from cryptography.fernet import Fernet
            try:
                Fernet(self.token_encryption_key.encode())
            except (ValueError, TypeError):
                raise ValueError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key")
        if self.app_env == "production":
            if self.auth_mode != "supabase" or not self.supabase_url or not self.supabase_anon_key:
                raise ValueError("Production requires Supabase authentication")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
            if not self.checkpoint_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("Production requires persistent PostgreSQL workflow checkpoints")
            if not self.supabase_service_role_key or len(self.app_secret) < 32:
                raise ValueError("Production requires private Supabase storage and a strong APP_SECRET")
            if self.external_mode == "live" and not self.token_encryption_key:
                raise ValueError("Live production integrations require TOKEN_ENCRYPTION_KEY")
        if not self.app_secret:
            if self.app_env == "test":
                self.app_secret = "test-only-secret-which-is-never-used-in-production"
            else:
                path = Path("data/.local-secret")
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
                self.app_secret = path.read_text(encoding="utf-8").strip()
        return self


@lru_cache
def get_settings():
    return Settings()
