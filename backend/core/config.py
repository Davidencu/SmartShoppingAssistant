from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    supabase_anon_key: str
    lemonsqueezy_api_key: str
    lemonsqueezy_variant_id: str
    lemonsqueezy_webhook_secret: str
    lithic_api_key: str
    lithic_webhook_secret: str
    tavily_api_key: str
    jina_api_key: str
    gemini_api_key: str
    browserbase_api_key: str
    browserbase_project_id: str
    jwt_secret: str
    rp_id: str = "localhost"
    rp_name: str = "SmartShop Assistant"
    frontend_origin: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
