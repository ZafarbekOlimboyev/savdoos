# -*- coding: utf-8 -*-
"""PHASE 5G.1 / B1 — HISOBOT VA XODIM STATISTIKASINING FILIAL DOIRASI.

Audit (`p5g1/audit_backend_supplier_reports.md` §2) ikki HAQIQIY teshik va bitta
imkoniyat bo'shlig'ini topdi:

  H1  `GET /employees/{id}/stats` sotuvlarni FAQAT `cashier_id` bo'yicha yig'ardi —
      `company_id` ham, `visible_branches` ham yo'q. A filialiga biriktirilgan administrator
      B filialida ishlagan kassirni ochib, B ning tushumini va 6 oylik grafigini ko'rardi.
  H3  `GET /reports/overview?branch_id=` sust tekshirilardi: buzuq UUID -> 200 (kompaniya
      bo'yicha), begona/o'chirilgan filial -> 200 (nollar), KO'RISH DOIRASIDAN TASHQARI filial
      -> 200 chaqiruvchining O'Z raqamlari bilan (mijoz ularni so'ralgan filial nomi ostida
      ko'rsatardi).
  §7  Qolgan 13 hisobot `visible_branches` ni HURMAT QILADI, lekin aniq `branch_id` pivotini
      bilmaydi — ega/ko'p-filial xodimi bitta filialga qaray olmasdi.

Shartnoma (barchasi `GET /products?branch_id=` bilan AYNI yordamchi — `_stock_scope`):
  · `branch_id` yo'q          -> ko'rinadigan filiallar (AVVALGIDEK, bayt-bayt);
  · ko'rinadigan filial       -> faqat o'sha;
  · buzuq UUID                -> 422 (FastAPI `uuid.UUID` annotatsiyasi);
  · begona/o'chirilgan filial -> 400 «Filial topilmadi» (tanada begona satr YO'Q);
  · o'z tenant, biriktirilmagan -> 403 «Ruxsat yo'q: bu filial sizga biriktirilmagan»
    (ruxsat DARVOZASI emas — `X-Error-Code` YO'Q, `test_mobile_parity` bilan izchil).
  · `/reports/debtors` — KOMPANIYA bo'yicha qoladi (`Customer` da filial yo'q).

⚠️  ADDITIVLIK: ega uchun A + B == parametrsiz. Filtr bitta so'rovga qo'yilib ikkinchisida
    unutilsa (cashflow'da SAKKIZ alohida agregat bor) — aynan shu tenglik yiqiladi.

⚠️  FAIL-OPEN PIN: filialga biriktirilmagan menejer KOMPANIYA bo'yicha ko'radi
    (`deps.visible_branches` — «moslik»). Bu B1 da ATAYLAB o'zgartirilmadi: Fayzan'da 2 xodim,
    1 `employee_branches` qatori — fail-closed jonli foydalanuvchining hisobotini bo'shatardi.
    Test uni PIN qiladi: qaror CI'da ko'rinib tursin.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.security import create_access_token

NOW = datetime.now(timezone.utc)


def _pick_store_tz() -> str:
    """Do'kon vaqt zonasini SHUNDAY tanlaydi-ki, mahalliy yarim tundan iloji boricha KO'P vaqt
    o'tgan bo'lsin.

    `period=day` hisoboti oynani `[mahalliy yarim tun, hozir]` deb oladi, fikstura esa faktlarni
    yarim tundan sal keyin yozadi. Zona qat'iy belgilangan bo'lsa, o'sha yarim tunni KESIB o'tgan
    yurish (CI 19:00 UTC dan keyin — Toshkentда ertangi kun) hamma "bugungi" raqamni NOLGA
    aylantirardi va to'plam kuniga ~yarim soat qizil bo'lardi. Qo'llab-quvvatlanadigan offsetlar
    3..7 — bu har doim kamida ~3 soat zaxira beradi.
    """
    from app.api.v1.reports import _TZ_OFFSETS
    best, best_since = None, -1
    for name, off in sorted(_TZ_OFFSETS.items()):
        local = NOW.astimezone(timezone(timedelta(hours=off)))
        since = local.hour * 3600 + local.minute * 60 + local.second
        if since > best_since:
            best, best_since = name, since
    return best
TZ = _pick_store_tz()  # pastdagi izohga qarang
PFX = "/api/v1"
D = lambda v: Decimal(str(v))  # noqa: E731


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _token(eid, role, cid) -> dict:
    tok = create_access_token(str(eid), {"role": role, "company_id": str(cid), "sv": 0})
    return {"Authorization": f"Bearer {tok}"}


def _at() -> datetime:
    """BUGUNGI do'kon kuni ichidagi ANIQ vaqt: mahalliy yarim tundan 60 s keyin, lekin hozirdan
    oldin — oy/kun/soat oynalari (`period=day|week|month`, hourly) hammasi qamrasin."""
    from app.api.v1.reports import _TZ_OFFSETS
    local = timezone(timedelta(hours=_TZ_OFFSETS[TZ]))
    midnight = NOW.astimezone(local).replace(hour=0, minute=0, second=0, microsecond=0)
    return min(midnight + timedelta(seconds=60), NOW - timedelta(seconds=1)).astimezone(timezone.utc)


AT = _at()


# ══ DUNYO: 2 tenant, A/B (+ o'chirilgan D) va C filiallari, har roldan xodim ═══════════

def _emp(db, cid, role_code, name, *, branches=()):
    from app.models.auth import Employee, EmployeeBranch, Role
    from app.models.enums import EmployeeStatus
    role = db.query(Role).filter(Role.code == role_code).one()
    e = Employee(id=uuid.uuid4(), company_id=cid, role_id=role.id, full_name=name,
                 phone=f"+9987{uuid.uuid4().int % 10**7:07d}", status=EmployeeStatus.active,
                 sec_epoch=0)
    db.add(e)
    db.flush()
    for b in branches:
        db.add(EmployeeBranch(employee_id=e.id, branch_id=b))
    return e.id


def _sale(db, cid, bid, cashier, total, cost, items, pay, *, status=None, at=AT):
    """Bitta chek: `items` = [(product_id, name, qty, unit_price, unit_cost, cost_total)],
    `pay` = [(method, amount)]. subtotal == Σ line_total (chegirmasiz -> factor 1)."""
    from app.models.enums import SaleStatus
    from app.models.sales import Sale, SaleItem, SalePayment
    s = Sale(id=uuid.uuid4(), receipt_no="R" + uuid.uuid4().hex[:6], company_id=cid, branch_id=bid,
             cashier_id=cashier, status=status or SaleStatus.completed, currency="UZS",
             subtotal=D(total), discount_total=0, tax_total=0, total=D(total), cost_total=D(cost),
             sold_at=at, is_offline=False)
    db.add(s)
    db.flush()
    for pid, nm, q, up, uc, ct in items:
        db.add(SaleItem(sale_id=s.id, product_id=pid, name_snapshot=nm, qty=D(q), unit_price=D(up),
                        unit_cost=D(uc), cost_total=D(ct), discount=0, tax_rate=0,
                        line_total=D(q) * D(up)))
    for m, a in pay:
        db.add(SalePayment(sale_id=s.id, method_code=m, amount=D(a), paid_at=at))
    return s.id


def _return(db, cid, bid, cashier, total, method, restock, pid, nm, qty, up, uc, ct, *, sale=None):
    from app.models.sales import Return, ReturnItem
    r = Return(id=uuid.uuid4(), return_no="Q" + uuid.uuid4().hex[:6], original_sale_id=sale,
               company_id=cid, branch_id=bid, cashier_id=cashier, restock=restock,
               refund_method=method, total=D(total), created_at=AT)
    db.add(r)
    db.flush()
    db.add(ReturnItem(return_id=r.id, product_id=pid, qty=D(qty), unit_price=D(up), unit_cost=D(uc),
                      cost_total=D(ct), line_total=D(total)))
    return r.id


def _shift(db, bid, cashier, opening, moves):
    """Ochiq smena + kassa harakatlari: `moves` = [(type, amount, reason)]."""
    from app.models.enums import CashMovementType
    from app.models.shifts import CashMovement, Shift
    sh = Shift(id=uuid.uuid4(), branch_id=bid, cashier_id=cashier, opened_at=AT, opening_cash=D(opening))
    db.add(sh)
    db.flush()
    for t, a, reason in moves:
        db.add(CashMovement(shift_id=sh.id, type=CashMovementType(t), amount=D(a), reason=reason,
                            employee_id=cashier, created_at=AT))
    return sh.id


def _product(db, cid, name, cat=None, *, inv=()):
    """Mahsulot + `inv` = [(branch_id, qty, min_qty)] qoldiqlari."""
    from app.models.catalog import Product, Unit
    from app.models.inventory import Inventory
    unit = db.query(Unit).filter(Unit.code == "dona").first() or db.query(Unit).first()
    p = Product(id=uuid.uuid4(), company_id=cid, name=name, article_code="B1-" + uuid.uuid4().hex[:8],
                sku=uuid.uuid4().hex[:8], unit_id=unit.id, category_id=cat, base_buy_price=50,
                base_sell_price=100, tax_rate=0, is_active=True)
    db.add(p)
    db.flush()
    for bid, q, mn in inv:
        db.add(Inventory(product_id=p.id, branch_id=bid, qty=D(q), min_qty=D(mn), updated_at=AT))
    return p.id


@pytest.fixture(scope="module")
def W(client):
    """Ikki tenant. T1: A, B (+ o'chirilgan D); T2: C. Faktlar ATAYLAB filialga BOG'LANGAN va
    ikki manbali qatorlar (beruvchiga naqd: kompaniya=SupplierPayment, filial=CashMovement)
    o'zaro MOS — shunda A + B == parametrsiz tengligi har maydonda tekshiriladi."""
    from app.models.catalog import Category
    from app.models.customers import Customer, CustomerPayment
    from app.models.enums import SaleStatus
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier, SupplierPayment
    w: dict = {}
    with _db() as db:
        # ── T1 ──
        c1 = Company(id=uuid.uuid4(), name="B1 T1 " + uuid.uuid4().hex[:5], code="b1a" + uuid.uuid4().hex[:7],
                     currency="UZS")
        db.add(c1)
        db.flush()
        A = Branch(id=uuid.uuid4(), company_id=c1.id, name="Filial A", code="A", timezone=TZ, is_active=True,
                   created_at=NOW - timedelta(days=30))
        B = Branch(id=uuid.uuid4(), company_id=c1.id, name="Filial B", code="B", timezone=TZ, is_active=True,
                   created_at=NOW - timedelta(days=29))
        Dd = Branch(id=uuid.uuid4(), company_id=c1.id, name="Filial D (o'chirilgan)", code="D", timezone=TZ,
                    is_active=True, created_at=NOW - timedelta(days=28), deleted_at=NOW - timedelta(days=1))
        db.add_all([A, B, Dd])
        db.flush()
        w.update(cid=c1.id, A=A.id, B=B.id, D=Dd.id)
        w["ega"] = _emp(db, c1.id, "ega", "B1 ega")
        w["adminA"] = _emp(db, c1.id, "administrator", "B1 admin A", branches=[A.id])
        w["menA"] = _emp(db, c1.id, "menejer", "B1 menejer A", branches=[A.id])
        w["menNone"] = _emp(db, c1.id, "menejer", "B1 menejer biriktirilmagan")
        w["ombA"] = _emp(db, c1.id, "omborchi", "B1 omborchi A", branches=[A.id])
        w["kasA"] = _emp(db, c1.id, "kassir", "B1 kassir A", branches=[A.id])
        w["cashierX"] = _emp(db, c1.id, "kassir", "B1 kassir X (A+B)", branches=[A.id, B.id])
        w["cashierB"] = _emp(db, c1.id, "kassir", "B1 kassir B", branches=[B.id])
        cat = Category(id=uuid.uuid4(), company_id=c1.id, name="Ichimliklar B1")
        db.add(cat)
        db.flush()
        p1 = _product(db, c1.id, "B1 Cola", cat.id, inv=[(A.id, 10, 0), (B.id, 4, 0)])
        p2 = _product(db, c1.id, "B1 Non", None, inv=[(A.id, 3, 0)])
        p3 = _product(db, c1.id, "B1 Kam-A", cat.id, inv=[(A.id, 1, 5)])       # A da kam qoldiq, sotilmagan
        p4 = _product(db, c1.id, "B1 Kam-B", None, inv=[(B.id, 2, 3)])         # B da kam qoldiq (sotiladi)
        # B da kam qoldiq VA hech qachon sotilmagan (o'lik) — A/B ASIMMETRIK bo'lsin: alerts'da
        # B=2 kam qoldiq, A=1; dead-stock'da B ham bo'sh bo'lmasin (aks holda «A == parametrsiz»).
        p5 = _product(db, c1.id, "B1 Olik-B", None, inv=[(B.id, 6, 10)])
        w.update(p1=p1, p2=p2, p3=p3, p4=p4, p5=p5)
        # Sotuvlar — A: 1000 (naqd), 2000 (karta), 3100 (naqd, zarar qatori bilan), VOID 9999.
        w["sA1"] = _sale(db, c1.id, A.id, w["cashierX"], 1000, 600,
                         [(p1, "B1 Cola", 2, 500, 300, 600)], [("cash", 1000)])
        _sale(db, c1.id, A.id, w["cashierX"], 2000, 1200, [(p2, "B1 Non", 1, 2000, 1200, 1200)],
              [("card", 2000)])
        _sale(db, c1.id, A.id, w["kasA"], 3100, 1650,
              [(p1, "B1 Cola", 3, 1000, 500, 1500), (p2, "B1 Non", 1, 100, 150, 150)], [("cash", 3100)])
        _sale(db, c1.id, A.id, w["kasA"], 9999, 1, [(p1, "B1 Cola", 1, 9999, 1, 1)], [("cash", 9999)],
              status=SaleStatus.voided)
        # B: 5000 (naqd, kassir X), 7050 (nasiya, kassir B, zarar qatori bilan).
        _sale(db, c1.id, B.id, w["cashierX"], 5000, 2500, [(p1, "B1 Cola", 5, 1000, 500, 2500)],
              [("cash", 5000)])
        _sale(db, c1.id, B.id, w["cashierB"], 7050, 3080,
              [(p2, "B1 Non", 1, 7000, 3000, 3000), (p4, "B1 Kam-B", 1, 50, 80, 80)], [("credit", 7050)])
        # Qaytarishlar — A: naqd 100 (restock), B: karta 200 (restock EMAS).
        _return(db, c1.id, A.id, w["cashierX"], 100, "cash", True, p1, "B1 Cola", 0.2, 500, 300, 60,
                sale=w["sA1"])
        _return(db, c1.id, B.id, w["cashierB"], 200, "card", False, p2, "B1 Non", 0.1, 2000, 1000, 100)
        # Smenalar va kassa harakatlari.
        _shift(db, A.id, w["cashierX"], 10000, [
            ("expense", 300, "Xarajat"), ("payin", 50, "Qo'shimcha"), ("collection", 400, "Inkassa"),
            ("payout", 60, "Ta'minotchi · S1"), ("payout", 20, "Boshqa"),
            ("payin", 15, "Qarz to'lovi: mijoz"),        # qarz_qaytdi'da sanaladi, payin'dan chiqadi
        ])
        _shift(db, B.id, w["cashierB"], 20000, [("expense", 700, "Xarajat"), ("payout", 80, "Ta'minotchi · S1")])
        sup = Supplier(id=uuid.uuid4(), company_id=c1.id, name="B1 S1")
        db.add(sup)
        db.flush()
        # Kompaniya ko'rinishi SupplierPayment'dan, filial ko'rinishi «Ta'minotchi» payout'dan —
        # 60 + 80 == 140: ikki manba MOS, additivlik tekshiriladi.
        db.add_all([SupplierPayment(supplier_id=sup.id, amount=D(60), method="cash", paid_at=AT, created_at=AT),
                    SupplierPayment(supplier_id=sup.id, amount=D(80), method="cash", paid_at=AT, created_at=AT)])
        cust = Customer(id=uuid.uuid4(), company_id=c1.id, code="M-B1-1", full_name="B1 Qarzdor",
                        credit_balance=D(500), is_active=True)
        db.add(cust)
        db.flush()
        db.add_all([
            CustomerPayment(customer_id=cust.id, amount=D(150), method="cash", paid_at=AT, branch_id=A.id,
                            created_at=AT),
            CustomerPayment(customer_id=cust.id, amount=D(30), method="card", paid_at=AT, branch_id=A.id,
                            created_at=AT),
            CustomerPayment(customer_id=cust.id, amount=D(250), method="cash", paid_at=AT, branch_id=B.id,
                            created_at=AT),
        ])
        # ── T2 ──
        c2 = Company(id=uuid.uuid4(), name="B1 T2 " + uuid.uuid4().hex[:5], code="b1b" + uuid.uuid4().hex[:7],
                     currency="UZS")
        db.add(c2)
        db.flush()
        C = Branch(id=uuid.uuid4(), company_id=c2.id, name="Filial C", code="C", timezone=TZ, is_active=True,
                   created_at=NOW - timedelta(days=27))
        db.add(C)
        db.flush()
        w.update(cid2=c2.id, C=C.id)
        w["ega2"] = _emp(db, c2.id, "ega", "B1 ega T2")
        w["cashier2"] = _emp(db, c2.id, "kassir", "B1 kassir T2", branches=[C.id])
        p9 = _product(db, c2.id, "T2 Mahsulot", None, inv=[(C.id, 7, 9)])
        _sale(db, c2.id, C.id, w["cashier2"], 11000, 4000, [(p9, "T2 Mahsulot", 1, 11000, 4000, 4000)],
              [("cash", 11000)])
        cust2 = Customer(id=uuid.uuid4(), company_id=c2.id, code="M-B1-2", full_name="T2 Qarzdor",
                         credit_balance=D(999), is_active=True)
        db.add(cust2)
        db.commit()
    w["H"] = {k: _token(w[k], r, w["cid"]) for k, r in (
        ("ega", "ega"), ("adminA", "administrator"), ("menA", "menejer"), ("menNone", "menejer"),
        ("ombA", "omborchi"), ("kasA", "kassir"))}
    w["H"]["ega2"] = _token(w["ega2"], "ega", w["cid2"])
    return w


# ══ HISOBOTLAR RO'YXATI ═════════════════════════════════════════════════════════
#
# (yo'l, standart parametrlar). Hammasi `hisobot.view`; hammasi filialga bog'liq faktlarni
# yig'adi. `/reports/debtors` ATAYLAB YO'Q — u kompaniya bo'yicha (alohida test).
REPORTS = [
    ("/reports/summary", {}),
    ("/reports/pnl", {"period": "month"}),
    ("/reports/top-products", {"period": "month", "limit": 100}),
    ("/reports/sales-dynamics", {}),
    ("/reports/dashboard", {}),
    ("/reports/overview", {"period": "week"}),
    ("/reports/alerts", {}),
    ("/reports/categories", {"period": "month"}),
    ("/reports/detail", {"period": "month"}),
    ("/reports/cashflow", {"period": "day"}),
    ("/reports/hourly", {}),
    ("/reports/alerts/detail", {"type": "low"}),
    ("/reports/inventory-value", {}),
    ("/reports/dead-stock", {"days": 30}),
]
RIDS = [p.replace("/reports/", "") for p, _ in REPORTS]


def _get(client, path, headers, branch=None, **extra):
    params = dict(next(q for p, q in REPORTS if p == path)) if any(p == path for p, _ in REPORTS) else {}
    params.update(extra)
    if branch is not None:
        params["branch_id"] = str(branch)
    return client.get(PFX + path, headers=headers, params=params)


# ── Additiv maydonlar: hisobot -> {yo'l: son}. Foiz/marja/delta/o'rtacha/yorliq KIRMAYDI. ──
def _by(rows, key, *fields):
    out = {}
    for r in rows:
        for f in fields:
            out[f"{r[key]}.{f}"] = out.get(f"{r[key]}.{f}", 0.0) + float(r[f] or 0)
    return out


def _flat(path, j) -> dict[str, float]:
    if path == "/reports/summary":
        d = {k: float(j[k]) for k in ("today_sales", "today_profit", "tx_count", "cogs_variance")}
        d.update(_by(j["payment_breakdown"], "method", "amount"))
        return d
    if path == "/reports/pnl":
        return {k: float(j[k]) for k in (
            "gross", "discount", "returns", "net", "cogs", "gross_profit", "net_profit", "vat",
            "revenue_known_cost", "revenue_mixed_cost", "revenue_estimated_cost", "revenue_cost_unknown",
            "cogs_known", "cogs_estimated", "cogs_unknown", "cogs_of_known_revenue", "returns_unlinked",
            "cogs_returns_unlinked", "returns_prior_period", "cogs_returns_prior_period", "cogs_variance",
            "gross_profit_known")}
    if path == "/reports/top-products":
        return _by(j, "name", "qty", "profit")
    if path == "/reports/sales-dynamics":
        return _by(j, "day", "sales")
    if path == "/reports/dashboard":
        d = {k: float(j[k]) for k in ("today_sales", "today_profit", "cogs_variance")}
        d["debt.paid_today"] = float(j["debt"]["paid_today"])
        d.update(_by(j["weekly"], "day", "sales"))
        d.update(_by(j["payments"], "method", "amount"))
        return d
    if path == "/reports/overview":
        d = {"kpi." + k: float(j["kpi"][k]) for k in ("sales", "profit", "tx", "cogs_variance")}
        d["credit_total"] = float(j["credit_total"])
        for s in j["series"]:
            for k in ("subtotal", "discount", "returns", "sales", "cost", "profit", "tx"):
                d[f"series.{s['label']}.{k}"] = d.get(f"series.{s['label']}.{k}", 0.0) + float(s[k])
            for m, v in s["pays"].items():
                d[f"series.{s['label']}.pays.{m}"] = d.get(f"series.{s['label']}.pays.{m}", 0.0) + float(v)
        d.update(_by(j["payments"], "method", "amount"))
        d.update({"top." + k: v for k, v in _by(j["top_products"], "name", "revenue", "qty").items()})
        d.update({"cashier." + k: v for k, v in _by(j["cashiers"], "name", "sales", "tx").items()})
        return d
    if path == "/reports/alerts":
        return {k: float(j[k]) for k in ("low_stock", "loss_making")}
    if path == "/reports/categories":
        return _by(j, "name", "sales", "profit")
    if path == "/reports/detail":
        d = {"returns." + k: float(j["returns"][k]) for k in ("count", "sum", "voided")}
        d["cogs_variance_unranked"] = float(j["cogs_variance_unranked"])
        d.update({"abc." + k: v for k, v in _by(j["abc"], "name", "units", "revenue", "profit").items()})
        return d
    if path == "/reports/cashflow":
        d = {"in." + k: float(v) for k, v in j["in"].items()}
        d.update({"out." + k: float(v) for k, v in j["out"].items()})
        d.update({"noncash." + k: float(v) for k, v in j["noncash"].items()})
        d["opening"], d["kassada"] = float(j["opening"]), float(j["kassada"])
        return d
    if path == "/reports/hourly":
        return _by(j, "hour", "sales")
    if path == "/reports/alerts/detail":
        return {r["name"]: 1.0 for r in j}          # har filialda ALOHIDA kam-qoldiq nomi
    if path == "/reports/inventory-value":
        # `item_count` ADDITIV EMAS: bir mahsulot ikki filialda -> parametrsiz 1, A + B esa 2.
        d = {k: float(j[k]) for k in ("total_cost", "total_retail", "potential_profit")}
        d.update({"cat." + k: v for k, v in _by(j["by_category"], "name", "value").items()})
        d.update({"item." + k: v for k, v in _by(j["top_items"], "name", "value").items()})
        return d
    if path == "/reports/dead-stock":
        # `count` ADDITIV EMAS (yuqoridagi sabab); qiymatlar additiv.
        d = {"frozen_value": float(j["frozen_value"])}
        d.update({"item." + k: v for k, v in _by(j["items"], "name", "value").items()})
        return d
    raise AssertionError(path)


def _plus(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0.0) + v
    return out


def _close(x: dict, y: dict, where: str):
    keys = set(x) | set(y)
    bad = {k: (x.get(k, 0.0), y.get(k, 0.0)) for k in keys if abs(x.get(k, 0.0) - y.get(k, 0.0)) > 1e-6}
    assert not bad, f"{where}: {bad}"


# ══ 1. EGA: parametrsiz == A + B (ADDITIVLIK), A va B alohida to'g'ri ══════════════

@pytest.mark.parametrize("path", [p for p, _ in REPORTS], ids=RIDS)
def test_EGA_A_plus_B_parametrsizga_TENG(client, W, path):
    """Filtr bitta agregatga qo'yilib boshqasida unutilsa — aynan shu tenglik yiqiladi."""
    H = W["H"]["ega"]
    full = _get(client, path, H)
    a = _get(client, path, H, W["A"])
    b = _get(client, path, H, W["B"])
    assert full.status_code == a.status_code == b.status_code == 200, (full.text, a.text, b.text)
    fa, fb, ff = _flat(path, a.json()), _flat(path, b.json()), _flat(path, full.json())
    _close(_plus(fa, fb), ff, f"{path}: A + B != parametrsiz")
    # Filtr HAQIQATAN ishlaydi: A != B (ikkala filialda ham fakt bor), va A != parametrsiz.
    assert fa != fb, f"{path}: A va B bir xil — filtr e'tiborsiz qoldirilgan"
    assert fa != ff, f"{path}: A == parametrsiz — filtr e'tiborsiz qoldirilgan"


def test_EGA_summary_va_cashflow_ANIQ_raqamlar(client, W):
    """Fixture arifmetikasidan MUSTAQIL kutilgan qiymatlar (hisobot kodiga tayanmaydi)."""
    H = W["H"]["ega"]
    s_all, s_a, s_b = (_get(client, "/reports/summary", H, b).json() for b in (None, W["A"], W["B"]))
    assert (s_all["today_sales"], s_all["tx_count"]) == (17850.0, 5)   # 18150 − 300 qaytarish; void yo'q
    assert (s_a["today_sales"], s_a["tx_count"]) == (6000.0, 3)        # 6100 − 100
    assert (s_b["today_sales"], s_b["tx_count"]) == (11850.0, 2)       # 12050 − 200
    cf_a = _get(client, "/reports/cashflow", H, W["A"]).json()
    assert cf_a["in"] == {"naqd_savdo": 4100.0, "qarz_qaytdi": 150.0, "qoshimcha": 50.0, "jami": 4300.0}
    assert cf_a["out"] == {"xarajat": 300.0, "inkassatsiya": 420.0, "qaytarish": 100.0,
                           "beruvchiga": 60.0, "jami": 880.0}
    assert (cf_a["opening"], cf_a["kassada"]) == (10000.0, 13420.0)
    assert cf_a["noncash"] == {"karta": 2000.0, "qr": 0.0, "nasiya": 0.0}
    cf_b = _get(client, "/reports/cashflow", H, W["B"]).json()
    assert cf_b["in"]["naqd_savdo"] == 5000.0 and cf_b["in"]["qarz_qaytdi"] == 250.0
    assert cf_b["out"]["beruvchiga"] == 80.0 and cf_b["out"]["xarajat"] == 700.0
    assert cf_b["noncash"] == {"karta": -200.0, "qr": 0.0, "nasiya": 7050.0}
    assert (cf_b["opening"], cf_b["kassada"]) == (20000.0, 24470.0)
    cf = _get(client, "/reports/cashflow", H).json()
    assert cf["out"]["beruvchiga"] == 140.0 and cf["kassada"] == 37890.0


@pytest.mark.parametrize("branch", ["A", "B", None], ids=["A", "B", "hammasi"])
def test_HISOBOTLAR_bir_filial_uchun_bir_xil_sof_tushum(client, W, branch):
    """summary / dashboard / overview(day) / pnl(day) / Σ hourly — AYNI `branch_id` da bir son."""
    H = W["H"]["ega"]
    b = W[branch] if branch else None
    s = _get(client, "/reports/summary", H, b).json()["today_sales"]
    d = _get(client, "/reports/dashboard", H, b).json()["today_sales"]
    o = _get(client, "/reports/overview", H, b, period="day").json()["kpi"]["sales"]
    p = _get(client, "/reports/pnl", H, b, period="day").json()["net"]
    h = sum(x["sales"] for x in _get(client, "/reports/hourly", H, b).json())
    assert s == d == o == p == pytest.approx(h), (s, d, o, p, h)


# ══ 2. TEKSHIRUV MATRITSASI: 422 / 400 / 403 — har hisobotda AYNI ═══════════════

@pytest.mark.parametrize("path", [p for p, _ in REPORTS], ids=RIDS)
def test_BUZUQ_uuid_422(client, W, path):
    r = _get(client, path, W["H"]["ega"], "not-a-uuid")
    assert r.status_code == 422, (path, r.status_code, r.text[:200])


@pytest.mark.parametrize("who", ["ega", "adminA", "menA", "menNone"])
@pytest.mark.parametrize("path", [p for p, _ in REPORTS], ids=RIDS)
def test_BEGONA_tenant_filiali_400_va_tanada_begona_satr_YOQ(client, W, path, who):
    """13-band: T1 chaqiruvchi T2 filialini so'raydi -> 400 va tana FAQAT xato (T2 ning 11000/999 yo'q)."""
    r = _get(client, path, W["H"][who], W["C"])
    assert r.status_code == 400, (path, who, r.status_code, r.text[:200])
    assert r.json() == {"detail": "Filial topilmadi"}, r.text
    assert "11000" not in r.text and "T2 Mahsulot" not in r.text


@pytest.mark.parametrize("path", [p for p, _ in REPORTS], ids=RIDS)
def test_OCHIRILGAN_filial_400(client, W, path):
    r = _get(client, path, W["H"]["ega"], W["D"])
    assert r.status_code == 400 and r.json() == {"detail": "Filial topilmadi"}, (path, r.text)


@pytest.mark.parametrize("who", ["adminA", "menA"])
@pytest.mark.parametrize("path", [p for p, _ in REPORTS], ids=RIDS)
def test_BIRIKTIRILMAGAN_filial_403_kodsiz(client, W, path, who):
    """9/10-band: A ga biriktirilgan administrator/menejer B ni so'raydi -> 403.
    Ruxsat DARVOZASI emas — `X-Error-Code` YO'Q (`test_mobile_parity` shartnomasi)."""
    r = _get(client, path, W["H"][who], W["B"])
    assert r.status_code == 403, (path, who, r.status_code, r.text[:200])
    assert r.json() == {"detail": "Ruxsat yo'q: bu filial sizga biriktirilmagan"}, r.text
    assert r.headers.get("X-Error-Code") is None
    # Tana B ning raqamlarini ham, A ning raqamlarini ham OLIB KELMAYDI.
    assert "11850" not in r.text and "6000" not in r.text


@pytest.mark.parametrize("who", ["adminA", "menA"])
@pytest.mark.parametrize("path", [p for p, _ in REPORTS], ids=RIDS)
def test_BIRIKTIRILGAN_xodim_parametrsiz_va_A_bir_xil_va_ega_A_ga_TENG(client, W, path, who):
    """7/8-band: A-xodim uchun parametrsiz == `branch_id=A` == ega'ning `branch_id=A`."""
    absent = _get(client, path, W["H"][who])
    a = _get(client, path, W["H"][who], W["A"])
    ega_a = _get(client, path, W["H"]["ega"], W["A"])
    assert absent.status_code == a.status_code == ega_a.status_code == 200, (absent.text, a.text, ega_a.text)
    fa = _flat(path, absent.json())
    _close(fa, _flat(path, a.json()), f"{path} {who}: parametrsiz != branch_id=A")
    _close(fa, _flat(path, ega_a.json()), f"{path} {who}: A-xodim != ega(A)")


@pytest.mark.parametrize("path", [p for p, _ in REPORTS], ids=RIDS)
def test_FAIL_OPEN_PIN_biriktirilmagan_menejer_KOMPANIYA_boyicha_koradi(client, W, path):
    """⚠️  H2 — `visible_branches` biriktirilmagan xodim uchun None (cheklovsiz). B1 da ATAYLAB
    O'ZGARTIRILMADI (Fayzan: 2 xodim, 1 `employee_branches` qatori — fail-closed jonli
    foydalanuvchini bo'shatardi). Bu test qarorni CI'da KO'RINADIGAN qiladi: kimdir uni
    fail-closed qilsa, aynan shu test qizaradi va u ONGLI ravishda yangilanadi."""
    mine = _get(client, path, W["H"]["menNone"])
    ega = _get(client, path, W["H"]["ega"])
    assert mine.status_code == 200
    _close(_flat(path, mine.json()), _flat(path, ega.json()), f"{path}: biriktirilmagan menejer != ega")
    # Aniq pivot ham ochiq: A va B ikkalasi ham 200 (cheklov yo'q).
    assert _get(client, path, W["H"]["menNone"], W["A"]).status_code == 200
    assert _get(client, path, W["H"]["menNone"], W["B"]).status_code == 200


@pytest.mark.parametrize("who", ["ombA", "kasA"])
@pytest.mark.parametrize("path", [p for p, _ in REPORTS], ids=RIDS)
def test_RUXSATSIZ_rol_403_PERMISSION_DENIED_har_qanday_filialda(client, W, path, who):
    """12-band: omborchi/kassir `hisobot.view` siz — darvoza, doira emas (kod BOR)."""
    for b in (None, W["A"], W["B"], W["C"]):
        r = _get(client, path, W["H"][who], b)
        assert r.status_code == 403 and r.headers.get("X-Error-Code") == "PERMISSION_DENIED", (path, who, r.text)


# ══ 3. /reports/overview — H3 regressiyasi ANIQ (audit jadvalining uch qatori) ══════

def test_OVERVIEW_H3_buzuq_begona_va_doiradan_tashqari_filial(client, W):
    ega, adm = W["H"]["ega"], W["H"]["adminA"]
    # (1) buzuq UUID: ilgari 200 kompaniya bo'yicha -> endi 422.
    assert _get(client, "/reports/overview", ega, "xyz").status_code == 422
    # (2) begona filial: ilgari 200 nollar -> endi 400.
    assert _get(client, "/reports/overview", ega, W["C"]).status_code == 400
    # (3) doiradan tashqari: ilgari 200 A ning raqamlari B nomi ostida -> endi 403.
    r = _get(client, "/reports/overview", adm, W["B"])
    assert r.status_code == 403, r.text
    # Ega uchun haqiqiy pivot: A/B alohida, jami mos.
    oa, ob, oo = (_get(client, "/reports/overview", ega, b).json() for b in (W["A"], W["B"], None))
    assert (oa["kpi"]["sales"], ob["kpi"]["sales"], oo["kpi"]["sales"]) == (6000.0, 11850.0, 17850.0)
    assert (oa["kpi"]["tx"], ob["kpi"]["tx"], oo["kpi"]["tx"]) == (3, 2, 5)
    # Filiallar bo'limi AVVALGIDEK — chaqiruvchining KO'RISH DOIRASI (pivotdan qat'i nazar):
    # ega ikkalasini ko'radi, A-admin faqat A ni.
    assert sorted(x["name"] for x in oa["branches"]) == ["Filial A", "Filial B"] and oa["branch_count"] == 2
    ra = _get(client, "/reports/overview", adm, W["A"]).json()
    assert [x["name"] for x in ra["branches"]] == ["Filial A"] and ra["branch_count"] == 1
    assert ra["kpi"]["sales"] == 6000.0


# ══ 4. /reports/debtors — KOMPANIYA bo'yicha (Customer'da filial yo'q) ══════════════

def test_DEBTORS_kompaniya_boyicha_va_tenant_izolyatsiyasi(client, W):
    """`Customer.credit_balance` — mijoz fakti, filial fakti emas. `branch_id` QABUL QILINMAYDI
    (e'tiborsiz — hech qanday ta'sir yo'q). Filialga biriktirilgan xodim ham butun kompaniya
    qarzini ko'radi (dashboard.debt.total bilan izchil). T2 ning 999 si T1 da yo'q."""
    for who in ("ega", "adminA", "menA", "menNone"):
        r = client.get(PFX + "/reports/debtors", headers=W["H"][who])
        assert r.status_code == 200, (who, r.text)
        assert (r.json()["total"], r.json()["count"]) == (500.0, 1), (who, r.json())
        assert [x["name"] for x in r.json()["rows"]] == ["B1 Qarzdor"]
    r2 = client.get(PFX + "/reports/debtors", headers=W["H"]["ega2"])
    assert (r2.json()["total"], r2.json()["count"]) == (999.0, 1)
    # Filial doirasi bo'lmagani uchun `branch_id` ham hech narsani o'zgartirmaydi (parametr yo'q).
    for b in (W["A"], W["C"], "xyz"):
        r = client.get(PFX + "/reports/debtors", headers=W["H"]["ega"], params={"branch_id": str(b)})
        assert r.status_code == 200 and r.json()["total"] == 500.0
    # dashboard.debt — kompaniya darajasi, hatto `branch_id=A` da ham (mavjud xatti-harakat).
    dd = _get(client, "/reports/dashboard", W["H"]["ega"], W["A"]).json()["debt"]
    assert (dd["total"], dd["debtors"], dd["paid_today"]) == (500.0, 1, 180.0)   # paid_today FILIAL bo'yicha


# ══ 5. /employees/{id}/stats — H1 (haqiqiy filiallararo pul teshigi) ═══════════════

def _stats(client, W, who, eid, branch=None):
    params = {"branch_id": str(branch)} if branch is not None else None
    return client.get(f"{PFX}/employees/{eid}/stats", headers=W["H"][who], params=params)


def _eski_stats(caller_eid, target_eid) -> dict:
    """33ea7b1 dagi `employee_stats` — AYNAN NUSXA (company/filial filtrsiz): teshikni QAYTA
    ISHLAB CHIQARADI, yangi kod bilan taqqoslash uchun (ega uchun teng, A-admin uchun FARQ)."""
    from sqlalchemy import func

    from app.api.v1.reports import _store_tz
    from app.models.auth import Employee
    from app.models.enums import SaleStatus
    from app.models.sales import Sale
    with _db() as db:
        emp = db.get(Employee, caller_eid)
        e = db.get(Employee, target_eid)
        assert e and e.company_id == emp.company_id
        _valid = Sale.status != SaleStatus.voided
        LOCAL = _store_tz(db, e.company_id)
        now_l = datetime.now(timezone.utc).astimezone(LOCAL)
        month_start = now_l.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        month_sales = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
            Sale.cashier_id == e.id, Sale.sold_at >= month_start, _valid).scalar())
        tx = db.query(Sale).filter(Sale.cashier_id == e.id, Sale.sold_at >= month_start, _valid).count()
        y, m = now_l.year, now_l.month
        buckets = []
        for _i in range(6):
            buckets.append((y, m))
            m -= 1
            if m == 0:
                m, y = 12, y - 1
        buckets.reverse()
        six_start = datetime(buckets[0][0], buckets[0][1], 1, tzinfo=LOCAL).astimezone(timezone.utc)
        agg = {}
        for sold_at, total in db.query(Sale.sold_at, Sale.total).filter(
                Sale.cashier_id == e.id, Sale.sold_at >= six_start, _valid).all():
            if sold_at is None:
                continue
            _sl = (sold_at if sold_at.tzinfo else sold_at.replace(tzinfo=timezone.utc)).astimezone(LOCAL)
            k = (_sl.year, _sl.month)
            agg[k] = agg.get(k, 0.0) + float(total or 0)
        MON = ["Yan", "Fev", "Mar", "Apr", "May", "Iyn", "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]
        chart = [{"label": MON[mo - 1], "sales": round(agg.get((yr, mo), 0.0), 2)} for yr, mo in buckets]
        return {"month_sales": month_sales, "tx": tx, "chart": chart}


def test_STATS_H1_A_admin_B_filial_tushumini_KORMAYDI(client, W):
    """Kassir X: A da 1000 + 2000 (2 chek), B da 5000 (1 chek). A-admin FAQAT A ni ko'radi."""
    r = _stats(client, W, "adminA", W["cashierX"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["month_sales"], j["tx"]) == (3000.0, 2), j
    assert sum(c["sales"] for c in j["chart"]) == 3000.0 and len(j["chart"]) == 6
    # Eski algoritm teshikni ko'rsatadi (8000 — B ham ichida); yangisi yo'q.
    old = _eski_stats(W["adminA"], W["cashierX"])
    assert (old["month_sales"], old["tx"]) == (8000.0, 3), "fixture teshikni qayta ishlab chiqarmadi"
    assert j != old


def test_STATS_ega_hamma_filial_va_ESKI_algoritm_bilan_BAYT_BAYT(client, W):
    """Ega uchun (cheklovsiz) javob eski algoritm bilan AYNAN teng — `company_id` filtri
    qo'shilishi hech narsani o'zgartirmaydi (kassir bitta kompaniyada)."""
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse
    r = _stats(client, W, "ega", W["cashierX"])
    assert r.status_code == 200 and (r.json()["month_sales"], r.json()["tx"]) == (8000.0, 3)
    assert r.content == JSONResponse(content=jsonable_encoder(_eski_stats(W["ega"], W["cashierX"]))).body


def test_STATS_aniq_branch_id_ayni_yordamchi(client, W):
    """`branch_id` — hisobotlar bilan AYNI tekshiruv: ega A -> 3000; ega B -> 5000; A-admin B -> 403;
    begona -> 400; buzuq -> 422; A-admin A -> 3000."""
    assert _stats(client, W, "ega", W["cashierX"], W["A"]).json()["month_sales"] == 3000.0
    assert _stats(client, W, "ega", W["cashierX"], W["B"]).json()["month_sales"] == 5000.0
    assert _stats(client, W, "adminA", W["cashierX"], W["A"]).json()["month_sales"] == 3000.0
    r = _stats(client, W, "adminA", W["cashierX"], W["B"])
    assert r.status_code == 403 and r.headers.get("X-Error-Code") is None, r.text
    assert _stats(client, W, "ega", W["cashierX"], W["C"]).status_code == 400
    assert _stats(client, W, "ega", W["cashierX"], W["D"]).status_code == 400
    assert _stats(client, W, "ega", W["cashierX"], "xyz").status_code == 422
    # B-kassir (A-admin ko'ra oladigan xodim, lekin sotuvlari B da): 200 va NOLLAR — 404 emas.
    r = _stats(client, W, "adminA", W["cashierB"])
    assert r.status_code == 200 and (r.json()["month_sales"], r.json()["tx"]) == (0.0, 0), r.text


def test_STATS_begona_tenant_va_yoq_xodim_FARQLANMAYDI(client, W):
    """T2 egasi T1 kassirini ochadi -> 404; mavjud bo'lmagan id -> 404; tanalar AYNAN bir xil
    (xodimning boshqa tenantda bor-yo'qligi oshkor bo'lmaydi)."""
    foreign = _stats(client, W, "ega2", W["cashierX"])
    missing = _stats(client, W, "ega2", uuid.uuid4())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Xodim topilmadi"}
    assert "8000" not in foreign.text and "5000" not in foreign.text
    # `branch_id` bilan ham oracle yo'q: begona xodim + begona filial -> 404 (xodim birinchi).
    assert _stats(client, W, "ega2", W["cashierX"], W["A"]).json() == {"detail": "Xodim topilmadi"}


def test_STATS_ruxsat_darvozasi(client, W):
    """`xodimlar.view` — menejer/omborchi/kassir yo'q -> 403 PERMISSION_DENIED; administrator o'tadi."""
    for who in ("menA", "menNone", "ombA", "kasA"):
        r = _stats(client, W, who, W["cashierX"])
        assert r.status_code == 403 and r.headers.get("X-Error-Code") == "PERMISSION_DENIED", (who, r.text)


# ══ 6. PARAMETRSIZ JAVOB BAYT-BAYT AVVALGIDEK (eski algoritm oracle) ═══════════════

def _old_scope(db, emp, branch_id):
    """33ea7b1 da HAR hisobot `_bset = visible_branches(emp, db)` deb yozgan — `branch_id`
    umuman o'qilmagan. Bu funksiya o'sha derivatsiyaning AYNAN nusxasi."""
    from app.core.deps import visible_branches
    return visible_branches(emp, db)


@pytest.mark.parametrize("who", ["ega", "adminA", "menNone"])
def test_PARAMETRSIZ_javob_ESKI_derivatsiya_bilan_BAYT_BAYT(client, W, monkeypatch, who):
    """Yagona o'zgargan narsa — `_bset` qayerdan olinishi. Eski derivatsiyani `_scope` o'rniga
    qo'yib HAMMA hisobotni bayt-bayt olamiz, keyin yangi kod bilan — tafovut bo'lmasin.
    (`_scope` bo'lmasa — bu tree hali eski: test qizaradi.)"""
    from app.api.v1 import reports as R
    assert hasattr(R, "_scope"), "reports._scope yo'q — filial doirasi yordamchisi kiritilmagan"
    H = W["H"][who]
    monkeypatch.setattr(R, "_scope", _old_scope)
    old = {p: _get(client, p, H).content for p, _ in REPORTS}
    old["/reports/debtors"] = client.get(PFX + "/reports/debtors", headers=H).content
    monkeypatch.undo()
    for p, _ in REPORTS:
        assert _get(client, p, H).content == old[p], f"{p} ({who}): parametrsiz javob o'zgardi"
    assert client.get(PFX + "/reports/debtors", headers=H).content == old["/reports/debtors"]


def test_SCOPE_yordamchisi_products_bilan_AYNI_obyekt(client, W):
    """«Qayta yozilmagan, qayta ishlatilgan»: `reports._scope` va `employees` yo'li AYNAN
    `products._stock_scope` ni chaqiradi (parametrsiz -> `visible_branches` bilan bir xil)."""
    import inspect

    from app.api.v1 import products as P
    from app.api.v1 import reports as R
    from app.core.deps import visible_branches
    from app.models.auth import Employee
    src = inspect.getsource(R._scope)
    assert "_stock_scope" in src and "visible_branches(" not in src
    with _db() as db:
        for who in ("ega", "adminA", "menNone"):
            emp = db.get(Employee, W[who])
            assert R._scope(db, emp, None) == P._stock_scope(db, emp, None) == visible_branches(emp, db)


# ═══ BITTA FILIALLI DO'KON: PIVOT == PARAMETRSIZ (filialsiz qatorlar ham) ═══════════════
#
# Adversarial review topdi (review 5G.1, report-scope): telefon Naqd oqim kartasi HAR DOIM
# `branch_id` yuboradi, stoldagi Manager esa YUBORMAYDI. Filialsiz yoziladigan ikki fakt bor:
#   · `customer_payments.branch_id` birinchi relizda umuman to'ldirilmagan (NULL);
#   · smenasiz qilingan naqd ta'minotchi to'lovi filial smenasiga CashMovement yozmaydi.
# Ilgari bunday qator HECH BIR filial javobiga tushmasdi — ya'ni bitta filialli do'kon
# (bugungi har bir mijoz) telefonda kamroq pul ko'rardi. Endi doira BARCHA filialni qamrasa
# javob cheklovsiz javob bilan bir xil (`reports._covers_every_branch`).
@pytest.fixture(scope="module")
def S1(client):
    """Bitta filialli tenant: filialsiz mijoz to'lovi + smenasiz ta'minotchi to'lovi."""
    from app.models.customers import Customer, CustomerPayment
    from app.models.org import Branch, Company
    from app.models.purchasing import Supplier, SupplierPayment
    w: dict = {}
    with _db() as db:
        c = Company(id=uuid.uuid4(), name="B1 S1 " + uuid.uuid4().hex[:5],
                    code="b1s" + uuid.uuid4().hex[:7], currency="UZS")
        db.add(c)
        db.flush()
        br = Branch(id=uuid.uuid4(), company_id=c.id, name="Yagona filial", code="S", timezone=TZ,
                    is_active=True, created_at=NOW - timedelta(days=10))
        db.add(br)
        db.flush()
        w.update(cid=c.id, br=br.id)
        w["ega"] = _emp(db, c.id, "ega", "S1 ega")
        kas = _emp(db, c.id, "kassir", "S1 kassir", branches=[br.id])
        _sale(db, c.id, br.id, kas, 1000, 400,
              [(_product(db, c.id, "S1 Cola", None, inv=[(br.id, 9, 0)]), "S1 Cola", 1, 1000, 400, 400)],
              [("cash", 1000)])
        cust = Customer(id=uuid.uuid4(), company_id=c.id, code="M-S1-1", full_name="S1 Qarzdor",
                        credit_balance=D(0), is_active=True)
        db.add(cust)
        db.flush()
        # ⚠️  ATAYLAB `branch_id` YO'Q — birinchi relizdagi qatorning aynan o'zi.
        db.add(CustomerPayment(customer_id=cust.id, amount=D(900), method="cash", paid_at=AT,
                               created_at=AT))
        sup = Supplier(id=uuid.uuid4(), company_id=c.id, name="S1 ta'minotchi")
        db.add(sup)
        db.flush()
        # ⚠️  Smenasiz to'lov: `CashMovement` YO'Q (pre-T0 do'konda haqiqiy holat).
        db.add(SupplierPayment(supplier_id=sup.id, amount=D(500), method="cash", paid_at=AT,
                               created_at=AT))
        db.commit()
    return w


@pytest.mark.parametrize("path", ["/reports/cashflow", "/reports/dashboard", "/reports/summary"])
def test_BITTA_FILIAL_pivot_PARAMETRSIZGA_teng_filialsiz_qatorlar_ham(client, S1, path):
    h = _token(S1["ega"], "ega", S1["cid"])
    full = _get(client, path, h)
    piv = _get(client, path, h, branch=S1["br"])
    assert full.status_code == 200 and piv.status_code == 200, (full.status_code, piv.status_code)
    assert piv.json() == full.json(), (
        f"{path}: yagona filialga pivot parametrsiz javobdan FARQ qildi — filialsiz qator yo'qolgan")


def test_BITTA_FILIAL_naqd_oqimda_filialsiz_TOLOVLAR_KORINADI(client, S1):
    h = _token(S1["ega"], "ega", S1["cid"])
    j = _get(client, "/reports/cashflow", h, branch=S1["br"]).json()
    assert float(j["in"]["qarz_qaytdi"]) == 900.0, ("filialsiz mijoz to'lovi yo'qoldi", j)
    assert float(j["out"]["beruvchiga"]) == 500.0, ("smenasiz ta'minotchi to'lovi yo'qoldi", j)
    # kassada = 1000 (naqd savdo) + 900 (qarz qaytdi) - 500 (beruvchiga)
    assert float(j["kassada"]) == 1400.0, ("kassa oshirib ko'rsatilgan", j)


# ═══ FIKSTURA VAQTI: KUN OYNASI YARIM TUNDA AG'DARILMASIN ═══════════════════
#
# `period=day` oynasi `[mahalliy yarim tun, hozir]`. Fikstura faktlarni yarim
# tundan sal keyin yozadi, shu bois zona QAT'IY bo'lsa (`Asia/Tashkent`) CI
# 19:00 UTC dan keyin — Toshkentда ertangi kun — hamma "bugungi" raqamni NOLGA
# aylantirardi. Aynan shu CI'ni qizil qildi (36043795170, 36044494277).
def test_FIKSTURA_zonasi_har_qanday_soatda_yarim_tundan_UZOQ():
    from app.api.v1.reports import _TZ_OFFSETS

    def since_midnight(now, off):
        local = now.astimezone(timezone(timedelta(hours=off)))
        return local.hour * 3600 + local.minute * 60 + local.second

    worst = None
    for hour in range(24):
        for minute in (0, 30):
            now = datetime(2026, 6, 15, hour, minute, tzinfo=timezone.utc)
            best = max(sorted(_TZ_OFFSETS.items()), key=lambda kv: since_midnight(now, kv[1]))
            head = since_midnight(now, best[1])
            if worst is None or head < worst[0]:
                worst = (head, f"{hour:02d}:{minute:02d}Z -> {best[0]}")
    assert worst[0] >= 2 * 3600, (
        "tanlangan zona yarim tunga juda yaqin — uzoq yurish kun oynasini kesib o'tishi mumkin", worst)


def test_FIKSTURA_AT_kun_oynasi_ICHIDA():
    """`AT` haqiqatan bugungi do'kon kunida va hozirdan oldin."""
    from app.api.v1.reports import _TZ_OFFSETS
    local = timezone(timedelta(hours=_TZ_OFFSETS[TZ]))
    midnight = NOW.astimezone(local).replace(hour=0, minute=0, second=0, microsecond=0)
    assert midnight <= AT.astimezone(local), (AT, midnight)
    assert AT < NOW, (AT, NOW)
