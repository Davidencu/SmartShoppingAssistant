from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    supabase_url: str
    supabase_service_role_key: str

    gemini_api_key: str = ""
    tavily_api_key: str = ""
    jina_api_key: str = ""
    lithic_api_key: str = ""
    lithic_webhook_secret: str = ""
    lemonsqueezy_api_key: str = ""
    lemonsqueezy_webhook_secret: str = ""
    browserbase_api_key: str = ""
    browserbase_project_id: str = ""

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
