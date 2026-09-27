# -*- coding: utf-8 -*-
"""PHASE 2 — CUSTODY DOMENI (hisob-turiga xos validatsiya) + O'QISH YO'LI.

NUQSON (tuzatishdan oldin): `resolve_cash_custody` ochiq smena bo'lganda custody'ni
SHARTSIZ `shift.till_id` ga bog'lardi va boshqa har qanday hisobni
`ERR_TILL_SHIFT_MISMATCH` bilan rad etardi — SEYFni HAM. Ya'ni kassir navbatda
turgani do'kon egasiga KOMPANIYA SEYFIDAN yetkazuvchiga to'lashni to'sardi.

Bu jismoniy haqiqatga ham, sxemaning O'ZIGA ham qarshi: seyf oyog'i HAR DOIM
`OFF_SHIFT` (`cle_posting_shift`, `cle_shift_fk`, jadval izohi «SAFE legs are always
OFF_SHIFT (SAFE owns no shift)»; `posting._resolve_shift` ham SAFE uchun shunday).

TUZATISH — amalning CUSTODY DOMENI e'lon qilinadi:
    SHIFT_BOUND  kassirning yashik seansi qismi          -> TILL qoidasi TO'LIQ
    TREASURY     kompaniya pulining harakati             -> SEYF smenadan MUSTAQIL

⚠️  GLOBAL DARVOZA OLIB TASHLANMAGAN. `ERR_TILL_SHIFT_MISMATCH` TILL uchun
    bit-ba-bit saqlanadi (boshqa kassirning yashigi ham rad etiladi), va domeni
    e'lon qilinmagan amal `SHIFT_BOUND` (eng qattiq) deb qabul qilinadi.
    Manfiy nazorat sifatida har SEYF holati `domain=None` bilan ham o'lchanadi.

O'QISH YO'LI: `decide()` TREASURY amalida `options` ni to'ldiradi — aks holda server
SEYFni qabul qilib, Manager ekrani uni KO'RSATA OLMASDI (darvoza server tomonida
ochilib, UI tomonida yopiq qolardi).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.cash import CashLedgerEntry as CLE
from app.models.settings import Setting
from app.services.cash import custody_preview as CP
from app.services.cash import cutover_guard as CG

from tests.cash.test_custody_and_inkassa import _acct, _hex, _now, _open_shift, _tenant


# ══ yordamchilar ════════════════════════════════════════════════════════════
def _t0(db, co):
    """T0 (cutover) ni O'TGAN qilib belgilaydi — post-T0 qoidalari kuchga kiradi."""
    db.add(Setting(company_id=co.id, branch_id=None, key="cash",
                   value={"cutover_at": (_now() - timedelta(hours=1)).isoformat()}))
    db.commit()


def _resolve(db, co, br, *, shift=None, account=None, operation=CP.OP_RECEIVING, domain="TREASURY"):
    return CG.resolve_cash_custody(
        db, company_id=co.id, branch_id=br.id, operation=operation, shift=shift,
        cash_account_id=(account.id if account is not None else None),
        domain=(CG.DOMAIN_TREASURY if domain == "TREASURY" else domain))


def _rad(db, **kw):
    """Chaqiruv RAD etilishini kutadi; xato kodini qaytaradi."""
    with pytest.raises(HTTPException) as ei:
        _resolve(db, **kw)
    db.rollback()
    return str(ei.value.detail)


# ══ TILL SHARTNOMASI — bit-ba-bit saqlanadi (1-5) ═══════════════════════════
def test_01_TILL_ochiq_smena_bilan_PASS(db, cashenv):
    co, br, emp, till, _safe = _tenant(db, cashenv)
    _t0(db, co)
    sh = _open_shift(db, br, emp, till)
    #  hisob berilmasa — server smenadan hal qiladi
    acc, enforced = _resolve(db, co, br, shift=sh)
    assert acc.id == till.id and enforced is True
    #  AYNI kassa aniq berilsa ham o'tadi
    acc2, _ = _resolve(db, co, br, shift=sh, account=till)
    assert acc2.id == till.id


def test_02_TILL_smenasiz_server_HAL_QILMAYDI(db, cashenv):
    """Smena yo'q + hisob berilmagan -> `ERR_CUSTODY_REQUIRED` (TAXMIN YO'Q).

    ⚠️  Smenasiz + ANIQ berilgan TILL o'tadi — bu Phase 2 dan OLDIN ham shunday edi
        va o'zgarmadi (pastdagi ikkinchi assert).
    """
    co, br, _emp, till, _safe = _tenant(db, cashenv)
    _t0(db, co)
    assert CG.ERR_CUSTODY_REQUIRED in _rad(db, co=co, br=br, shift=None, account=None)
    acc, _ = _resolve(db, co, br, shift=None, account=till)
    assert acc.id == till.id


def test_03_TILL_BOSHQA_smenaning_kassasi_RAD(db, cashenv):
    """REGRESSIYA QO'RIQCHISI: global `TILL_SHIFT_MISMATCH` olib tashlanmagan."""
    co, br, emp, till, _safe = _tenant(db, cashenv)
    till2 = _acct(db, co, br, "TILL"); db.commit()
    _t0(db, co)
    sh = _open_shift(db, br, emp, till)
    assert CG.ERR_TILL_SHIFT_MISMATCH in _rad(db, co=co, br=br, shift=sh, account=till2)


def test_04_TILL_boshqa_filial_RAD(db, cashenv):
    co, br, _emp, _till, _safe = _tenant(db, cashenv)
    from app.models.org import Branch
    br2 = Branch(company_id=co.id, code="X" + _hex(), name="F2", is_active=True)
    db.add(br2); db.flush()
    chet_till = _acct(db, co, br2, "TILL"); db.commit()
    _t0(db, co)
    assert CG.ERR_CUSTODY_INVALID in _rad(db, co=co, br=br, shift=None, account=chet_till)


def test_05_TILL_arxivlangan_RAD(db, cashenv):
    co, br, _emp, _till, _safe = _tenant(db, cashenv)
    arx = _acct(db, co, br, "TILL", status="ARCHIVED"); db.commit()
    _t0(db, co)
    assert CG.ERR_CUSTODY_INVALID in _rad(db, co=co, br=br, shift=None, account=arx)


# ══ SEYF SHARTNOMASI (6-10) ═════════════════════════════════════════════════
def test_06_SAFE_smenasiz_PASS_va_oyoq_OFF_SHIFT(db, cashenv):
    co, br, emp, _till, safe = _tenant(db, cashenv)
    _t0(db, co)
    acc, enforced = _resolve(db, co, br, shift=None, account=safe)
    assert acc.id == safe.id and enforced is True

    #  Haqiqiy oyoq: `shift_id` NULL va `posting_kind` OFF_SHIFT
    from app.services.cash import adapters as _ad
    import uuid as _u
    _ad.manual_cash_in(db, emp, cash_account_id=safe.id, source_id=_u.uuid4(),
                       amount=Decimal("50000"), commit=True)
    leg = (db.query(CLE).filter(CLE.tenant_id == co.id, CLE.cash_account_id == safe.id)
           .order_by(CLE.recorded_at.desc()).first())
    assert leg is not None and leg.shift_id is None
    assert str(leg.posting_kind) == "OFF_SHIFT"


def test_07_SAFE_smenali_oyoq_BAZA_darajasida_RAD(db, cashenv):
    """«SAFE + shift_id berilgan -> rad» — DB invarianti bilan qotiriladi.

    Xizmat qatlami SEYF uchun `origin_shift_id` ni NORMALLASHTIRADI
    (`posting._resolve_shift`: SAFE -> OFF_SHIFT, shift_id=None). Shu bois «rad»
    ni xizmatdan emas, BAZADAN o'lchaymiz: `cle_posting_shift` CHECK ON_SHIFT
    seyf oyog'ini PRINSIPIAL ravishda yozdirmaydi.
    """
    co, br, emp, till, safe = _tenant(db, cashenv)
    #  TILL uchun HAQIQIY `cash.shifts` qatori (SEYF hech qachon smena ocholmaydi:
    #  `sh_type_till` CHECK) — keyin AYNI smenani SEYF oyog'iga bog'lashga urinamiz.
    csid = db.execute(text(
        "INSERT INTO cash.shifts (tenant_id, cash_account_id, branch_id, account_type, "
        "                         status, opened_at, opened_by) "
        "VALUES (:t, :a, :b, 'TILL', 'OPEN', now(), :e) RETURNING id"),
        {"t": str(co.id), "a": str(till.id), "b": str(br.id), "e": str(emp.id)}).scalar()
    db.commit()
    assert csid is not None
    with pytest.raises(IntegrityError):
        db.execute(text(
            "INSERT INTO cash.cash_ledger_entries "
            "(tenant_id, cash_account_id, branch_id, account_type, shift_id, posting_kind, "
            " source_type, source_id, leg_index, direction, category, amount, currency, "
            " device_occurred_at, server_received_at, idempotency_key) "
            "VALUES (:t, :a, :b, 'SAFE', :s, 'ON_SHIFT', 'CASH_OP', gen_random_uuid(), 0, "
            "        'IN', 'CASH_IN', 1000, 'UZS', now(), now(), :k)"),
            {"t": str(co.id), "a": str(safe.id), "b": str(br.id), "s": str(csid),
             "k": "p2-" + _hex()})
        db.flush()
    db.rollback()


def test_08_SAFE_BOSHQA_TILLda_ochiq_smena_borda_HAM_PASS(db, cashenv):
    """PHASE 2 NING O'ZAGI + manfiy nazorat.

    TREASURY domenida ochiq smena SEYFga TA'SIR QILMAYDI. AYNI chaqiruv
    `SHIFT_BOUND` (domeni e'lon qilinmagan) bo'lsa — avvalgidek RAD etiladi,
    ya'ni darvoza GLOBAL o'chirilmagan.
    """
    co, br, emp, till, safe = _tenant(db, cashenv)
    _t0(db, co)
    sh = _open_shift(db, br, emp, till)

    acc, enforced = _resolve(db, co, br, shift=sh, account=safe)          # TREASURY
    assert acc.id == safe.id and enforced is True

    #  MANFIY NAZORAT: domen SHIFT_BOUND -> eski xatti-harakat
    assert CG.ERR_TILL_SHIFT_MISMATCH in _rad(
        db, co=co, br=br, shift=sh, account=safe, domain=CG.DOMAIN_SHIFT_BOUND)
    #  va domen UMUMAN berilmasa ham (fail-closed default)
    assert CG.ERR_TILL_SHIFT_MISMATCH in _rad(
        db, co=co, br=br, shift=sh, account=safe, domain=None)


def test_09_SAFE_boshqa_filial_RAD(db, cashenv):
    co, br, emp, till, _safe = _tenant(db, cashenv)
    from app.models.org import Branch
    br2 = Branch(company_id=co.id, code="Y" + _hex(), name="F3", is_active=True)
    db.add(br2); db.flush()
    chet_safe = _acct(db, co, br2, "SAFE"); db.commit()
    _t0(db, co)
    sh = _open_shift(db, br, emp, till)
    assert CG.ERR_CUSTODY_INVALID in _rad(db, co=co, br=br, shift=sh, account=chet_safe)


def test_10_SAFE_arxivlangan_RAD(db, cashenv):
    co, br, emp, till, _safe = _tenant(db, cashenv)
    arx = _acct(db, co, br, "SAFE", status="ARCHIVED"); db.commit()
    _t0(db, co)
    sh = _open_shift(db, br, emp, till)
    assert CG.ERR_CUSTODY_INVALID in _rad(db, co=co, br=br, shift=sh, account=arx)


# ══ 0 / 1 / N TILL — TAXMIN YO'Q (11-14) ════════════════════════════════════
def test_11_nol_TILL_faqat_SEYF_tanlovda(db, cashenv):
    co, br, _emp, till, safe = _tenant(db, cashenv)
    till.status = "ARCHIVED"; db.commit()          # filialda FAOL TILL qolmadi
    _t0(db, co)
    turlar = [o["type"] for o in CP.custody_options(db, co.id, br.id)]
    assert turlar == ["SAFE"], turlar
    assert CG.ERR_CUSTODY_REQUIRED in _rad(db, co=co, br=br, shift=None, account=None)


def test_12_bitta_TILL_ham_AVTOMATIK_tanlanmaydi(db, cashenv):
    co, br, _emp, till, _safe = _tenant(db, cashenv)
    _t0(db, co)
    assert len([o for o in CP.custody_options(db, co.id, br.id) if o["type"] == "TILL"]) == 1
    #  YAGONA TILL bo'lsa ham server uni TANLAMAYDI
    assert CG.ERR_CUSTODY_REQUIRED in _rad(db, co=co, br=br, shift=None, account=None)
    _ = till


def test_13_N_TILL_hammasi_tanlovda(db, cashenv):
    co, br, _emp, _till, _safe = _tenant(db, cashenv)
    for _ in range(2):
        _acct(db, co, br, "TILL")
    _acct(db, co, br, "TILL", status="ARCHIVED")      # arxiv ro'yxatga TUSHMAYDI
    db.commit()
    _t0(db, co)
    opts = CP.custody_options(db, co.id, br.id)
    assert len([o for o in opts if o["type"] == "TILL"]) == 3
    assert len([o for o in opts if o["type"] == "SAFE"]) == 1


def test_14_ikki_TILL_AUTO_FIRST_yoq(db, cashenv):
    co, br, _emp, _till, _safe = _tenant(db, cashenv)
    _acct(db, co, br, "TILL"); db.commit()
    _t0(db, co)
    kod = _rad(db, co=co, br=br, shift=None, account=None)
    assert CG.ERR_CUSTODY_REQUIRED in kod
    #  hech qanday hisob QAYTARILMAGANIGA ishonch: dry-run ham hisob bermaydi
    acc, _enf, code = CG.preview_cash_custody(
        db, company_id=co.id, branch_id=br.id, operation=CP.OP_RECEIVING,
        shift=None, cash_account_id=None, domain=CG.DOMAIN_TREASURY)
    assert acc is None and code == CG.ERR_CUSTODY_REQUIRED


# ══ O'QISH YO'LI (15-16) ════════════════════════════════════════════════════
def test_15_oqish_API_hisob_TURLARINI_togri_qaytaradi(db, cashenv):
    co, br, _emp, till, safe = _tenant(db, cashenv)
    db.commit()
    opts = {o["id"]: o["type"] for o in CP.custody_options(db, co.id, br.id)}
    assert opts.get(str(till.id)) == "TILL"
    assert opts.get(str(safe.id)) == "SAFE"
    #  arxivlangan hisob TANLOVDA YO'Q (operator soxta tanlov ko'rmasin)
    arx = _acct(db, co, br, "SAFE", status="ARCHIVED"); db.commit()
    assert str(arx.id) not in {o["id"] for o in CP.custody_options(db, co.id, br.id)}


def test_16_ochiq_smenada_oqish_yoli_SEYFni_KORSATADI(db, cashenv):
    """GATE TOPILMASI: o'qish yo'li SEYFni jimgina yo'qotardi.

    Ochiq smenada `decide()` `SERVER_RESOLVED` + `options=[]` qaytarardi, ya'ni
    Manager ekrani seyfni TANLAB BO'LMASDI — server uni qabul qilsa ham.

    Manfiy nazorat: `SHIFT_BOUND` amal (`OP_DEBT`) uchun `options` AVVALGIDEK
    bo'sh qoladi — Phase 2 uni qayta tasniflamaydi.
    """
    co, br, emp, till, safe = _tenant(db, cashenv)
    _t0(db, co)
    sh = _open_shift(db, br, emp, till)

    blok = CP.decide(db, emp, branch_id=br.id, shift=sh, operation=CP.OP_RECEIVING,
                     options=lambda: CP.custody_options(db, co.id, br.id))
    assert blok["mode"] == CP.MODE_SERVER_RESOLVED
    assert blok["resolved"]["id"] == str(till.id)          # standart — smena kassasi
    turlar = {o["type"] for o in blok["options"]}
    assert "SAFE" in turlar, "o'qish yo'li SEYFni ko'rsatmadi (gate nuqsoni QAYTGAN)"
    assert str(safe.id) in {o["id"] for o in blok["options"]}

    #  MANFIY NAZORAT — SHIFT_BOUND amalda tanlov ochilmaydi
    blok2 = CP.decide(db, emp, branch_id=br.id, shift=sh, operation=CP.OP_DEBT,
                      options=lambda: CP.custody_options(db, co.id, br.id))
    assert blok2["mode"] == CP.MODE_SERVER_RESOLVED
    assert blok2["options"] == [], "SHIFT_BOUND amal uchun tanlov OCHILDI"


# ══ DOMEN XARITASI — fail-closed ════════════════════════════════════════════
def test_domen_xaritasi_fail_closed_va_konstantalar_MOS(db, cashenv):
    assert CP.operation_domain(CP.OP_RECEIVING) == CG.DOMAIN_TREASURY
    assert CP.operation_domain(CP.OP_SUPPLIER) == CG.DOMAIN_TREASURY
    assert CP.operation_domain(CP.OP_CASH_PURCHASE) == CG.DOMAIN_TREASURY
    #  e'lon qilinmagan amal -> eng qattiq domen
    assert CP.operation_domain("yangi_amal_" + _hex()) == CG.DOMAIN_SHIFT_BOUND
    assert CP.operation_domain(CP.OP_DEBT) == CG.DOMAIN_SHIFT_BOUND
    #  xaritadagi literal qiymat konstanta bilan AYNI (drift qo'riqchisi)
    assert set(CP.OPERATION_DOMAIN.values()) == {CG.DOMAIN_TREASURY}


# ══ PHASE 2 TUZATISH — ISSUE 1: `cash_purchase` O'QISH YO'LI ════════════════
def test_18_cash_purchase_preview_SEYFni_qaytaradi(db, cashenv):
    """Yozuvchi TREASURY bo'lsa, o'qish yo'li ham SHU amal uchun TREASURY bo'lishi kerak.

    ILGARI: `cash_purchase` uchun preview amali UMUMAN yo'q edi — backend SEYFni
    qabul qilardi, Manager esa uni tanlash uchun option OLA OLMASDI (Phase 2
    asimmetriyasi).
    """
    co, br, emp, till, safe = _tenant(db, cashenv)
    _t0(db, co)
    _open_shift(db, br, emp, till)

    blok = CP.preview(db, emp, "cash_purchase")
    assert blok["branch"]["id"] == str(br.id)
    assert blok["mode"] == CP.MODE_SERVER_RESOLVED
    assert blok["resolved"]["id"] == str(till.id) and blok["resolved"]["type"] == "TILL"
    idlar = {o["id"] for o in blok["options"]}
    assert str(safe.id) in idlar, "cash_purchase preview SEYFni bermadi"
    assert str(till.id) in idlar
    assert {o["type"] for o in blok["options"]} == {"TILL", "SAFE"}
    #  ruxsat xaritasi ham to'ldirilgan (yozuvchi darvozasi bilan AYNI)
    assert CP.PREVIEW_PERMISSIONS["cash_purchase"] == "xaridlar.edit"
    assert CP.operation_domain(CP.OP_CASH_PURCHASE) == CG.DOMAIN_TREASURY


def test_19_cash_purchase_preview_ARXIVLANGAN_SEYFni_bermaydi(db, cashenv):
    co, br, emp, till, safe = _tenant(db, cashenv)
    arx_safe = _acct(db, co, br, "SAFE", status="ARCHIVED")
    arx_till = _acct(db, co, br, "TILL", status="ARCHIVED")
    db.commit()
    _t0(db, co)
    _open_shift(db, br, emp, till)

    idlar = {o["id"] for o in CP.preview(db, emp, "cash_purchase")["options"]}
    assert str(arx_safe.id) not in idlar, "arxivlangan SEYF tanlovda"
    assert str(arx_till.id) not in idlar, "arxivlangan TILL tanlovda"
    assert {str(till.id), str(safe.id)} <= idlar


def test_20_cash_purchase_preview_BEGONA_FILIAL_izolyatsiyasi(db, cashenv):
    """Boshqa filialning TILL/SAFE hisobi tanlovda KO'RINMAYDI."""
    from app.models.org import Branch
    co, br, emp, till, safe = _tenant(db, cashenv)
    br2 = Branch(company_id=co.id, code="Z" + _hex(), name="F4", is_active=True)
    db.add(br2)
    db.flush()
    chet_till = _acct(db, co, br2, "TILL")
    chet_safe = _acct(db, co, br2, "SAFE")
    db.commit()
    _t0(db, co)
    _open_shift(db, br, emp, till)

    blok = CP.preview(db, emp, "cash_purchase")
    idlar = {o["id"] for o in blok["options"]}
    assert blok["branch"]["id"] == str(br.id)
    assert str(chet_till.id) not in idlar and str(chet_safe.id) not in idlar
    assert idlar == {str(till.id), str(safe.id)}


def test_21_cash_purchase_preview_YOZUVCHI_bilan_AYNI_kontekst(db, cashenv):
    """Filial va smena preview'da ham, yozuvchida ham AYNI yordamchidan.

    Drift qo'riqchisi: `create_purchase` smenani `actor_open_shift` bilan oladi va
    filialni AYNI ifoda bilan hal qiladi. Ikkisi ajralib ketsa ekran bir hisobni
    ko'rsatib, server boshqasini yozardi.
    """
    co, br, emp, till, _safe = _tenant(db, cashenv)
    _t0(db, co)
    sh = _open_shift(db, br, emp, till)

    p_br, p_sh = CP.cash_purchase_ctx(db, emp)
    assert str(p_br.id) == str(br.id)
    assert p_sh is not None and str(p_sh.id) == str(sh.id)
    assert CP.preview(db, emp, "cash_purchase")["branch"]["id"] == str(br.id)


def test_22_cash_purchase_preview_0_1_N_TILL_va_AUTO_FIRST_yoq(db, cashenv):
    """0/1/N TILL semantikasi saqlangan; 2+ TILL da AVTOMATIK tanlov YO'Q."""
    from app.models.cash import CashAccount
    co, br, emp, till, safe = _tenant(db, cashenv)
    _t0(db, co)

    #  1 TILL, smenasiz -> OPERATOR_MUST_CHOOSE, tanlovda 1 TILL + 1 SAFE
    b1 = CP.preview(db, emp, "cash_purchase")
    assert b1["mode"] == CP.MODE_OPERATOR_MUST_CHOOSE and b1["resolved"] is None
    assert len([o for o in b1["options"] if o["type"] == "TILL"]) == 1

    #  N TILL, smenasiz -> hamon TANLOV, oldindan tanlanmagan (auto-first YO'Q)
    _acct(db, co, br, "TILL")
    db.commit()
    b2 = CP.preview(db, emp, "cash_purchase")
    assert b2["mode"] == CP.MODE_OPERATOR_MUST_CHOOSE and b2["resolved"] is None
    assert len([o for o in b2["options"] if o["type"] == "TILL"]) == 2
    assert CG.ERR_CUSTODY_REQUIRED in _rad(db, co=co, br=br, shift=None, account=None,
                                           operation=CP.OP_CASH_PURCHASE)

    #  0 TILL -> faqat SEYF
    for a in db.query(CashAccount).filter(CashAccount.tenant_id == co.id,
                                          CashAccount.type == "TILL").all():
        a.status = "ARCHIVED"
    db.commit()
    b3 = CP.preview(db, emp, "cash_purchase")
    assert {o["type"] for o in b3["options"]} == {"SAFE"}
    assert str(safe.id) in {o["id"] for o in b3["options"]}
    _ = till


# ══ PHASE 2 TUZATISH — ISSUE 2: SEYF + zid `shift_id` FAIL-CLOSED ═══════════
def _till_cash_shift(db, co, br, till, emp):
    """TILL uchun HAQIQIY `cash.shifts` qatori (SEYF uchun bunday qator IMKONSIZ)."""
    return db.execute(text(
        "INSERT INTO cash.shifts (tenant_id, cash_account_id, branch_id, account_type, "
        "                         status, opened_at, opened_by) "
        "VALUES (:t, :a, :b, 'TILL', 'OPEN', now(), :e) RETURNING id"),
        {"t": str(co.id), "a": str(till.id), "b": str(br.id), "e": str(emp.id)}).scalar()


def test_23_SAFE_ANIQ_shift_id_bilan_XIZMAT_chegarasida_RAD(db, cashenv):
    """Zid `shift_id` JIMGINA TASHLANMAYDI — `SHIFT_NOT_BELONG_TO_ACCOUNT`.

    ILGARI: `posting._resolve_shift` SEYF uchun `origin_shift_id` ni indamay
    tashlab, oyoqni OFF_SHIFT qilib yozardi (silent normalization). Shartnoma
    esa «any supplied shift_id => FAIL» deydi.

    ⚠️  API yuzasi: klient `shift_id` YUBORMAYDI — u serverda HISOB BO'YICHA hal
        qilinadi (`retrofit._open_cash_shift_id` SEYF uchun har doim None, chunki
        `cash.shifts` da SEYF qatori `sh_type_till` CHECK bilan imkonsiz). Shu bois
        shartnoma XIZMAT chegarasida (`CashPostingService`) qotiriladi.
    """
    from app.services.cash import adapters as _ad
    from app.services.cash.errors import CashError, CashPostingError
    import uuid as _u
    co, br, emp, till, safe = _tenant(db, cashenv)
    csid = _till_cash_shift(db, co, br, till, emp)
    db.commit()

    oldin = db.query(CLE).filter(CLE.tenant_id == co.id).count()
    with pytest.raises(CashPostingError) as ei:
        _ad.manual_cash_in(db, emp, cash_account_id=safe.id, source_id=_u.uuid4(),
                           amount=Decimal("10000"), origin_shift_id=csid, commit=True)
    db.rollback()
    assert ei.value.code == CashError.SHIFT_NOT_BELONG_TO_ACCOUNT, ei.value.code
    assert db.query(CLE).filter(CLE.tenant_id == co.id).count() == oldin, "oyoq YOZILDI"


def test_24_SAFE_shift_id_NULL_boshqa_TILLda_ochiq_smena_bilan_PASS(db, cashenv):
    """SEYF + `shift_id=NULL`, boshqa TILLda ochiq smena bor -> O'TADI, oyoq OFF_SHIFT."""
    from app.services.cash import adapters as _ad
    import uuid as _u
    co, br, emp, till, safe = _tenant(db, cashenv)
    _till_cash_shift(db, co, br, till, emp)      # TILLda OCHIQ smena bor
    _t0(db, co)
    _open_shift(db, br, emp, till)               # legacy smena ham ochiq

    #  custody: SEYF qabul qilinadi (TREASURY)
    acc, _ = _resolve(db, co, br, shift=None, account=safe)
    assert acc.id == safe.id

    #  posting: oyoq OFF_SHIFT / shift_id NULL
    _ad.manual_cash_in(db, emp, cash_account_id=safe.id, source_id=_u.uuid4(),
                       amount=Decimal("25000"), origin_shift_id=None, commit=True)
    leg = (db.query(CLE).filter(CLE.tenant_id == co.id, CLE.cash_account_id == safe.id)
           .order_by(CLE.recorded_at.desc()).first())
    assert leg is not None and leg.shift_id is None
    assert str(leg.posting_kind) == "OFF_SHIFT"
