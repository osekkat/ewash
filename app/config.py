"""Environment configuration loaded via pydantic-settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Meta Cloud API
    meta_app_secret: str
    meta_verify_token: str
    meta_access_token: str
    meta_phone_number_id: str
    meta_waba_id: str = ""

    # Server
    port: int = 8000
    log_level: str = "INFO"
    public_base_url: str = ""
    railway_service_web_url: str = ""

    # v0.3 persistence/admin portal
    database_url: str = ""
    admin_password: str = ""
    admin_session_secret: str = ""
    admin_session_ttl_seconds: int = 60 * 60 * 24 * 7
    internal_cron_secret: str = ""
    admin_default_locale: str = "fr"


settings = Settings()
