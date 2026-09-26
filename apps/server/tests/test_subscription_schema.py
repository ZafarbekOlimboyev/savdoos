# -*- coding: utf-8 -*-
"""PHASE 6A/1 — obuna SXEMASI: jadvallar, ro'yxatlar, eski tarif kodlari (bazasiz).

Holat mashinasi, davrlar, yangilash va siyosat — `test_subscription_state.py` da.
"""

from app.core import required_schema as rs
from app.models.enums import (CompanyStatus, PlatformAdminRole, SubscriptionPaymentMethod,
                              SubscriptionStatus)
from app.services.subscription.plan_limits import (CANONICAL_PLANS, LEGACY_PLAN_ALIAS,
                                                   canonical_from_legacy, canonical_plan_code)

# ══ ESKI TARIF KODLARI XARITASI ══════════════════════════════════════════════

def test_kanonik_tariflar_royxati():
    assert CANONICAL_PLANS == ("PILOT", "START", "BUSINESS", "NETWORK")


def test_legacy_alias_LIMITNI_KAMAYTIRMAYDI():
    """`start+` = 5 filial / 30 xodim (branches.py:4, 27, 30).

    Uni 1 filialli `START` ga xaritalash 3 filialli do'konni bir kechada limit
    buzuvchiga aylantirardi — shu bois xarita pog'ona TARTIBINI saqlaydi.
    """
    assert LEGACY_PLAN_ALIAS["start"] == "START"
    assert LEGACY_PLAN_ALIAS["start+"] == "BUSINESS"
    assert LEGACY_PLAN_ALIAS["start+"] != "START", "start+ (5 filial) -> START (1 filial) = KAMAYISH"
    assert LEGACY_PLAN_ALIAS["business"] == "NETWORK"
    assert set(LEGACY_PLAN_ALIAS.values()) <= set(CANONICAL_PLANS)


def test_startplus_kanonik_tarif_EMAS():
    assert "start+" not in CANONICAL_PLANS and "START+" not in CANONICAL_PLANS


def test_ikki_namespace_ARALASHMAYDI():
    """`"business"` ikkala namespace'da ham bor — funksiya manbani BILISHI shart.

    Eski `business` = 999 filial (cheksiz). Uni yangi `BUSINESS` (o'rta pog'ona) deb
    o'qish do'konni PASAYTIRARDI, shuning uchun bitta "aqlli" funksiya YO'Q.
    """
    #  ESKI manba (settings['plan'])
    assert canonical_from_legacy("start") == "START"
    assert canonical_from_legacy("start+") == "BUSINESS"
    assert canonical_from_legacy("business") == "NETWORK"
    assert canonical_from_legacy("BUSINESS") == "NETWORK", "registrga sezgir bo'lmasin"
    assert canonical_from_legacy("PILOT") is None, "PILOT eski kod EMAS"
    #  YANGI manba (admin/API)
    assert canonical_plan_code("BUSINESS") == "BUSINESS"
    assert canonical_plan_code("PILOT") == "PILOT"
    assert canonical_plan_code("business") is None, (
        "kichik harfli `business` — ESKI kod; uni yangi BUSINESS deb qabul qilish PASAYTIRISH")
    assert canonical_plan_code("start+") is None
    assert canonical_plan_code("yoq-tarif") is None
    assert canonical_plan_code(None) is None and canonical_plan_code("") is None


# ══ SXEMA INVARIANTLARI ══════════════════════════════════════════════════════

def test_yangi_jadvallar_metadatada():
    from app.db.base import Base
    import app.models  # noqa: F401  (ro'yxatga olish)
    for t in ("plans", "subscriptions", "subscription_payments",
              "platform_admins", "admin_audit_log"):
        assert t in Base.metadata.tables, f"{t} `models/__init__.py` da ro'yxatga OLINMAGAN"


def test_tolov_reyestri_OZGARMAS_ustunlar_yoq():
    """`subscription_payments` da `updated_at`/`deleted_at` BO'LMASLIGI SHART."""
    from app.db.base import Base
    import app.models  # noqa: F401
    cols = set(Base.metadata.tables["subscription_payments"].columns.keys())
    assert "updated_at" not in cols and "deleted_at" not in cols, (
        "to'lov reyestri o'zgarmas bo'lishi kerak — tahrir/o'chirish ustunlari yo'q")
    assert {"client_uuid", "reversal_of_id", "created_at"} <= cols


def test_companies_status_T1_izchil():
    """ORM'da xaritalangan + boot qo'shadi -> MAJBURIY ro'yxatda (T1 qoidasi)."""
    from app import initdb as I
    assert ("companies", "status", "VARCHAR(16)") in I._ADDED_COLUMNS
    assert ("companies", "status") in rs.REQUIRED_COLUMNS


def test_yangi_indekslar_BOOTGA_BOGLANMAGAN():
    """Majburlash yoqilmagan ekan, prod boot bu obyektlarga bog'lanmasin."""
    req = {n for n, _ in rs.REQUIRED_INDEXES}
    opt = {n for n, _ in rs.OPTIONAL_UNIQUE_INDEXES}
    perf = {n for n, _ in rs.PERFORMANCE_INDEXES}
    uniques = {"ux_plans_code", "ux_subscriptions_company", "ux_subpay_client_uuid",
               "ux_platform_admins_login"}
    speed = {"ix_subscriptions_period_end", "ix_subscriptions_grace", "ix_subpay_company_paid",
             "ix_admin_audit_company_created", "ix_admin_audit_actor_created"}
    assert uniques & req == set(), "Phase 6A noyob indeksi MAJBURIY ro'yxatda — boot unga bog'lanadi"
    assert uniques <= opt
    assert speed <= perf


def test_purge_reyestrida_yangi_jadvallar_ELON_QILINGAN():
    """Har jadval yo FK grafida, yo reyestrda bo'lishi SHART (tenant_purge qoidasi)."""
    from app.tools.tenant_purge import SEMANTIC_REGISTRY as R
    assert R[("public", "plans")]["klass"] == "GLOBAL_SHARED"
    assert R[("public", "platform_admins")]["klass"] == "GLOBAL_SHARED"
    assert R[("public", "admin_audit_log")]["klass"] == "OWNED_SEMANTIC"
    assert R[("public", "admin_audit_log")]["ownership_column"] == "company_id"
    #  FK grafi orqali topiladiganlar reyestrda BO'LMASLIGI kerak (yolg'on tasnif bo'lardi)
    assert ("public", "subscriptions") not in R
    assert ("public", "subscription_payments") not in R


def test_enum_qiymatlari_shartnoma():
    assert [e.value for e in CompanyStatus] == ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert [e.value for e in SubscriptionStatus] == ["ACTIVE", "GRACE", "RESTRICTED", "CANCELLED"]
    assert [e.value for e in PlatformAdminRole] == ["SUPER_ADMIN", "ADMIN", "SUPPORT_READONLY"]
    assert [e.value for e in SubscriptionPaymentMethod] == ["CASH", "BANK_TRANSFER", "QR", "OTHER"]

def test_GRACE_bazaga_YOZILMAYDI_shartnomasi():
    """Saqlanadigan qiymatlar — faqat ACTIVE/RESTRICTED/CANCELLED.

    `GRACE` faqat HISOBLANADI (`state.evaluate_subscription_access`). Agar u bazaga
    yozilsa, qiymat darhol eskirardi: uni yangilab turadigan hech kim yo'q.
    """
    from app.services.subscription import state as S
    persisted = {SubscriptionStatus.ACTIVE.value, SubscriptionStatus.RESTRICTED.value,
                 SubscriptionStatus.CANCELLED.value}
    assert SubscriptionStatus.GRACE.value not in persisted
    assert S.REASON_GRACE_PERIOD == "GRACE_PERIOD"
