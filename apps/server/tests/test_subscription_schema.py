# -*- coding: utf-8 -*-
"""PHASE 6A/1 — obuna sxemasi va GRANDFATHERING (bazasiz, sof tekshiruvlar).

⚠️  ENG MUHIM TEST — `test_GRANDFATHERING_*`: obuna yozuvi YO'Q bo'lgan do'kon
    HECH QACHON cheklanmasligi kerak. Mavjud production ijarachilari (Fayzan ham)
    aynan shu holatda va migratsiya ularni avtomatik cheklab qo'ymasligi SHART.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core import required_schema as rs
from app.models.enums import (CompanyStatus, PlatformAdminRole, SubscriptionPaymentMethod,
                              SubscriptionStatus)
from app.services.subscription.plan_limits import (CANONICAL_PLANS, LEGACY_PLAN_ALIAS,
                                                   canonical_from_legacy, canonical_plan_code)
from app.services.subscription.state import NOT_ENROLLED, effective_state

UTC = timezone.utc
T0 = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


class _Sub:
    """`Subscription` qatorining eng kichik o'rindoshi (baza kerak emas)."""

    def __init__(self, *, period_end, grace_until, status=SubscriptionStatus.ACTIVE.value,
                 restricted_at=None):
        self.current_period_end = period_end
        self.grace_until = grace_until
        self.status = status
        self.restricted_at = restricted_at


# ══ GRANDFATHERING — PHASE 6A NING ENG MUHIM INVARIANTI ══════════════════════

def test_GRANDFATHERING_obuna_yozuvi_YOQ_dokon_CHEKLANMAYDI():
    st = effective_state(None, T0)
    assert st.status == NOT_ENROLLED
    assert st.enrolled is False
    assert st.writes_allowed is True, (
        "obuna yozuvi yo'q do'kon CHEKLANDI — mavjud production ijarachilari "
        "(Fayzan ham) aynan shu holatda; bu migratsiyani xavfli qiladi")
    assert st.warn is False


def test_GRANDFATHERING_vaqt_qancha_otsa_ham_yozuvsiz_dokon_ochiq():
    """Yozuv yo'q bo'lsa VAQT umuman hisobga olinmaydi — «muddati o'tgan» tushunchasi yo'q."""
    for dt in (T0 - timedelta(days=3650), T0, T0 + timedelta(days=3650)):
        assert effective_state(None, dt).writes_allowed is True


# ══ CHEGARA HOLATLARI ════════════════════════════════════════════════════════

def test_davr_ichida_ACTIVE():
    sub = _Sub(period_end=T0 + timedelta(days=5), grace_until=T0 + timedelta(days=8))
    st = effective_state(sub, T0)
    assert (st.status, st.writes_allowed, st.warn) == (SubscriptionStatus.ACTIVE.value, True, False)
    assert st.days_left == 5


def test_davr_oxiri_AYNAN_shu_lahza_GRACE_ga_otadi():
    """`now == current_period_end` — davr TUGAGAN, grace BOSHLANGAN (chegara `<` bilan)."""
    end = T0
    sub = _Sub(period_end=end, grace_until=end + timedelta(days=3))
    st = effective_state(sub, end)
    assert st.status == SubscriptionStatus.GRACE.value
    assert st.writes_allowed is True, "GRACE da yozuv MUMKIN bo'lishi kerak (ogohlantirish bilan)"
    assert st.warn is True


def test_grace_oxiri_AYNAN_shu_lahza_RESTRICTED():
    end = T0
    grace = end + timedelta(days=3)
    sub = _Sub(period_end=end, grace_until=grace)
    assert effective_state(sub, grace - timedelta(seconds=1)).status == SubscriptionStatus.GRACE.value
    st = effective_state(sub, grace)
    assert st.status == SubscriptionStatus.RESTRICTED.value
    assert st.writes_allowed is False


def test_oy_oxiri_va_KABISA_yil_chegaralari():
    """Yillik sana modeli: 31-yanvar -> 28/29-fevral; kalendar oyga bog'lanmaydi."""
    end = datetime(2026, 2, 28, 23, 59, 59, tzinfo=UTC)
    sub = _Sub(period_end=end, grace_until=end + timedelta(days=3))
    assert effective_state(sub, datetime(2026, 2, 28, 12, 0, tzinfo=UTC)).status == \
        SubscriptionStatus.ACTIVE.value
    assert effective_state(sub, datetime(2026, 3, 1, 0, 0, tzinfo=UTC)).status == \
        SubscriptionStatus.GRACE.value
    # 2028 — kabisa yil: 29-fevral MAVJUD va oddiy kun sifatida ishlaydi
    end2 = datetime(2028, 2, 29, 12, 0, tzinfo=UTC)
    sub2 = _Sub(period_end=end2, grace_until=end2 + timedelta(days=3))
    assert effective_state(sub2, end2 - timedelta(seconds=1)).status == SubscriptionStatus.ACTIVE.value
    assert effective_state(sub2, end2).status == SubscriptionStatus.GRACE.value


def test_CANCELLED_sanadan_QATIY_NAZAR_RESTRICTED():
    sub = _Sub(period_end=T0 + timedelta(days=365), grace_until=T0 + timedelta(days=368),
               status=SubscriptionStatus.CANCELLED.value)
    st = effective_state(sub, T0)
    assert st.status == SubscriptionStatus.RESTRICTED.value and st.writes_allowed is False


def test_operator_QOLDA_cheklasa_muddat_tugamagan_bolsa_ham_RESTRICTED():
    sub = _Sub(period_end=T0 + timedelta(days=30), grace_until=T0 + timedelta(days=33),
               status=SubscriptionStatus.RESTRICTED.value, restricted_at=T0 - timedelta(days=1))
    assert effective_state(sub, T0).writes_allowed is False


def test_naive_vaqt_RAD_etiladi():
    """Zonasiz vaqt jim noto'g'ri solishtirishga olib kelardi — ochiq xato."""
    sub = _Sub(period_end=T0, grace_until=T0 + timedelta(days=3))
    with pytest.raises(ValueError):
        effective_state(sub, datetime(2026, 10, 17, 12, 0))


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
