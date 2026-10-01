# -*- coding: utf-8 -*-
"""P9-06 — `_lock_candidate_shift` da ESKIRGAN IDENTITY-MAP holati (haqiqiy PostgreSQL).

ASL TOPILMA (mustaqil QA):
  «`posting._lock_candidate_shift` da qulfdan keyin status QAYTA O'QILMAYDI
   (identity-map eski qiymat) → ON_SHIFT leg YOPIQ cash-smenaga; LATE_SYNC
   aylanib o'tiladi.»

MEXANIZM. `select(CashShift)...with_for_update()` SQL qulfini TO'G'RI oladi, lekin
obyekt sessiya identity-map'ida ALLAQACHON bo'lsa, SQLAlchemy KESHDAGI nusxani
qaytaradi va atributlarni QAYTA O'QIMAYDI (`populate_existing()` yo'q,
`expire_on_commit=False`). Ya'ni qulf kutilayotganda boshqa tranzaksiya smenani
yopib commit qilsa ham, `cand.status` hamon 'OPEN' bo'lib ko'rinadi.

QAROR MAYDONI: `_resolve_shift` AYNAN `cand.status` ga qaraydi —
  OPEN + oynada  -> ON_SHIFT      (Case A, anomaliyasiz)
  CLOSED + oynada-> LATE_SYNC + `LATE_SYNC_UNACK`  (Case C, anomaliya bilan)
Eskirgan 'OPEN' Case C ni Case A ga aylantiradi: yopilgan va yarashtirilgan
smenaga ANOMALIYASIZ ON_SHIFT legi tushadi va `trg_cle_immutable` uni muzlatadi.

⚠️  REACHABILITY (3A va P9-05 dan KEYIN qayta tekshirilgan — eski xulosa ko'chirilmadi):
    · SOTUV yo'li (`on_cash_sale`) ENDI HIMOYALANGAN: Phase 3A `sales.py` da
      `public.shifts` ni `FOR NO KEY UPDATE` bilan qulflaydi, `close_shift` esa ayni
      qatorni `FOR UPDATE` bilan oladi — ular to'qnashadi, ya'ni yopish sotuv qulfni
      ushlab turganda COMMIT QILA OLMAYDI va eskirish oynasi ochilmaydi.
    · LEKIN naqd QARZ TO'LOVI (`customers.py` -> `on_debt_payment`), TA'MINOTCHI
      TO'LOVI, NAQD XARID va XARID QAYTARISHI `public.shifts` ni UMUMAN qulflamaydi
      (faqat Customer/Supplier/Inventory). Ular `_explicit_ctx` -> `_open_cash_shift_id`
      -> `repo.open_shift_for_account` orqali CashShift'ni identity-map'ga YUKLAYDI va
      keyin `origin_shift_id` bilan post qiladi — oyna AYNAN shu yerda ochiq.

⚠️  Sinov DETERMINISTIK: qulf chaqirilishidan AYNAN oldin boshqa tranzaksiyada
    smenani yopamiz (hook), ya'ni timing lotereyasi yo'q.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models.cash import CashAccount, CashShift
from app.services.cash import posting as _posting
from app.services.cash import retrofit as _cr
from app.services.cash.posting import CashPostingService
# ⚠️  HAQIQIY hozirgi vaqt: `adapters._post` `device_occurred_at` berilmasa `_now()`
#     ni qo'yadi, `_resolve_shift` esa uni smena OYNASIGA solishtiradi
#     (`opened_at ± tolerance` … `opened_at + MAX_SHIFT_HOURS`). Qattiq kodlangan sana
#     bilan har post Case B (`TIMESTAMP_OUT_OF_WINDOW`) bo'lib ketardi va sinov
#     tekshirmoqchi bo'lgan shoxga UMUMAN yetib bormasdi.
NOW = datetime.now(timezone.utc)

pytestmark = pytest.mark.usefixtures("cashenv")


def _S(env):
    """ILOVA BILAN AYNI sozlama — identity-map tuzog'i aynan shu yerdan keladi."""
    return sessionmaker(bind=env.engine, autoflush=False,
                        expire_on_commit=False, class_=Session)()


def _till(env, *, code=None):
    from app.services.cash import till_identity as _ti
    kod = code or ("T-" + uuid.uuid4().hex[:6])
    s = _S(env)
    try:
        a = CashAccount(id=uuid.uuid4(), tenant_id=env.company_id, branch_id=env.branch_id,
                        type="TILL", currency="UZS", status="ACTIVE",
                        label=_ti.till_label(kod, None), created_at=NOW)
        s.add(a)
        s.commit()
        return a.id
    finally:
        s.close()


def _open_shift(env, till_id, *, opened_ago_h=1):
    s = _S(env)
    try:
        sid = uuid.uuid4()
        s.add(CashShift(id=sid, tenant_id=env.company_id, cash_account_id=till_id,
                        branch_id=env.branch_id, account_type="TILL", status="OPEN",
                        opened_at=NOW - timedelta(hours=opened_ago_h),
                        opened_by=env.employee_id, version=1))
        s.commit()
        return sid
    finally:
        s.close()


def _close_in_other_tx(env, shift_id):
    """BOSHQA tranzaksiya smenani yopadi va COMMIT qiladi."""
    s = _S(env)
    try:
        sh = s.get(CashShift, shift_id)
        sh.status = "CLOSED"
        sh.closed_at = NOW
        s.commit()
    finally:
        s.close()


def _legs(env, source_id):
    s = _S(env)
    try:
        return s.execute(text(
            "SELECT posting_kind, shift_id, amount FROM cash.cash_ledger_entries "
            "WHERE tenant_id = :t AND source_id = :s"),
            {"t": str(env.company_id), "s": str(source_id)}).mappings().all()
    finally:
        s.close()


def _exceptions(env):
    s = _S(env)
    try:
        return [r["kind"] for r in s.execute(text(
            "SELECT kind FROM cash.cash_ledger_exceptions WHERE tenant_id = :t"),
            {"t": str(env.company_id)}).mappings().all()]
    finally:
        s.close()


def _shift_status(env, sid):
    s = _S(env)
    try:
        return s.execute(text("SELECT status FROM cash.shifts WHERE id = :i"),
                         {"i": str(sid)}).scalar()
    finally:
        s.close()


def _debt_payment(env, till_id, *, source_id, amount=Decimal("100"), hook=None):
    """`customers.py` NAQD QARZ TO'LOVI yo'lining AYNAN o'zi — `public.shifts` QULFSIZ.

    `hook` berilsa, `_lock_candidate_shift` chaqirilishidan AYNAN OLDIN bajariladi.
    """
    from app.models.auth import Employee
    s = _S(env)
    real = CashPostingService._lock_candidate_shift
    try:
        emp = s.get(Employee, env.employee_id)
        if hook is not None:
            state = {"done": False}

            def wrapped(self, db, tenant_id, acct, origin_shift_id):
                if not state["done"]:
                    state["done"] = True
                    hook()
                return real(self, db, tenant_id, acct, origin_shift_id)

            CashPostingService._lock_candidate_shift = wrapped
        _cr.on_debt_payment(s, emp, branch_id=env.branch_id, payment_id=source_id,
                            cash_amount=amount, till_id=till_id)
        s.commit()
        return "ok"
    except Exception as e:                        # noqa: BLE001
        s.rollback()
        return f"{type(e).__name__}: {e}"
    finally:
        CashPostingService._lock_candidate_shift = real
        s.close()


# ══ A. ESKIRGAN STATUS — P9-06 NING YADROSI ═════════════════════════════════

def test_a_stale_status_yopilgan_smenaga_ON_SHIFT_tushmaydi(cashenv):
    """INVARIANT: qulf olingach qaror DB'DAGI HOZIRGI holatga tayanishi SHART.

    Yopilgan smenaga tushgan naqd `LATE_SYNC` + `LATE_SYNC_UNACK` bo'lishi kerak
    (ratifikatsiya qilingan Case C), ANOMALIYASIZ `ON_SHIFT` emas."""
    till = _till(cashenv)
    sid = _open_shift(cashenv, till)
    src = uuid.uuid4()

    r = _debt_payment(cashenv, till, source_id=src,
                      hook=lambda: _close_in_other_tx(cashenv, sid))
    assert r == "ok", r
    assert _shift_status(cashenv, sid) == "CLOSED"

    legs = _legs(cashenv, src)
    assert len(legs) == 1, legs
    kind = legs[0]["posting_kind"]
    excs = _exceptions(cashenv)

    assert kind != "ON_SHIFT" or "LATE_SYNC_UNACK" in excs, (
        f"ESKIRGAN HOLAT: smena CLOSED, lekin leg '{kind}' (shift_id={legs[0]['shift_id']}) "
        f"va anomaliya YO'Q (istisnolar: {excs}). Yopilgan va yarashtirilgan smenaga "
        f"{legs[0]['amount']} naqd ANOMALIYASIZ qo'shildi va `trg_cle_immutable` uni "
        "abadiy muzlatadi.")
    assert kind == "LATE_SYNC" and "LATE_SYNC_UNACK" in excs, (kind, excs)


# ══ B. EGALIK (cash_account) — ESKIRISHGA BOG'LIQ EMASLIGI ══════════════════

def test_b_begona_kassaning_smenasi_RAD_etiladi(cashenv):
    """`cand.cash_account_id` ham qarorga ta'sir qiladi. U o'zgarmas maydon, lekin
    qulfdan keyingi tekshiruv ishlashini QULFLAYMIZ (fail-closed saqlanadi)."""
    till_a = _till(cashenv)
    till_b = _till(cashenv)
    sid_b = _open_shift(cashenv, till_b)          # smena B kassasiniki
    src = uuid.uuid4()

    from app.models.auth import Employee
    from app.services.cash import adapters as _ad
    s = _S(cashenv)
    try:
        emp = s.get(Employee, cashenv.employee_id)
        try:
            # A kassasiga post, lekin B ning smenasi bilan -> RAD
            _ad.debt_payment(s, emp, cash_account_id=till_a, source_id=src,
                             amount=Decimal("50"), origin_shift_id=sid_b, commit=False)
            s.flush()
            out = "yozildi"
        except Exception as e:                    # noqa: BLE001
            out = f"{type(e).__name__}"
        finally:
            s.rollback()
    finally:
        s.close()
    assert out != "yozildi", "begona kassaning smenasi bilan leg yozildi"
    assert _legs(cashenv, src) == []


# ══ C. NORMAL (FRESH) YO'L — REGRESSIYA QO'RIQCHISI ═════════════════════════

def test_c_ochiq_smena_normal_ON_SHIFT(cashenv):
    """Hech kim yopmasa — avvalgidek `ON_SHIFT`, anomaliyasiz."""
    till = _till(cashenv)
    sid = _open_shift(cashenv, till)
    src = uuid.uuid4()
    assert _debt_payment(cashenv, till, source_id=src) == "ok"
    legs = _legs(cashenv, src)
    assert len(legs) == 1 and legs[0]["posting_kind"] == "ON_SHIFT", legs
    assert str(legs[0]["shift_id"]) == str(sid)


def test_c2_oldindan_YOPILGAN_smena_LATE_SYNC(cashenv):
    """Poyga yo'q, smena allaqachon yopiq — Case C avvalgidek ishlaydi."""
    till = _till(cashenv)
    sid = _open_shift(cashenv, till)
    _close_in_other_tx(cashenv, sid)
    src = uuid.uuid4()
    # Smena yopiq, shu bois `_open_cash_shift_id` uni TOPMAYDI -> origin None ->
    # Case D (OFF_SHIFT + UNRESOLVED_OFF_SHIFT). Bu MAVJUD, hujjatlangan xulq.
    assert _debt_payment(cashenv, till, source_id=src) == "ok"
    legs = _legs(cashenv, src)
    assert len(legs) == 1 and legs[0]["posting_kind"] == "OFF_SHIFT", legs
    assert "UNRESOLVED_OFF_SHIFT" in _exceptions(cashenv)


# ══ D. KONKURRENT — origin'SIZ shox (status WHERE ichida) ═══════════════════

def test_d_originsiz_shox_EvalPlanQual_bilan_xavfsiz(cashenv):
    """`origin_shift_id=None` shoxida `status == 'OPEN'` WHERE ichida: PostgreSQL
    qulfdan keyin shartni QAYTA baholaydi (EvalPlanQual), ya'ni yopilgan qator
    QAYTARILMAYDI. Bu shox eskirishdan TABIIY himoyalangan — shuni qulflaymiz."""
    till = _till(cashenv)
    sid = _open_shift(cashenv, till)
    src = uuid.uuid4()
    from app.models.auth import Employee
    from app.services.cash import adapters as _ad
    s = _S(cashenv)
    real = CashPostingService._lock_candidate_shift
    state = {"done": False}
    try:
        emp = s.get(Employee, cashenv.employee_id)

        def wrapped(self, db, tenant_id, acct, origin_shift_id):
            if not state["done"]:
                state["done"] = True
                _close_in_other_tx(cashenv, sid)
            return real(self, db, tenant_id, acct, origin_shift_id)

        CashPostingService._lock_candidate_shift = wrapped
        _ad.manual_cash_in(s, emp, cash_account_id=till, source_id=src,
                           amount=Decimal("70"), origin_shift_id=None, commit=False)
        s.commit()
    finally:
        CashPostingService._lock_candidate_shift = real
        s.close()
    legs = _legs(cashenv, src)
    assert len(legs) == 1 and legs[0]["posting_kind"] == "OFF_SHIFT", legs
    assert legs[0]["shift_id"] is None


# ══ E. IJARACHI IZOLYATSIYASI ═══════════════════════════════════════════════

def test_e_begona_ijarachining_smenasi_KORINMAYDI(cashenv):
    """Qulf so'rovi `tenant_id` bilan chegaralangan — boshqa ijarachining ayni
    id'li smenasi TOPILMAYDI va leg YOZILMAYDI."""
    till = _till(cashenv)
    sid = _open_shift(cashenv, till)
    s = _S(cashenv)
    try:
        svc = CashPostingService()
        acct = s.get(CashAccount, till)
        got = svc._lock_candidate_shift(s, uuid.uuid4(), acct, sid)   # BEGONA tenant
    finally:
        s.rollback()
        s.close()
    assert got is None, "begona ijarachi smenasi qulflandi"


# ══ F. P9-05 YOPILISH GARDI BILAN O'ZARO TA'SIR ════════════════════════════

def test_f_sotuv_yoli_3A_qulfi_bilan_HIMOYALANGAN(cashenv):
    """SOTUV yo'lida eskirish oynasi OCHILMAYDI: `sales.py` `public.shifts` ni
    qulflaydi va `close_shift` ayni qatorni kutadi. Bu sinov `on_cash_sale` ning
    o'z smenasiga to'g'ri bog'lanishini qulflaydi (P9-05/3A regressiya qo'riqchisi)."""
    from app.models.auth import Employee
    till = _till(cashenv)
    sid = _open_shift(cashenv, till)
    src = uuid.uuid4()
    s = _S(cashenv)
    try:
        emp = s.get(Employee, cashenv.employee_id)
        _cr.on_cash_sale(s, emp, branch_id=cashenv.branch_id, sale_id=src,
                         cash_amount=Decimal("120"), device_occurred_at=NOW,
                         terminal_id=None, till_id=till, shift_id=sid)
        s.commit()
    finally:
        s.close()
    legs = _legs(cashenv, src)
    assert len(legs) == 1 and legs[0]["posting_kind"] == "ON_SHIFT", legs
    assert str(legs[0]["shift_id"]) == str(sid)

# ══ G. MEXANIZMNING O'ZI — HOZIR YETIB BORILMAYDI, LEKIN MAVJUD ════════════

@pytest.mark.xfail(strict=True, reason=(
    "P9-06 mexanizmi MAVJUD (`populate_existing()` yo'q), lekin bugun HECH BIR "
    "ishlab chiqarish yozuvchisida yuz bermaydi: hammasi CashShift obyektini "
    "qulfdan OLDIN tashlab yuboradi va identity-map ZAIF (`WeakInstanceDict`). "
    "Ega qarori bo'yicha kod O'ZGARTIRILMADI. `populate_existing` qo'shilsa bu "
    "sinov XPASS bo'ladi — o'shanda markerni OLIB TASHLANG."))
def test_g_MEXANIZM_kuchli_havola_bolsa_qulf_ESKIRGAN_obyekt_qaytaradi(cashenv):
    """Obyektga KUCHLI havola saqlansa, `_lock_candidate_shift` SQL qulfini oladi,
    lekin identity-map'dagi ESKI nusxani qaytaradi va `status` eskirgan bo'ladi.

    Bu — kelajak uchun qo'riqchi: bugun biror chaqiruvchi yuklangan smenani
    USHLAB QOLSA (masalan `sh.id` o'rniga `sh` ni uzatsa, yoki jurnalga yozsa),
    himoya JIMGINA yo'qoladi va Case C (LATE_SYNC + anomaliya) Case A ga aylanadi."""
    till = _till(cashenv)
    sid = _open_shift(cashenv, till)
    s = _S(cashenv)
    try:
        from app.services.cash import repositories as repo
        loaded = repo.open_shift_for_account(s, cashenv.company_id, till)  # KUCHLI havola
        assert loaded is not None and loaded.status == "OPEN"
        _close_in_other_tx(cashenv, sid)
        assert _shift_status(cashenv, sid) == "CLOSED"

        svc = CashPostingService()
        acct = s.get(CashAccount, till)
        cand = svc._lock_candidate_shift(s, cashenv.company_id, acct, sid)
        assert cand is not None
        assert cand.status == "CLOSED", (
            f"ESKIRGAN: qulf olindi, lekin identity-map '{cand.status}' qaytardi "
            f"(DB'da CLOSED). `_resolve_shift` buni Case A deb o'qiydi va yopilgan "
            "smenaga ANOMALIYASIZ ON_SHIFT legi yozadi.")
    finally:
        s.rollback()
        s.close()
