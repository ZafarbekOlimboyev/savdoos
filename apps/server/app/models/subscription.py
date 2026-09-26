"""Obuna platformasi (Phase 6A): tarif, obuna, to'lov reyestri, platforma admini, admin auditi.

NEGA ALOHIDA JADVALLAR (va nega `settings` EMAS)
================================================
Tarif va to'xtatish hozir `settings` da JSONB qator sifatida yashaydi
(`key='plan'`, `key='suspended'` — `api/v1/admin.py`). Obuna uchun bu yaramaydi:

  · «kimning obunasi ertaga tugaydi?» degan so'rov JSONB bo'ylab SKAN talab qiladi —
    indekslab bo'lmaydi, muddat esa har so'rovda kerak;
  · `ux_settings_company_key` loyihada MAJBURIY EMAS (`required_schema.OPTIONAL_UNIQUE_INDEXES`),
    ya'ni eski bazada bitta (company, key) uchun IKKI qator bo'lishi mumkin va mavjud
    o'quvchilar `.first()` ni TARTIBSIZ chaqiradi (`core/deps.py:40-42`, `api/v1/auth.py:79`) —
    pul bilan bog'liq holat bunday nodeterministik joyda yashamasligi kerak;
  · `settings` qatorida `created_at`/`updated_at` YO'Q (`PKMixin`), obuna esa vaqt bilan yashaydi.

FK SIYOSATI — LOYIHA QOIDASI
============================
⚠️  JONLI jadvalga FAQAT BITTA FK: `companies`. Boot'da `create_all` har FK uchun ota jadvalga
    SHARE ROW EXCLUSIVE qulf oladi — `products`/`sales`/`employees` ga FK bersak, o'sha
    jadvaldagi bitta ochiq yozuvchi butun boot'ni ushlab turardi (`models/receipt.py` izohi,
    `BINOS_PRODUCTION_DEPLOY_RUNBOOK.md` §1.3–1.4).
    Shu bois: `created_by_admin` → `platform_admins` (YANGI jadval, jonli yozuvchi YO'Q — xavfsiz),
    `admin_audit_log.company_id` esa FK'SIZ (sabab quyida).

ENUM EMAS, `String`
===================
⚠️  Holat ustunlari `SAEnum` EMAS. Sabab `models/enums.py` dagi Phase 6A blokida batafsil:
    native PG enum tipi `_ADDED_COLUMNS` yo'lida yaratilmaydi va yangi qiymat DDL talab qiladi.
    Qiymatlar `enums.py` dagi sinflar bilan ILOVA qatlamida tekshiriladi.

PUL — `Numeric`, `float` EMAS
=============================
⚠️  Barcha pul ustunlari `Numeric(14, 2)` va Python tomonda `Decimal`. Annotatsiya ham
    `Decimal` (loyihadagi eski `Mapped[float]` annotatsiyalari — noto'g'ri, ular ham
    ish vaqtida `Decimal` qaytaradi).
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
                        func, text)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, FullMixin, PKMixin
from app.db.types import JSONB, UUID

#  Qisman indeks shartlari — model va `initdb._ensure_indexes` DDL'ida AYNAN BIR XIL matn
#  bo'lishi SHART (loyiha konvensiyasi, `models/receipt.py:58` naqshi).
_ALIVE = text("deleted_at IS NULL")
_CLIENT_UUID_SET = text("client_uuid IS NOT NULL")


class Plan(Base, FullMixin):
    """Tarif — narx DB'da, kodda EMAS.

    ⚠️  `price` da NULL va 0 BOSHQA-BOSHQA narsa:
          NULL = narx HALI ANIQLANMAGAN (admin kiritmagan) — hisob-kitobga kirmaydi;
          0    = ATAYLAB BEPUL (masalan pilot).
        Shu bois ustun nullable va kodda `is None` bilan tekshiriladi, `or 0` BILAN EMAS.
    ⚠️  Limitlar (`max_*`) NULL bo'lsa — «bu yerda aniqlanmagan», cheksiz DEGANI EMAS.
        Eski ijarachilar uchun chegara `api/v1/branches.py` dagi eski jadvaldan keladi
        (`services/subscription/plan_limits.py` — o'qish tartibi shu yerda).
    """
    __tablename__ = "plans"
    __table_args__ = (
        Index("ux_plans_code", "code", unique=True, postgresql_where=_ALIVE, sqlite_where=_ALIVE),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)      # PILOT | START | BUSINESS | NETWORK
    name: Mapped[str] = mapped_column(String, nullable=False)
    billing_period: Mapped[str] = mapped_column(String(16), nullable=False, default="monthly")
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="UZS")
    grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_branches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tills: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Subscription(Base, FullMixin):
    """Kompaniyaning obunasi — HAR KOMPANIYAGA BITTA (qisman noyob indeks).

    ⚠️  QATOR YO'Q = MAJBURLASH YO'Q. Mavjud ijarachilar (Fayzan ham) qatorsiz qoladi va
        HECH QACHON avtomatik cheklanmaydi. Ro'yxatga olish faqat ANIQ admin amali bilan.
        Bu jim «fail-open» emas: yozuv yo'qligi «to'lanmagan» degani emas, «ro'yxatda yo'q»
        degani. Test buni qulflaydi (`test_subscription_schema.py`).
    ⚠️  `status` — KESH va ANIQ bekor qilish (CANCELLED / operator RESTRICT) uchun.
        Muddat bo'yicha qaror HAR SO'ROVDA qayta hisoblanadi: scheduler kechiksa ham
        muddati o'tgan ijarachi yoza olmasin (`services/subscription/state.py`).
    """
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ux_subscriptions_company", "company_id", unique=True,
              postgresql_where=_ALIVE, sqlite_where=_ALIVE),
        Index("ix_subscriptions_period_end", "current_period_end"),
        Index("ix_subscriptions_grace", "grace_until"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    grace_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restricted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SubscriptionPayment(Base, PKMixin):
    """Qo'lda kiritilgan to'lov — O'ZGARMAS reyestr.

    ⚠️  TAHRIRLASH VA O'CHIRISH YO'Q. `FullMixin` ATAYLAB olinmagan: `updated_at` ham,
        `deleted_at` ham yo'q — qator yozilgach o'zgarmaydi. Xato kiritilgan to'lov
        `reversal_of_id` bilan YANGI qator orqali qaytariladi (storno), eskisi qoladi.
    ⚠️  `client_uuid` — idempotentlik kaliti: admin ikki marta bossa IKKI to'lov yozilmaydi
        (`ux_subpay_client_uuid`).
    """
    __tablename__ = "subscription_payments"
    __table_args__ = (
        Index("ux_subpay_client_uuid", "client_uuid", unique=True,
              postgresql_where=_CLIENT_UUID_SET, sqlite_where=_CLIENT_UUID_SET),
        Index("ix_subpay_company_paid", "company_id", "paid_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="UZS")
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #  Qaysi davr uchun to'landi — yangilash (renewal) natijasidan MUSTAQIL yoziladi.
    period_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_admin: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_admins.id"), nullable=True)
    #  Storno: shu qator QAYSI to'lovni qaytaradi (o'ziga havola).
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_payments.id"), nullable=True)
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlatformAdmin(Base, FullMixin):
    """Platforma operatori — `employees` DAN MUTLAQO ALOHIDA.

    ⚠️  NEGA `employees` EMAS (uchta aniq sabab):
          1. `Employee.company_id` NOT NULL — «kompaniyasiz» admin modelga sig'maydi;
             soxta kompaniyaga bog'lash ijarachi izolyatsiyasini buzardi.
          2. Parolli akkaunt telefoni GLOBAL noyob (`ux_employees_phone_pw`) — admin
             telefoni mijoz do'konidagi telefon bilan to'qnashardi.
          3. `core/deps.py:require()` da ega/administrator ruxsat kodisiz SHARTSIZ o'tadi —
             «faqat platforma admini» darvozasini ruxsat kodi ustiga qurish XAVFLI.
    ⚠️  `password_hash` va `totp_secret` HECH QACHON javobga chiqmaydi (API sxemasida yo'q).
    """
    __tablename__ = "platform_admins"
    __table_args__ = (
        Index("ux_platform_admins_login", "login", unique=True,
              postgresql_where=_ALIVE, sqlite_where=_ALIVE),
    )

    login: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminAuditLog(Base, PKMixin):
    """Platforma admini amallari — O'ZGARMAS iz.

    ⚠️  MAVJUD `audit_log` (models/sync.py) BU ISH UCHUN YARAMAYDI:
          · unda `company_id` ustuni YO'Q;
          · `actor_id` FK'si `employees` ga — vendor operatorini yozib bo'lmaydi va
            hozirgi vendor amallari `actor_id=None` bilan yoziladi;
          · `/audit` o'qishi INNER JOIN qiladi (`api/v1/audit.py:32-34`) — `actor_id=None`
            qatorlar ekranda UMUMAN ko'rinmaydi.
    ⚠️  `company_id` da FK ATAYLAB YO'Q: `companies` ga FK (ayniqsa CASCADE) do'kon
        o'chirilganda platformaning O'Z izini ham yo'q qilardi. Egalik `tools/tenant_purge`
        `SEMANTIC_REGISTRY` sida ANIQ e'lon qilingan.
    ⚠️  Sir yozilmaydi: parol, token, TOTP — `before_summary`/`after_summary` ga yozuvchi
        funksiya oq-ro'yxat bilan filtrlaydi (xizmat qatlami, Phase 6A/3).
    """
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        Index("ix_admin_audit_company_created", "company_id", "created_at"),
        Index("ix_admin_audit_actor_created", "actor_admin_id", "created_at"),
    )

    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_admins.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    before_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
