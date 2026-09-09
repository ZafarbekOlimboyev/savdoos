# -*- coding: utf-8 -*-
"""TENANT PURGE — do'kon ma'lumotini butunlay o'chirish vositasi.

Bu YAGONA qaytarib bo'lmaydigan vosita, shu bois testlar HAQIQIY Postgres'da,
HAQIQIY sxema (public + cash, append-only triggerlar bilan) ustida ishlaydi.
Fixture'da IKKI do'kon bor: nishon va YONDOSH — yondoshning bitta qatori ham
tegilmasligi har testda tekshiriladi.

Alohida pgserver nusxasi ishlatiladi: bu testlar ma'lumot O'CHIRADI va umumiy
`cashenv` bazasini buzib qo'yardi.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

pgserver = pytest.importorskip("pgserver")

from app.tools import tenant_purge as TP  # noqa: E402

NOW = datetime.now(timezone.utc)


def _norm(url: str) -> str:
    for pfx in ("postgres://", "postgresql://"):
        if url.startswith(pfx):
            return "postgresql+psycopg://" + url[len(pfx):]
    return url


# ═══ FIXTURE: REALISTIK TENANT ══════════════════════════════════════════════
def _make_tenant(s: Session, code: str, name: str, *, recent: bool,
                 ledger_native: bool) -> dict:
    """To'liq do'kon: filial, terminal, xodim, katalog, ombor, mijoz, ta'minotchi,
    xarid, savdo, qaytarish, smena, naqd harakat, sozlama."""
    from decimal import Decimal as D

    from app.models.auth import Employee, Role
    from app.models.catalog import Category, Product, ProductBarcode, Unit
    from app.models.customers import CreditTransaction, Customer, CustomerPayment
    from app.models.inventory import Inventory, StockMovement
    from app.models.org import Branch, Company, Terminal
    from app.models.purchasing import Purchase, PurchaseItem, Supplier, SupplierPayment
    from app.models.sales import Return, ReturnItem, Sale, SaleItem, SalePayment
    from app.models.settings import Setting
    from app.models.shifts import CashMovement, Shift

    co = Company(name=name, code=code, currency="UZS"); s.add(co); s.flush()
    role = Role(code=f"role_{code}", name="Kassir", is_system=False); s.add(role); s.flush()
    emp = Employee(company_id=co.id, full_name=f"Kassir {code}", role_id=role.id,
                   status="active")
    s.add(emp); s.flush()
    br = Branch(company_id=co.id, code="F01", name="Asosiy", timezone="Asia/Tashkent",
                is_active=True)
    s.add(br); s.flush()
    term = Terminal(branch_id=br.id, name="Kassa-1", is_active=True); s.add(term); s.flush()

    unit = Unit(code=f"u_{code}", name="dona", allow_fraction=False); s.add(unit); s.flush()
    cat = Category(company_id=co.id, name="Toifa", sort_order=0); s.add(cat); s.flush()
    prod = Product(company_id=co.id, article_code=f"A_{code}", name="Mahsulot",
                   unit_id=unit.id, category_id=cat.id, base_buy_price=D("500"),
                   base_sell_price=D("1000"), tax_rate=D("0"), is_weighted=False,
                   scale_sync=False, is_active=True)
    s.add(prod); s.flush()
    s.add(ProductBarcode(company_id=co.id, product_id=prod.id, barcode=f"BC{code}",
                         pack_qty=1, is_primary=True))
    s.add(Inventory(product_id=prod.id, branch_id=br.id, qty=D("100"), reserved_qty=D("0"),
                    min_qty=D("0"), low_alerted=False, updated_at=NOW))
    s.add(StockMovement(product_id=prod.id, branch_id=br.id, type="purchase_in",
                        qty=D("100"), created_at=NOW))

    cust = Customer(company_id=co.id, code=f"M_{code}", full_name="Mijoz",
                    credit_balance=D("5000"), loyalty_points=0, is_active=True)
    s.add(cust); s.flush()
    s.add(CreditTransaction(customer_id=cust.id, type="charge", amount=D("5000"),
                            balance_after=D("5000"), created_at=NOW))
    s.add(CustomerPayment(customer_id=cust.id, branch_id=br.id, amount=D("1000"),
                          method="cash", paid_at=NOW, created_at=NOW))

    sup = Supplier(company_id=co.id, name="Ta'minotchi", balance=D("0"), is_active=True)
    s.add(sup); s.flush()
    pur = Purchase(company_id=co.id, branch_id=br.id, supplier_id=sup.id, doc_no=f"P_{code}",
                   purchase_date=NOW, status="received", currency="UZS", subtotal=D("5000"),
                   discount=D("0"), total=D("5000"), paid_amount=D("5000"), created_at=NOW)
    s.add(pur); s.flush()
    s.add(PurchaseItem(purchase_id=pur.id, product_id=prod.id, qty=D("10"),
                       unit_cost=D("500"), line_total=D("5000")))
    s.add(SupplierPayment(supplier_id=sup.id, amount=D("5000"), method="cash",
                          paid_at=NOW, created_at=NOW))

    sh = Shift(branch_id=br.id, cashier_id=emp.id, opening_cash=D("0"), status="closed",
               opened_at=NOW - timedelta(days=1))
    s.add(sh); s.flush()
    s.add(CashMovement(shift_id=sh.id, type="payin", amount=D("1000"), employee_id=emp.id,
                       created_at=NOW))

    sold = NOW - timedelta(days=2 if recent else 400)
    for i in range(5):
        sale = Sale(company_id=co.id, branch_id=br.id, cashier_id=emp.id, shift_id=sh.id,
                    receipt_no=f"R_{code}_{i}", status="completed", currency="UZS",
                    subtotal=D("2000"), discount_total=D("0"), tax_total=D("0"),
                    total=D("2000"), cost_total=D("1000"), sold_at=sold, is_offline=False)
        s.add(sale); s.flush()
        s.add(SaleItem(sale_id=sale.id, product_id=prod.id, name_snapshot="Mahsulot",
                       qty=D("2"), unit_price=D("1000"), unit_cost=D("500"),
                       discount=D("0"), tax_rate=D("0"), line_total=D("2000")))
        s.add(SalePayment(sale_id=sale.id, method_code="cash", amount=D("2000"), paid_at=sold))
        if i == 0:
            ret = Return(company_id=co.id, branch_id=br.id, cashier_id=emp.id,
                         original_sale_id=sale.id, shift_id=sh.id,
                         return_no=f"Q_{code}", reason="other", restock=True,
                         refund_method="cash", total=D("2000"), created_at=sold)
            s.add(ret); s.flush()
            s.add(ReturnItem(return_id=ret.id, product_id=prod.id, qty=D("2"),
                             unit_price=D("1000"), unit_cost=D("500"), line_total=D("2000")))

    s.add(Setting(company_id=co.id, branch_id=None, key="store", value={"name": name}))
    if ledger_native:
        s.add(Setting(company_id=co.id, branch_id=None, key="cash",
                      value={"ledger_native": True, "onboarded_at": NOW.isoformat(),
                             "cutover_at": NOW.isoformat()}))
    s.commit()
    return {"id": co.id, "code": code, "branch_id": br.id, "shift_id": sh.id,
            "product_id": prod.id, "employee_id": emp.id, "terminal_id": term.id}


def _make_untracked_rows(con, t: dict, *, qr: bool, device_version: str | None):
    """FK'SIZ jadvallar — faqat FK grafini kuzatsak YETIM qolardi."""
    con.execute(text(
        "INSERT INTO scales (id, company_id, name, connection_type, status,"
        " synced_count, is_active, created_at, updated_at)"
        " VALUES (:i,:c,'Tarozi','lan','disconnected',0,true, now(), now())"),
        {"i": uuid.uuid4(), "c": t["id"]})
    con.execute(text(
        "INSERT INTO sync_devices (id, device_uuid, company_id, branch_id, app_version,"
        " created_at) VALUES (:i,:d,:c,:b,:v, now())"),
        {"i": uuid.uuid4(), "d": f"dev-{t['code']}-{uuid.uuid4().hex[:6]}",
         "c": t["id"], "b": t["branch_id"], "v": device_version})
    if qr:
        con.execute(text(
            "INSERT INTO qr_payments (id, company_id, txn_id, amount, status,"
            " created_at, updated_at)"
            " VALUES (:i,:c,:x, 1000, 'COMPLETED', now(), now())"),
            {"i": uuid.uuid4(), "c": t["id"], "x": f"txn-{uuid.uuid4().hex[:10]}"})


def _make_cash_rows(con, t: dict):
    """cash sxemasi: hisob + smena + ledger + reconciliation (append-only!)."""
    acc = uuid.uuid4()
    con.execute(text(
        "INSERT INTO cash.cash_accounts (id, tenant_id, branch_id, type, currency, status,"
        " label, created_at) VALUES (:i,:t,:b,'TILL','UZS','ACTIVE','TILL-01', now())"),
        {"i": acc, "t": t["id"], "b": t["branch_id"]})
    csh = uuid.uuid4()
    con.execute(text(
        "INSERT INTO cash.shifts (id, tenant_id, branch_id, cash_account_id, account_type,"
        " status, opened_at, opened_by, version)"
        " VALUES (:i,:t,:b,:a,'TILL','OPEN', now(), :e, 1)"),
        {"i": csh, "t": t["id"], "b": t["branch_id"], "a": acc, "e": t["employee_id"]})
    for i in range(4):
        con.execute(text(
            "INSERT INTO cash.cash_ledger_entries (id, tenant_id, cash_account_id, branch_id,"
            " account_type, shift_id, posting_kind, source_type, source_id, leg_index,"
            " direction, category, amount, currency, device_occurred_at, server_received_at,"
            " recorded_at, idempotency_key, provenance, metadata)"
            " VALUES (:i,:t,:a,:b,'TILL',:s,'ON_SHIFT','SALE',:src,0,'IN','SALE',:amt,'UZS',"
            " now(), now(), now(), :k, 'NORMAL', '{}'::jsonb)"),
            {"i": uuid.uuid4(), "t": t["id"], "a": acc, "b": t["branch_id"], "s": csh,
             "src": uuid.uuid4(), "amt": 1000 + i, "k": f"{t['code']}-{i}"})
    con.execute(text(
        "INSERT INTO cash.reconciliation_records (id, tenant_id, target_type, shift_id,"
        " cash_account_id, account_type, seq, is_current, ledger_balance_snapshot,"
        " counted_cash, difference, state, created_at)"
        # SHIFT nishonida cash_account_id va account_type NULL bo'lishi SHART
        # (rr_target_shape + rr_account_target_safe cheklovlari).
        " VALUES (:i,:t,'SHIFT',:s,NULL,NULL,1,true, 4006, 4006, 0, 'PENDING', now())"),
        {"i": uuid.uuid4(), "t": t["id"], "s": csh})


@pytest.fixture(scope="module")
def db_url(tmp_path_factory):
    from app.db.base import Base
    from app.db.cash.deploy import deploy_cash_schema
    import app.models  # noqa: F401

    srv = pgserver.get_server(str(tmp_path_factory.mktemp("purge_pg")))
    url = _norm(srv.get_uri())
    eng = create_engine(url, future=True)
    Base.metadata.create_all(eng)
    assert deploy_cash_schema(eng) == "deployed"
    eng.dispose()
    return url


@pytest.fixture
def env(db_url):
    """Har test uchun TOZA holat: ikkala do'kon qayta yaratiladi."""
    eng = create_engine(db_url, future=True)
    # Oldingi testdan qolgan hamma narsani tozalaymiz (triggerlarni vaqtincha o'chirib).
    with eng.begin() as con:
        blocking = TP._blocking_triggers(con)
        for sch, tbl in blocking:
            con.execute(text(f'ALTER TABLE "{sch}"."{tbl}" DISABLE TRIGGER USER'))
        for sch, tbl in [("cash", t) for t in (
                "reconciliation_assignments", "reconciliation_records", "cash_ledger_entries",
                "cash_ledger_exceptions", "negative_cash_approvals", "cash_transfers",
                "shifts", "cash_accounts", "audit_logs")]:
            con.execute(text(f'DELETE FROM "{sch}"."{tbl}"'))
        for tbl in ("qr_payments", "scales", "sync_devices", "return_items", "returns",
                    "sale_payments", "sale_items", "sales", "cash_movements", "shifts",
                    "supplier_payments", "purchase_items", "purchases", "suppliers",
                    "credit_transactions", "customer_payments", "customers",
                    "stock_movements", "inventory", "product_barcodes", "products",
                    "categories", "settings", "terminals", "branches", "employees",
                    "roles", "units", "companies"):
            con.execute(text(f'DELETE FROM "{tbl}"'))
        for sch, tbl in blocking:
            con.execute(text(f'ALTER TABLE "{sch}"."{tbl}" ENABLE TRIGGER USER'))

    SessionLocal = sessionmaker(bind=eng, future=True)
    with SessionLocal() as s:
        target = _make_tenant(s, "demo1", "Demo Do'kon", recent=False, ledger_native=False)
        bystander = _make_tenant(s, "yondosh", "Yondosh Do'kon", recent=False,
                                 ledger_native=False)
    with eng.begin() as con:
        for t in (target, bystander):
            _make_untracked_rows(con, t, qr=False, device_version=None)
            _make_cash_rows(con, t)

    yield {"url": db_url, "engine": eng, "target": target, "bystander": bystander,
           "factory": SessionLocal}
    eng.dispose()


def _run(env, argv):
    return TP.main(argv, session_factory=env["factory"])


def _counts(env, company_id) -> dict:
    with env["factory"]() as s:
        ownership, order, _meta = TP.build_ownership(s)
        return TP.collect_counts(s, company_id, ownership, order)


def _capture(env, argv, capsys):
    code = _run(env, argv)
    out = capsys.readouterr()
    return code, out.out, out.err


# ═══ TESTLAR ════════════════════════════════════════════════════════════════

def test_A_dry_run_changes_nothing(env, capsys):
    """Standart rejim — QURUQ SINOV. Bitta qator ham o'chmasligi SHART."""
    before = _counts(env, env["target"]["id"])
    assert before, "fixture bo'sh — test ma'nosiz bo'lardi"

    code, out, _ = _capture(env, ["--company-code", "demo1"], capsys)
    assert code == 0, out
    assert "QURUQ SINOV" in out
    assert "PURGE_READY" in out

    assert _counts(env, env["target"]["id"]) == before, "quruq sinov ma'lumotni o'zgartirdi"


def test_B_dry_run_discovers_indirect_and_unlinked_tables(env, capsys):
    """Hisobot FK bo'yicha BILVOSITA va FK'SIZ jadvallarni ham topishi shart.

    `scales`, `sync_devices`, `qr_payments` da `companies` ga FK YO'Q — faqat FK
    grafini kuzatsak ular JIMGINA yetim qolardi."""
    code, out, _ = _capture(env, ["--company-code", "demo1", "--json"], capsys)
    assert code == 0
    rep = json.loads(out)
    deps = rep["dependencies"]

    # bilvosita (sale -> sale_items), (branch -> terminals)
    assert deps.get("public.sale_items"), deps
    assert deps.get("public.terminals"), deps
    # FK'siz — eng muhimi
    assert deps.get("public.scales"), "FK'siz `scales` topilmadi"
    assert deps.get("public.sync_devices"), "FK'siz `sync_devices` topilmadi"
    # cash sxemasi
    assert deps.get("cash.cash_ledger_entries"), deps
    assert deps.get("cash.reconciliation_records"), deps
    # append-only jadvallar aniqlangan
    assert "cash.cash_ledger_entries" in rep["discovery"]["append_only_tables"]


def test_C_missing_company_fails(env, capsys):
    with pytest.raises(SystemExit) as ei:
        _run(env, ["--company-code", "bunday-dokon-yoq"])
    assert "TOPILMADI" in str(ei.value)


def test_D_wildcard_and_empty_are_refused(env):
    """"Hammasini o'chirish" MUMKIN EMAS."""
    for bad in ["", "*", "%", "all", "ALL"]:
        with pytest.raises(SystemExit) as ei:
            _run(env, ["--company-code", bad])
        assert "MUMKIN EMAS" in str(ei.value) or "TOPILMADI" in str(ei.value)


def test_E_target_must_be_explicit(env):
    """Do'kon ko'rsatilmasa yoki IKKALASI berilsa — xato (taxmin YO'Q)."""
    with pytest.raises(SystemExit):
        _run(env, [])
    with pytest.raises(SystemExit):
        _run(env, ["--company-code", "demo1", "--company-id", str(env["target"]["id"])])
    with pytest.raises(SystemExit) as ei:
        _run(env, ["--company-id", "not-a-uuid"])
    assert "UUID" in str(ei.value)


def test_F_execute_requires_matching_confirmation(env, capsys):
    """--execute YOLG'IZ yetarli emas; tasdiq kodi AYNAN mos kelishi shart."""
    before = _counts(env, env["target"]["id"])

    # tasdiqsiz
    code, out, err = _capture(env, ["--company-code", "demo1", "--execute"], capsys)
    assert code == 1, out
    assert "TASDIQ MOS EMAS" in err
    assert _counts(env, env["target"]["id"]) == before

    # NOTO'G'RI tasdiq (boshqa do'kon kodi) — eng xavfli xato
    code, out, err = _capture(
        env, ["--company-code", "demo1", "--execute", "--confirm-company-code", "yondosh"], capsys)
    assert code == 1
    assert "TASDIQ MOS EMAS" in err
    assert _counts(env, env["target"]["id"]) == before
    assert _counts(env, env["bystander"]["id"]), "yondosh do'kon zarar ko'rdi"


def test_G_execute_purges_everything_and_leaves_no_orphans(env, capsys):
    """To'liq o'chirish: qoldiq YO'Q, do'kon qatori yo'q, YONDOSH TEGILMAGAN."""
    bystander_before = _counts(env, env["bystander"]["id"])
    target_before = _counts(env, env["target"]["id"])
    assert target_before.get("cash.cash_ledger_entries"), "ledger yozuvi yo'q — test kuchsiz"

    code, out, _ = _capture(
        env, ["--company-code", "demo1", "--execute", "--confirm-company-code", "demo1"], capsys)
    assert code == 0, out
    assert "TENANT_PURGE_OK" in out

    # Nishon: HECH NARSA qolmadi
    assert _counts(env, env["target"]["id"]) == {}
    with env["factory"]() as s:
        assert s.execute(text("SELECT count(*) FROM companies WHERE id=:i"),
                         {"i": env["target"]["id"]}).scalar() == 0

    # YONDOSH: bitta qator ham o'zgarmadi
    assert _counts(env, env["bystander"]["id"]) == bystander_before


def test_H_append_only_triggers_are_restored_after_purge(env, capsys):
    """Ledger triggerlari o'chirishdan KEYIN QAYTA YOQILGAN bo'lishi SHART.

    Aks holda tenant o'chirish butun bazadagi append-only kafolatini jimgina
    o'chirib ketardi — bu naqd ledgerning eng muhim xususiyati."""
    code, _out, _ = _capture(
        env, ["--company-code", "demo1", "--execute", "--confirm-company-code", "demo1"], capsys)
    assert code == 0

    with env["factory"]() as s:
        disabled = s.execute(text("""
            SELECT count(*) FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE NOT t.tgisinternal AND n.nspname='cash' AND t.tgenabled='D'
        """)).scalar()
        assert disabled == 0, "append-only triggerlar O'CHIQ qoldi"

    # Va ular HAQIQATAN ishlayotganini isbotlaymiz: yondosh ledgerni o'chirib bo'lmasin
    with env["factory"]() as s:
        with pytest.raises(Exception):
            s.execute(text("DELETE FROM cash.cash_ledger_entries WHERE tenant_id=:t"),
                      {"t": env["bystander"]["id"]})
            s.commit()


def test_I_rollback_on_failure_leaves_data_intact(env, capsys, monkeypatch):
    """Oxirgi bosqichda xato bo'lsa — TO'LIQ rollback, qisman o'chirish YO'Q."""
    before = _counts(env, env["target"]["id"])

    real = TP.execute_purge

    def boom(db, company, ownership, order, meta):
        real(db, company, ownership, order, meta)      # hamma narsani o'chiradi...
        raise RuntimeError("sun'iy nosozlik")          # ...keyin YIQILADI

    monkeypatch.setattr(TP, "execute_purge", boom)
    with pytest.raises(RuntimeError):
        _run(env, ["--company-code", "demo1", "--execute", "--confirm-company-code", "demo1"])

    after = _counts(env, env["target"]["id"])
    assert after == before, "rollback ishlamadi — ma'lumot QISMAN o'chdi"
    with env["factory"]() as s:
        assert s.execute(text("SELECT count(*) FROM companies WHERE id=:i"),
                         {"i": env["target"]["id"]}).scalar() == 1


def test_J_real_merchant_evidence_blocks_purge(env, capsys):
    """Haqiqiy mijoz dalili bo'lsa — BLOKLANADI (kod nomiga QARAMASDAN)."""
    # Ledger-native onboarding belgisini qo'yamiz
    with env["engine"].begin() as con:
        con.execute(text(
            "INSERT INTO settings (id, company_id, branch_id, key, value, row_version) "
            "VALUES (:i,:c,NULL,'cash',:v,1)"),
            {"i": uuid.uuid4(), "c": env["target"]["id"],
             "v": json.dumps({"ledger_native": True})})

    code, out, _ = _capture(env, ["--company-code", "demo1", "--json"], capsys)
    assert code == 2, out
    rep = json.loads(out)
    assert rep["verdict"] == "PURGE_BLOCKED"
    assert any(s["signal"] == "ledger_native_onboarding" for s in rep["risk_signals"])

    # Bloklangan holatda --execute ham ISHLAMAYDI
    before = _counts(env, env["target"]["id"])
    code, _out, _ = _capture(
        env, ["--company-code", "demo1", "--execute", "--confirm-company-code", "demo1"], capsys)
    assert code == 2
    assert _counts(env, env["target"]["id"]) == before


@pytest.mark.parametrize("setup,signal", [
    ("qr", "external_payments"),
    ("recent", "recent_sales_30d"),
    ("device", "reporting_devices"),
])
def test_K_each_real_merchant_signal_blocks(env, capsys, setup, signal):
    """Har bir dalil MUSTAQIL ravishda bloklashi kerak."""
    t = env["target"]
    with env["engine"].begin() as con:
        if setup == "qr":
            con.execute(text(
                "INSERT INTO qr_payments (id, company_id, txn_id, amount, status,"
                " created_at, updated_at)"
                " VALUES (:i,:c,:x,1000,'COMPLETED', now(), now())"),
                {"i": uuid.uuid4(), "c": t["id"], "x": f"txn-{uuid.uuid4().hex[:10]}"})
        elif setup == "recent":
            con.execute(text("UPDATE sales SET sold_at = now() WHERE company_id = :c"),
                        {"c": t["id"]})
        else:
            con.execute(text("UPDATE sync_devices SET app_version='0.7.0' WHERE company_id=:c"),
                        {"c": t["id"]})

    code, out, _ = _capture(env, ["--company-code", "demo1", "--json"], capsys)
    assert code == 2, out
    rep = json.loads(out)
    assert any(s["signal"] == signal for s in rep["risk_signals"]), rep["risk_signals"]


def test_L_ledger_rows_alone_do_not_block(env, capsys):
    """Naqd ledger yozuvlari YOLG'IZ holda BLOKLAMASLIGI kerak.

    Dual-write butun bazada yoqilgan, ya'ni ledger qatorlari HAR tenantda bor. Agar
    ular bloklasa, ettala eski demo ham bloklanardi va operator gardni har safar
    bekor qilishga o'rganardi — ya'ni garddan foyda qolmasdi. Ular KONTEKST."""
    code, out, _ = _capture(env, ["--company-code", "demo1", "--json"], capsys)
    assert code == 0, out
    rep = json.loads(out)
    assert rep["verdict"] == "PURGE_READY"
    assert rep["dependencies"].get("cash.cash_ledger_entries"), "fixture'da ledger yo'q"
    assert any(s["signal"] == "cash_ledger_entries" for s in rep["context_signals"])
    assert not any(s["signal"] == "cash_ledger_entries" for s in rep["risk_signals"])


def test_M_override_allows_blocked_tenant(env, capsys):
    """Bloklangan do'kon FAQAT aniq bayroq bilan o'chiriladi."""
    with env["engine"].begin() as con:
        con.execute(text(
            "INSERT INTO settings (id, company_id, branch_id, key, value, row_version) "
            "VALUES (:i,:c,NULL,'cash',:v,1)"),
            {"i": uuid.uuid4(), "c": env["target"]["id"],
             "v": json.dumps({"ledger_native": True})})

    code, _out, _ = _capture(env, ["--company-code", "demo1"], capsys)
    assert code == 2

    code, out, _ = _capture(
        env, ["--company-code", "demo1", "--execute", "--confirm-company-code", "demo1",
              "--i-know-this-is-not-a-real-merchant"], capsys)
    assert code == 0, out
    assert "TENANT_PURGE_OK" in out
    assert _counts(env, env["target"]["id"]) == {}


def test_N_second_purge_fails_safely(env, capsys):
    """O'chirilgandan KEYIN qayta urinish — aniq "topilmadi" xatosi."""
    code, _out, _ = _capture(
        env, ["--company-code", "demo1", "--execute", "--confirm-company-code", "demo1"], capsys)
    assert code == 0
    with pytest.raises(SystemExit) as ei:
        _run(env, ["--company-code", "demo1"])
    assert "TOPILMADI" in str(ei.value)


def test_O_json_report_is_stable(env, capsys):
    """JSON hisobot barqaror shaklda — operator/skript unga tayanadi."""
    code, out, _ = _capture(env, ["--company-code", "demo1", "--json"], capsys)
    assert code == 0
    rep = json.loads(out)
    assert set(rep) >= {"company", "discovery", "dependencies", "total_rows",
                        "risk_signals", "context_signals", "blockers", "verdict", "mode"}
    assert rep["mode"] == "dry_run"
    assert rep["rows_deleted"] == 0
    assert rep["company"]["code"] == "demo1"
    assert rep["total_rows"] == sum(rep["dependencies"].values())
    # Ikki marta chaqirilganda AYNAN bir xil natija
    _c2, out2, _ = _capture(env, ["--company-code", "demo1", "--json"], capsys)
    assert json.loads(out2)["dependencies"] == rep["dependencies"]


def test_P_no_secrets_in_output(env, capsys):
    """Chiqishda ulanish satri/parol bo'lmasligi shart."""
    _code, out, err = _capture(env, ["--company-code", "demo1", "--json"], capsys)
    blob = out + err
    for bad in ("postgresql://", "password", "PASSWORD", "@127.0.0.1", "@localhost"):
        assert bad not in blob, f"chiqishda sir bor: {bad}"


def test_Q_residual_tables_are_reported_not_hidden(env, capsys):
    """Egaligi ANIQLANMAGAN jadvallar hisobotda KO'RSATILADI.

    `activity_events`, `sync_log`, `sync_cursors` da tenantga FK YO'Q (branch_id /
    employee_id / device_uuid — oddiy ustunlar). Ular do'kon o'chgach ham QOLADI.
    Bu holat JIMGINA o'tkazilmasligi kerak: operator "hammasi o'chdi" deb yolg'on
    xulosa chiqarmasligi uchun ular alohida ro'yxatda chiqadi."""
    code, out, _ = _capture(env, ["--company-code", "demo1", "--json"], capsys)
    assert code == 0
    rep = json.loads(out)
    names = {r["table"] for r in rep["residual_tables"]}
    assert "public.activity_events" in names, names
    assert "public.sync_log" in names, names
    # Va ular o'chiriladiganlar ro'yxatida BO'LMASLIGI kerak (chalkashmasin)
    assert not (names & set(rep["dependencies"])), "qoldiq jadval o'chiriladiganlar ichida"


def test_R_purge_is_scoped_to_one_company_only(env, capsys):
    """Ikkinchi do'konni o'chirish BIRINCHISIGA TEGMAYDI (va aksincha)."""
    target_before = _counts(env, env["target"]["id"])

    code, _out, _ = _capture(
        env, ["--company-code", "yondosh", "--execute",
              "--confirm-company-code", "yondosh"], capsys)
    assert code == 0
    assert _counts(env, env["bystander"]["id"]) == {}
    assert _counts(env, env["target"]["id"]) == target_before, "boshqa do'kon zarar ko'rdi"
