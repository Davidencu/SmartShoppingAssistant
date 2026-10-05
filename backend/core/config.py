from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    supabase_anon_key: str
    tavily_api_key: str
    gemini_api_key: str
    openai_api_key: str = ""
    jwt_secret: str
    rp_id: str = "localhost"
    rp_name: str = "SmartShop Assistant"
    frontend_origin: str = "http://localhost:3000"
    admin_emails: str = ""        # comma-separated; empty = no admins (admin endpoints locked)
    proxy_username: str = ""      # residential proxy username (IPRoyal etc.)
    proxy_password: str = ""      # residential proxy password
    proxy_host: str = ""          # e.g. geo.iproyal.com
    proxy_port: str = ""          # e.g. 12321

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
