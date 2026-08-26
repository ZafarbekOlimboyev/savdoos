from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "dev-secret-change-me"  # bu ochiq (source'da) — production'da ishlatib bo'lmaydi


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Muhit: "dev" | "prod". Prod'da xavfsizlik cheklovlari yoqiladi (docs yopiladi, SECRET_KEY majburiy).
    app_env: str = "dev"
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
    # Ixtiyoriy IP-allowlist (vergul bilan). Berilса — vendor endpointlariга FAQAT shu IP'lardан
    # kirish mumkin (master-kalit sizib ketса ham himoya). Bo'sh = cheklovsiz.
    vendor_allowed_ips: str = ""

    @property
    def vendor_ip_list(self) -> list[str]:
        return [ip.strip() for ip in self.vendor_allowed_ips.split(",") if ip.strip()]

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
    # XPAY webhook HMAC-SHA256 siri (ixtiyoriy qo'shimcha himoya). Asosiy himoya — statusni
    # XPAY'дан server tomonда qayta so'rash; bu sir o'rnatilsa imzo ham tekshiriladi.
    xpay_webhook_secret: str = ""

    @property
    def xpay_enabled(self) -> bool:
        return bool(self.xpay_client_id and self.xpay_client_secret and self.xpay_merchant_uuid)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def insecure_secret(self) -> bool:
        """Standart (ochiq) JWT kaliti ishlatilyaptimi — token soxtalashtirishga imkon beradi."""
        return self.secret_key == DEFAULT_SECRET

    @property
    def is_production(self) -> bool:
        """Aniq APP_ENV=prod bo'lsa YOKI SQLite emas (Postgres) bo'lsa — production.
        Ikki shart: aniq flag afzal, lekin Postgres'да flag unutilsa ham himoya yoqiladi (fail-safe)."""
        return self.app_env.lower() in {"prod", "production"} or not self.database_url.startswith("sqlite")


settings = Settings()
