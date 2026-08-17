from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Standart — SQLite (demo, hech narsa o'rnatilmaydi). Production uchun .env da Postgres bering.
    database_url: str = "sqlite:///./savdoos.db"
    secret_key: str = "dev-secret-change-me"
    algorithm: str = "HS256"
    access_token_minutes: int = 720
    refresh_token_days: int = 30
    # "*" — paketlangan desktop ilova (file://) ham ulanishi uchun. Auth Bearer token orqali.
    cors_origins: str = "*"
    redis_url: str = "redis://localhost:6379/0"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
