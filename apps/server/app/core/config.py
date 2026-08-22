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

    # ── Vendor admin — mijoz akkauntlarini ochish/parol tiklash. Kalit bo'lmasa o'chiq ──
    vendor_admin_key: str = ""

    # ── FCM push (Firebase) — kam-qoldiq bildirishnomasi. Xizmat kaliti JSON bo'lmasa o'chiq ──
    fcm_credentials_json: str = ""

    @property
    def fcm_enabled(self) -> bool:
        return bool(self.fcm_credentials_json.strip())

    # ── AI (nakladnoy/hujjatni o'qish). Kalit bo'lmasa demo rejim ──
    # Ikki provayder: Gemini (Google — bepul tier, kartasiz) yoki Claude (Anthropic).
    # Ikkalasidan biri sozlansa yetadi; ikkisi ham bo'lsa Gemini ustun.
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5"      # xohlasa arzonroq: claude-sonnet-5 / claude-haiku-4-5
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def ai_any(self) -> bool:
        return self.gemini_enabled or self.ai_enabled

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
