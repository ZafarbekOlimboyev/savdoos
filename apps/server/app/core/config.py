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

    # ── XPAY (xpay.kg) QR to'lov — kalitlar bo'lmasa integratsiya o'chiq ──
    xpay_base_url: str = "https://api.xpay.kg"
    xpay_client_id: str = ""
    xpay_client_secret: str = ""
    xpay_merchant_uuid: str = ""
    # Webhook uchun bizning ochiq manzil (Railway). Bo'sh bo'lsa callback yuborilmaydi.
    public_base_url: str = ""

    @property
    def xpay_enabled(self) -> bool:
        return bool(self.xpay_client_id and self.xpay_client_secret and self.xpay_merchant_uuid)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
