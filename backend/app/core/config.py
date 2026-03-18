from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_provider: str = "auto"
    database_url: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE_URL", "SUPABASE_DB_URL"),
    )
    firebase_project_id: str = "animalitos-90b5c"
    firebase_private_key: str = ""
    firebase_client_email: str = ""
    firebase_credentials_file: str = ""

    jwt_secret_key: str = Field(
        default="super-secret-key-change-in-production",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "JWT_SECRET"),
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    app_env: str = "development"
    debug: bool = True
    app_timezone: str = "America/Caracas"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_email: str = "admin@animalitos.com"
    bootstrap_admin_full_name: str = "Administrator"
    bootstrap_admin_password: str = ""
    bootstrap_admin_token: str = ""
    allow_insecure_dev_admin: bool = False

    scheduler_interval_minutes: int = 1
    scheduler_lookback_minutes: int = 18
    scheduler_min_gap_minutes: int = 8
    backfill_default_days: int = 90
    analytics_default_days: int = 30
    quality_default_days: int = 14
    rate_limit_window_seconds: int = 60
    rate_limit_auth_attempts: int = 8
    rate_limit_admin_attempts: int = 24
    prediction_default_top_n: int = 5
    prediction_auto_send_on_refresh: bool = True
    admin_audit_default_limit: int = 50
    results_cache_ttl_seconds: int = 180
    use_external_scheduler: bool = Field(
        default=False,
        validation_alias=AliasChoices("USE_EXTERNAL_SCHEDULER", "USE_CLOUD_SCHEDULER"),
    )
    scheduler_service_token: str = ""
    backend_public_url: str = ""
    frontend_public_url: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def use_postgres(self) -> bool:
        provider = self.database_provider.lower()
        return bool(self.database_url and provider in {"auto", "postgres", "supabase"})

    @property
    def use_firebase(self) -> bool:
        provider = self.database_provider.lower()
        return provider in {"auto", "firebase"} and not self.use_postgres

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
