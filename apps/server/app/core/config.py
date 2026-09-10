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
    # Ixtiyoriy 2FA (TOTP, base32 sir). Berilса — portalга kirishда kalitdан tashqari
    # Google Authenticator kodi ham talab qilinadi. Bo'sh = 2FA o'chiq. (tools/gen_totp.py)
    vendor_totp_secret: str = ""

    # Vendor sessiyasi muddati (soat). Ilgari 12 soat QATTIQ yozilgan edi va uni
    # bekor qilishning yagona yo'li master kalitni almashtirish edi. Endi sessiya
    # bazada qayd etiladi va alohida bekor qilinadi, muddat esa sozlanadi.
    vendor_session_hours: int = 2

    @property
    def vendor_2fa_on(self) -> bool:
        return bool(self.vendor_totp_secret.strip())

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
    def on_managed_platform(self) -> bool:
        """Boshqariladigan hosting (Railway) ichida ishlayapmizmi.

        Railway har konteynerga o'z o'zgaruvchilarini QO'YADI (RAILWAY_*). Bu bizning
        konfiguratsiyamizga bog'liq EMAS — DATABASE_URL yo'qolsa ham qoladi."""
        import os as _os
        return any(_os.getenv(k) for k in (
            "RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME",
            "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_SERVICE_NAME",
        ))

    @property
    def is_production(self) -> bool:
        """Production'mi — UCH mustaqil signal (istalgan biri yetarli).

        1) aniq APP_ENV=prod|production      — afzal ko'riladigan, oshkora usul
        2) boshqariladigan platforma (RAILWAY_*) — DATABASE_URL BUZILSA HAM qoladi
        3) SQLite emas (ya'ni Postgres)      — eski fail-safe

        NEGA 2-SIGNAL QO'SHILDI (bu jiddiy tuzatish): ilgari production FAQAT
        `database_url` satridan CHIQARILARDI. Ya'ni Railway'da DATABASE_URL o'zgaruvchisi
        yo'qolsa (Postgres servisi uzilsa, havola buzilsa, muhit qayta yaratilsa) konteyner
        YIQILMASDAN ko'tarilardi va BIR VAQTNING O'ZIDA:
            · konteyner ichidagi vaqtinchalik SQLite faylga yozardi (har deploy'da YO'QOLADI),
            · `is_production` False bo'lgani uchun JWT standart (manbada ochiq) kalit bilan
              imzolanardi — token soxtalashtirish mumkin,
            · /docs va /openapi.json OCHILARDI,
            · `app.seed` demo do'konni (PIN 1234/1111, parol demo1234) YARATARDI.
        Ya'ni bitta yo'qolgan o'zgaruvchi ochiq internetda demo do'kon ochib qo'yardi.
        Endi Railway'da bu holat production deb qoladi va main.py uni BALAND to'xtatadi."""
        return (self.app_env.lower() in {"prod", "production"}
                or self.on_managed_platform
                or not self.database_url.startswith("sqlite"))

    @property
    def production_on_sqlite(self) -> bool:
        """Production, LEKIN baza SQLite — ya'ni DATABASE_URL berilmagan/buzilgan.
        Bu holat JIM o'tkazilmaydi (main.py ishga tushishni to'xtatadi)."""
        return self.is_production and self.database_url.startswith("sqlite")


settings = Settings()
