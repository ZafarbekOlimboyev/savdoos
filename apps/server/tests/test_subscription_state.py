# -*- coding: utf-8 -*-
"""PHASE 6A/2 — obuna holati mashinasi, davrlar, yangilash va siyosat (bazasiz).

Bu fayl UCHTA invariantni qulflaydi:
  1. GRANDFATHERING — obuna yozuvi yo'q do'kon HECH QACHON cheklanmaydi;
  2. USTUVORLIK — aniq operator qarori vaqtdan USTUN, tartib o'zgarmaydi;
  3. SMENA YOPISH — `RESTRICTED` da ham MUMKIN (kassada ochiq smena qolmasin).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.enums import SubscriptionStatus
from app.services.subscription import policy as P
from app.services.subscription.periods import (PILOT_CODE, RenewalRefused, add_months,
                                               grace_end, period_end, renewal_base)
from app.services.subscription.state import (REASON_CANCELLED, REASON_EXPIRED,
                                             REASON_GRACE_PERIOD, REASON_GRANDFATHERED,
                                             REASON_MANUAL_RESTRICTION, REASON_PERIOD_ACTIVE,
                                             evaluate_subscription_access)

UTC = timezone.utc
ACTIVE = SubscriptionStatus.ACTIVE.value
GRACE = SubscriptionStatus.GRACE.value
RESTRICTED = SubscriptionStatus.RESTRICTED.value
CANCELLED = SubscriptionStatus.CANCELLED.value

#  17-oktabr — brief'dagi misol (17 Okt -> 17 Noy).
START = datetime(2026, 10, 17, 9, 30, tzinfo=UTC)
END = datetime(2026, 11, 17, 9, 30, tzinfo=UTC)
GRACE_UNTIL = END + timedelta(days=3)


class _Sub:
    def __init__(self, *, status=ACTIVE, end=END, grace=GRACE_UNTIL,
                 restricted_at=None, cancelled_at=None):
        self.status = status
        self.current_period_end = end
        self.grace_until = grace
        self.restricted_at = restricted_at
        self.cancelled_at = cancelled_at


# ══ 1. GRANDFATHERING ════════════════════════════════════════════════════════

def test_GRANDFATHERING_yozuv_yoq_managed_FALSE_va_yozuv_OCHIQ():
    a = evaluate_subscription_access(None, START)
    assert a.managed is False
    assert a.effective_status is None, (
        "yozuvsiz do'kon `ACTIVE` deb ko'rsatilmasin — u ro'yxatga OLINMAGAN, "
        "bu pul haqida hech narsa demaydi")
    assert a.reason == REASON_GRANDFATHERED
    assert a.writes_allowed is True


@pytest.mark.parametrize("delta_days", [-3650, -1, 0, 1, 3650])
def test_GRANDFATHERING_vaqt_TASIR_QILMAYDI(delta_days):
    a = evaluate_subscription_access(None, START + timedelta(days=delta_days))
    assert (a.managed, a.writes_allowed) == (False, True)


def test_GRANDFATHERING_har_toifada_yozuv_ochiq():
    a = evaluate_subscription_access(None, START)
    for cat in sorted(P.ALL_CATEGORIES):
        assert P.is_allowed(cat, a.effective_status, managed=a.managed) is True


# ══ 2. USTUVORLIK — tartib qulflangan ════════════════════════════════════════

def test_USTUVORLIK_CANCELLED_vaqtdan_USTUN():
    """Davr hali tugamagan bo'lsa ham bekor qilingan obuna cheklangan."""
    sub = _Sub(status=CANCELLED, cancelled_at=START)
    a = evaluate_subscription_access(sub, START)          # davr oxirigacha bir oy bor
    assert (a.effective_status, a.reason, a.writes_allowed) == (RESTRICTED, REASON_CANCELLED, False)


def test_USTUVORLIK_QOLDA_cheklov_vaqtdan_USTUN():
    sub = _Sub(status=RESTRICTED, restricted_at=START - timedelta(days=1))
    a = evaluate_subscription_access(sub, START)
    assert (a.effective_status, a.reason) == (RESTRICTED, REASON_MANUAL_RESTRICTION)
    assert a.writes_allowed is False


def test_USTUVORLIK_ZID_qator_FAIL_CLOSED_status_RESTRICTED_restricted_at_YOQ():
    """`status='RESTRICTED'` + `restricted_at IS NULL` -> baribir CHEKLANGAN.

    ⚠️  Ilgari bu holat vaqtga tushib ketardi va davr ichida `ACTIVE` qaytarardi:
        qo'lda cheklangan do'kon yana yoza olardi. Zid qator «cheklov yo'q» degani
        emas, «ma'lumotga ishonib bo'lmaydi» degani — kengroq ruxsat berilmaydi.
        Sxemada `ck_sub_restricted_iff` buni taqiqlaydi; bu yerdagi shart esa
        CHECK'siz bazada ham (SQLite, yoki NOT VALID qolgan Postgres) ishlaydi.
    """
    sub = _Sub(status=RESTRICTED, restricted_at=None)
    a = evaluate_subscription_access(sub, START)
    assert (a.effective_status, a.reason) == (RESTRICTED, REASON_MANUAL_RESTRICTION)
    assert a.writes_allowed is False


def test_USTUVORLIK_ZID_qator_FAIL_CLOSED_status_ACTIVE_lekin_restricted_at_BOR():
    """Teskari zidlik ham xuddi shunday: qolib ketgan `restricted_at` CHEKLAYDI."""
    sub = _Sub(status=ACTIVE, restricted_at=START - timedelta(days=1))
    a = evaluate_subscription_access(sub, START)
    assert (a.effective_status, a.reason) == (RESTRICTED, REASON_MANUAL_RESTRICTION)
    assert a.writes_allowed is False


# ══ 3. VAQT CHEGARALARI (7-band) ═════════════════════════════════════════════

def test_davr_oxiridan_BIR_MIKROSONIYA_oldin_ACTIVE():
    a = evaluate_subscription_access(_Sub(), END - timedelta(microseconds=1))
    assert (a.effective_status, a.reason) == (ACTIVE, REASON_PERIOD_ACTIVE)


def test_AYNAN_davr_oxiri_GRACE():
    a = evaluate_subscription_access(_Sub(), END)
    assert (a.effective_status, a.reason, a.writes_allowed, a.warn) == \
        (GRACE, REASON_GRACE_PERIOD, True, True)


def test_grace_oxiridan_BIR_MIKROSONIYA_oldin_hamon_GRACE():
    a = evaluate_subscription_access(_Sub(), GRACE_UNTIL - timedelta(microseconds=1))
    assert a.effective_status == GRACE


def test_AYNAN_grace_oxiri_RESTRICTED():
    a = evaluate_subscription_access(_Sub(), GRACE_UNTIL)
    assert (a.effective_status, a.reason, a.writes_allowed) == (RESTRICTED, REASON_EXPIRED, False)


def test_grace_oxiridan_KEYIN_RESTRICTED():
    a = evaluate_subscription_access(_Sub(), GRACE_UNTIL + timedelta(days=90))
    assert (a.effective_status, a.reason) == (RESTRICTED, REASON_EXPIRED)


def test_grace_days_NOL_bolsa_grace_YOQ():
    end = END
    sub = _Sub(end=end, grace=grace_end(end, 0))
    assert evaluate_subscription_access(sub, end - timedelta(microseconds=1)).effective_status == ACTIVE
    assert evaluate_subscription_access(sub, end).effective_status == RESTRICTED


def test_naive_vaqt_RAD_etiladi():
    with pytest.raises(ValueError):
        evaluate_subscription_access(_Sub(), datetime(2026, 11, 17, 9, 30))


# ══ 4. YILLIK SANA VA OY OXIRI ═══════════════════════════════════════════════

def test_oddiy_yillik_sana_17okt_17noy():
    assert add_months(START, 1) == END


@pytest.mark.parametrize("start,expected", [
    # 31-yanvar -> 28-fevral (ODDIY yil)
    (datetime(2026, 1, 31, 12, 0, tzinfo=UTC), datetime(2026, 2, 28, 12, 0, tzinfo=UTC)),
    # 31-yanvar -> 29-fevral (KABISA yil)
    (datetime(2028, 1, 31, 12, 0, tzinfo=UTC), datetime(2028, 2, 29, 12, 0, tzinfo=UTC)),
    # 31-mart -> 30-aprel
    (datetime(2026, 3, 31, 12, 0, tzinfo=UTC), datetime(2026, 4, 30, 12, 0, tzinfo=UTC)),
    # 28-fevral -> 28-mart (qisqartirish YO'Q)
    (datetime(2026, 2, 28, 12, 0, tzinfo=UTC), datetime(2026, 3, 28, 12, 0, tzinfo=UTC)),
    # 29-fevral (kabisa) -> 29-mart
    (datetime(2028, 2, 29, 12, 0, tzinfo=UTC), datetime(2028, 3, 29, 12, 0, tzinfo=UTC)),
    # yil chegarasi: 31-dekabr -> 31-yanvar
    (datetime(2026, 12, 31, 12, 0, tzinfo=UTC), datetime(2027, 1, 31, 12, 0, tzinfo=UTC)),
])
def test_oy_oxiri_QISQARTIRILADI(start, expected):
    assert add_months(start, 1) == expected


def test_qisqartirish_YOPISHIB_QOLMAYDI():
    """31-yanvarda boshlangan obuna har oy uch kun yo'qotmasligi kerak.

    Davr oxiri HAR DOIM asl `started_at` dan hisoblanadi, oldingi (qisqartirilgan)
    davr oxiridan EMAS."""
    start = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)
    assert add_months(start, 1).day == 28    # fevral — qisqargan
    assert add_months(start, 2).day == 31    # mart — asl kun QAYTADI
    assert add_months(start, 3).day == 30    # aprel — yana qisqargan
    assert add_months(start, 4).day == 31    # may — asl kun


def test_add_months_vaqt_va_zona_OZGARMAYDI():
    got = add_months(START, 1)
    assert (got.hour, got.minute, got.tzinfo) == (START.hour, START.minute, START.tzinfo)


def test_PILOT_AYNAN_30_kun_kalendar_EMAS():
    """Fevralda ham 30 kun: «30 kunlik sinov» aytilgan."""
    feb = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    assert period_end(feb, plan_code=PILOT_CODE) == feb + timedelta(days=30)
    assert period_end(feb, plan_code=PILOT_CODE) == datetime(2026, 3, 3, 12, 0, tzinfo=UTC)
    #  Oylik tarif esa AYNI sanada kalendar bo'yicha yuradi
    assert period_end(feb, plan_code="START") == datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def test_grace_end_hisobi():
    assert grace_end(END, 3) == END + timedelta(days=3)
    with pytest.raises(ValueError):
        grace_end(END, -1)


# ══ 5. YANGILASH ═════════════════════════════════════════════════════════════

def test_yangilash_ACTIVE_da_ESKI_davr_oxiridan_boshlanadi():
    """Erta to'lagan mijoz kun YO'QOTMAYDI."""
    sub = _Sub()
    assert renewal_base(sub, START) == END


def test_yangilash_GRACE_da_NOW_dan_boshlanadi():
    sub = _Sub()
    now = END + timedelta(days=1)
    assert renewal_base(sub, now) == now


def test_yangilash_MUDDATI_OTGAN_da_NOW_dan_boshlanadi():
    sub = _Sub()
    now = GRACE_UNTIL + timedelta(days=10)
    assert renewal_base(sub, now) == now


def test_yangilash_CANCELLED_ni_JIMGINA_TIRILTIRMAYDI():
    """Bekor qilish terminal: to'lov keldi degan sabab bilan operator qarori bekor bo'lmasin."""
    sub = _Sub(status=CANCELLED, cancelled_at=START)
    with pytest.raises(RenewalRefused):
        renewal_base(sub, START)


def test_yangilash_QOLDA_CHEKLOVNI_YECHMAYDI():
    """Davr uzayadi, LEKIN cheklov kuchda qoladi — aniq `restore` kerak."""
    sub = _Sub(status=RESTRICTED, restricted_at=START - timedelta(days=1))
    base = renewal_base(sub, START)
    assert base == END, "davr uzayishi kerak"
    #  Yangi davr yozilgandan keyin ham holat RESTRICTED bo'lib qoladi
    sub.current_period_end = add_months(base, 1)
    sub.grace_until = grace_end(sub.current_period_end, 3)
    a = evaluate_subscription_access(sub, START)
    assert (a.effective_status, a.reason) == (RESTRICTED, REASON_MANUAL_RESTRICTION)


def test_yangilashdan_KEYIN_tiklansa_ACTIVE():
    """`restore` = `restricted_at=None` + status ACTIVE (faqat QO'LDA cheklov uchun)."""
    sub = _Sub(status=RESTRICTED, restricted_at=START - timedelta(days=1))
    sub.status, sub.restricted_at = ACTIVE, None
    a = evaluate_subscription_access(sub, START)
    assert (a.effective_status, a.reason) == (ACTIVE, REASON_PERIOD_ACTIVE)


def test_naive_now_yangilashda_ham_RAD():
    with pytest.raises(ValueError):
        renewal_base(_Sub(), datetime(2026, 10, 17, 9, 30))


# ══ 6. SIYOSAT MATRITSASI ════════════════════════════════════════════════════

def test_SMENA_YOPISH_RESTRICTED_da_ham_MUMKIN():
    """YAGONA istisno — kassada ochiq smena qolib ketmasin."""
    assert P.is_allowed(P.SHIFT_CLOSE, RESTRICTED, managed=True) is True


def test_smena_OCHISH_RESTRICTED_da_TOSILADI():
    assert P.is_allowed(P.SHIFT_OPEN, RESTRICTED, managed=True) is False


@pytest.mark.parametrize("cat", sorted(P.BUSINESS_WRITE))
def test_biznes_yozuvi_RESTRICTED_da_TOSILADI(cat):
    assert P.is_allowed(cat, RESTRICTED, managed=True) is False


@pytest.mark.parametrize("cat", sorted(P.BUSINESS_WRITE))
def test_biznes_yozuvi_ACTIVE_va_GRACE_da_MUMKIN(cat):
    assert P.is_allowed(cat, ACTIVE, managed=True) is True
    assert P.is_allowed(cat, GRACE, managed=True) is True


@pytest.mark.parametrize("cat", sorted(P.ALWAYS_ALLOWED))
def test_login_oqish_hisobot_billing_HAR_DOIM_ochiq(cat):
    for st in (ACTIVE, GRACE, RESTRICTED):
        assert P.is_allowed(cat, st, managed=True) is True


def test_smena_OCHISH_va_YOPISH_boshqa_toifada():
    assert P.SHIFT_OPEN in P.BUSINESS_WRITE and P.SHIFT_OPEN not in P.SAFE_RECOVERY
    assert P.SHIFT_CLOSE in P.SAFE_RECOVERY and P.SHIFT_CLOSE not in P.BUSINESS_WRITE


def test_notanish_toifa_JIMGINA_otmaydi():
    """Yangi yozuv toifasi qo'shilib matritsaga kiritilmasa — ochiq xato."""
    with pytest.raises(ValueError):
        P.is_allowed("yangi_nomalum_amal", RESTRICTED, managed=True)


def test_toifalar_toplami_KESISHMAYDI():
    assert P.ALWAYS_ALLOWED & P.BUSINESS_WRITE == frozenset()
    assert P.SAFE_RECOVERY & P.BUSINESS_WRITE == frozenset()
    assert P.ALL_CATEGORIES == P.ALWAYS_ALLOWED | P.BUSINESS_WRITE | P.SAFE_RECOVERY
