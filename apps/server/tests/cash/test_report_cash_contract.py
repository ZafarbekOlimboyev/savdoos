# -*- coding: utf-8 -*-
"""PUL HISOBOTI YARIM MA'LUMOT BILAN 200 QAYTARMAYDI (`GET /reports/cashflow`).

Ledger-native do'konda naqd xarid chiqimi FAQAT ledgerda bor (`CashMovement` yozilmaydi), ya'ni
o'sha son uchun boshqa manba YO'Q. Ilgari ledger o'qishi yiqilsa hisobot jimgina legacy shaklga
tushardi: `naqd_xarid` 0 bo'lib qolardi va `kassada` xarid summasicha KO'P ko'rinardi — 200 bilan
moliyaviy yolg'on (faylning o'z izohi: «hisobot 500 000 deydi, yashikda 300 000 turadi»).

SHARTNOMA:
  A) ledger AVTORITET + o'qish yiqildi     -> 503 `CASH_LEDGER_UNAVAILABLE` (yarim hisobot YO'Q)
  B) ledger AVTORITET EMAS (legacy/SQLite) -> eski legacy xulq AYNAN saqlanadi
  C) diagnostik bayroq avtoritet yiqilishini 200 ga AYLANTIRMAYDI

AVTORITET = `Setting(key='cash').value.ledger_native is True` **va** dialekt Postgres
(`services/cash/tenant.py · is_ledger_authoritative`) — `cash_enabled()` (infra darvozasi) EMAS.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.v1 import purchases as purchases_api
from app.api.v1 import reports as reports_api
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashAccount
from app.models.catalog import Product, Unit
from app.models.inventory import Inventory
from app.models.org import Branch, Company
from app.models.purchasing import Supplier
from app.models.settings import Setting
from app.schemas.purchase import PurchaseCreate, PurchaseItemIn
from app.services.cash import cutover_guard as CG
from app.services.cash import mode
from app.services.cash import tenant as _tn
from app.services.cash import till_identity as _ti


@pytest.fixture(autouse=True)
def _reset_mode():
    yield
    mode.reset_mode()


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _tenant(db, *, native: bool):
    """`native=True` -> `ledger_native` bayrog'i bilan (AVTORITET); aks holda legacy tenant."""
    co = Company(name="RC" + _hex(), code="rc" + _hex(), currency="UZS"); db.add(co); db.flush()
    br = Branch(company_id=co.id, code="B" + _hex(), name="F", is_active=True); db.add(br); db.flush()
    emp = Employee(company_id=co.id, full_name="K", role_id=db.query(Role).first().id)
    db.add(emp); db.flush(); db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id))
    till = CashAccount(tenant_id=co.id, branch_id=br.id, type="TILL", currency="UZS",
                       status="ACTIVE", label=_ti.till_label("T-" + _hex(), None), created_at=_now())
    db.add(till); db.flush()
    iso = (_now() - timedelta(hours=2)).isoformat()
    val = {"cutover_at": iso}
    if native:
        val = {"ledger_native": True, "onboarded_at": iso, "cutover_at": iso}
    db.add(Setting(company_id=co.id, branch_id=None, key="cash", value=val))
    db.commit()
    return co, br, emp, till


def _product(db, co, br):
    u = Unit(code="u" + _hex(), name="dona"); db.add(u); db.flush()
    p = Product(company_id=co.id, article_code="A" + _hex(), name="M" + _hex(), unit_id=u.id,
                base_buy_price=Decimal("1000"), base_sell_price=Decimal("2000"),
                tax_rate=Decimal("0"))
    db.add(p); db.flush()
    db.add(Inventory(product_id=p.id, branch_id=br.id, qty=Decimal("0"), updated_at=_now()))
    db.commit(); return p


def _fund(db, emp, acc, amount="90000"):
    from app.services.cash import adapters as _ad
    _ad.manual_cash_in(db, emp, cash_account_id=acc.id, source_id=uuid.uuid4(),
                       amount=Decimal(amount), commit=True)


def _buy_cash(db, emp, co, br, till, cost="7000"):
    sup = Supplier(company_id=co.id, name="S" + _hex()); db.add(sup); db.commit()
    prod = _product(db, co, br)
    purchases_api._create_purchase_once(
        PurchaseCreate(supplier_id=sup.id, status="received", cash_account_id=till.id,
                       items=[PurchaseItemIn(product_id=prod.id, qty=1, unit_cost=float(cost))]),
        emp, db)
    db.commit()


def _cashflow(emp, db):
    return reports_api.cashflow(period="day", emp=emp, db=db)


def _boom(*a, **k):
    raise RuntimeError("ledger o'qilmadi (sinov)")


# ═══ 1) AVTORITET + ledger SOG'LOM -> normal 200 ═════════════════════════════
def test_1_avtoritet_va_sogLom_ledger_normal_javob(db, cashenv):
    co, br, emp, till = _tenant(db, native=True)
    _fund(db, emp, till)
    _buy_cash(db, emp, co, br, till, cost="7000")
    out = _cashflow(emp, db)
    assert out["ledger_native"] is True
    assert out["out"]["naqd_xarid"] == 7000.0, out["out"]
    assert "xarid_qaytdi" in out["in"]
    assert "ledger_error" not in out, "diagnostik bayroq 200 javobni yumshatmasin"


# ═══ 2/3/4) AVTORITET + o'qish YIQILDI -> 503 + kod + YARIM HISOBOT YO'Q ════
def test_2_avtoritet_va_oqish_yiqildi_503(db, cashenv, monkeypatch):
    from app.services.cash import repositories as _crepo
    co, br, emp, till = _tenant(db, native=True)
    _fund(db, emp, till)
    _buy_cash(db, emp, co, br, till, cost="7000")
    monkeypatch.setattr(_crepo, "category_totals", _boom)
    with pytest.raises(HTTPException) as ei:
        _cashflow(emp, db)
    assert ei.value.status_code == 503, ei.value.detail


def test_3_barqaror_kod_sarlavhada_va_prefiksda(db, cashenv, monkeypatch):
    from app.services.cash import repositories as _crepo
    co, br, emp, till = _tenant(db, native=True)
    monkeypatch.setattr(_crepo, "category_totals", _boom)
    with pytest.raises(HTTPException) as ei:
        _cashflow(emp, db)
    e = ei.value
    assert e.headers and e.headers.get("X-Error-Code") == CG.ERR_LEDGER_UNAVAILABLE
    assert str(e.detail).startswith(CG.ERR_LEDGER_UNAVAILABLE + ":")
    assert CG.code_of(e.detail) == CG.ERR_LEDGER_UNAVAILABLE      # mijoz kodni TANIYDI
    # YANGI kod IXTIRO QILINMAGAN: mavjud ro'yxatdan
    assert CG.ERR_LEDGER_UNAVAILABLE in CG.ERROR_CODES


def test_4_yarim_hisobot_qaytarilmaydi(db, cashenv, monkeypatch):
    """Javobda `kassada`/`out` kabi son BO'LMASIN — faqat xato."""
    from app.services.cash import repositories as _crepo
    co, br, emp, till = _tenant(db, native=True)
    _fund(db, emp, till)
    _buy_cash(db, emp, co, br, till, cost="7000")
    monkeypatch.setattr(_crepo, "category_totals", _boom)
    try:
        out = _cashflow(emp, db)
    except HTTPException as e:
        assert isinstance(e.detail, str) and "kassada" not in e.detail
        return
    pytest.fail("yarim hisobot 200 bilan qaytdi: " + repr(out)[:200])


# ═══ 5) AVTORITET EMAS (legacy) -> eski xulq AYNAN ═══════════════════════════
def test_5_legacy_tenant_ledger_yoq_bolsa_ham_ishlaydi(db, cashenv, monkeypatch):
    from app.services.cash import repositories as _crepo
    co, br, emp, till = _tenant(db, native=False)
    monkeypatch.setattr(_crepo, "category_totals", _boom)      # ATAYLAB buzilgan
    out = _cashflow(emp, db)                                    # ...lekin CHAQIRILMAYDI
    assert out["ledger_native"] is False
    assert "naqd_xarid" not in out["out"], "legacy javob shakli o'zgarmasin"
    assert "kassada" in out and "in" in out and "out" in out


# ═══ 6) rejim/cutover chegarasi — HAQIQIY holat modeli bo'yicha ══════════════
def test_6a_avtoritet_va_LEGACY_ONLY_rejim_503(db, cashenv):
    """Ledger-native do'konda `LEGACY_ONLY` — ledger yozilmaydi, ya'ni avtoritet manba
    ishlamayapti. `services/sales.py` bilan AYNI qoida: baland xato, jim legacy EMAS."""
    co, br, emp, till = _tenant(db, native=True)
    mode.set_mode(mode.CashMode.LEGACY_ONLY)
    with pytest.raises(HTTPException) as ei:
        _cashflow(emp, db)
    assert ei.value.status_code == 503
    assert CG.code_of(ei.value.detail) == CG.ERR_LEDGER_UNAVAILABLE


def test_6b_legacy_tenant_LEGACY_ONLY_rejimda_ishlaydi(db, cashenv):
    """Legacy do'kon uchun `LEGACY_ONLY` QONUNIY holat — hisobot ishlashi kerak."""
    co, br, emp, till = _tenant(db, native=False)
    mode.set_mode(mode.CashMode.LEGACY_ONLY)
    out = _cashflow(emp, db)
    assert out["ledger_native"] is False and "kassada" in out


def test_6c_avtoritet_holati_oqilmasa_fail_closed(db, cashenv):
    """`cash` Setting qiymati BUZUQ bo'lsa «legacy» deb TAXMIN QILMAYMIZ.

    ⚠️  Qator YO'QLIGI xato emas (legacy do'konning ODATIY holati) — 5-sinov shuni ko'rsatadi."""
    co, br, emp, till = _tenant(db, native=False)
    row = db.query(Setting).filter(Setting.company_id == co.id, Setting.key == "cash").one()
    row.value = "buzuq-qiymat"                      # dict EMAS -> `.get` AttributeError
    db.add(row); db.commit()
    with pytest.raises(HTTPException) as ei:
        _cashflow(emp, db)
    assert ei.value.status_code == 503
    assert CG.code_of(ei.value.detail) == CG.ERR_LEDGER_UNAVAILABLE


# ═══ 7) boshqa hisobot marshrutlari TEGILMAGAN ══════════════════════════════
def test_7_boshqa_hisobotlar_ozgarmaydi(db, cashenv, monkeypatch):
    from app.services.cash import repositories as _crepo
    co, br, emp, till = _tenant(db, native=True)
    monkeypatch.setattr(_crepo, "category_totals", _boom)
    # `summary` va `debtors` ledgerga tayanmaydi -> buzilgan ledger ularga TA'SIR QILMAYDI
    assert isinstance(reports_api.summary(emp=emp, db=db), dict)
    assert isinstance(reports_api.debtors(emp=emp, db=db), dict)


# ═══ AVTORITET predikati — `cash_enabled` EMAS ══════════════════════════════
def test_avtoritet_predikati_infra_darvozasi_emas(db, cashenv):
    co, br, emp, till = _tenant(db, native=True)
    co2, _, _, _ = _tenant(db, native=False)
    assert _tn.is_ledger_authoritative(db, co.id) is True
    assert _tn.is_ledger_authoritative(db, co2.id) is False
    # infra darvozasi IKKALA do'kon uchun ham bir xil (Postgres + cash sxemasi) — ya'ni u
    # avtoritetni AJRATMAYDI, shu bois predikat sifatida YARAMAYDI
    from app.services.cash import retrofit as _cr
    assert _cr.cash_enabled(db) is True
