# -*- coding: utf-8 -*-
"""`customer_groups` va `brands` — DO'KONGA BOG'LANGANLIGI (tenancy).

Bu ikki jadval dastlabki sxemada `company_id` SIZ e'lon qilingan edi. Audit ko'rsatdiki
ular "global katalog" emas, TUGALLANMAGAN ish edi: na CRUD, na UI, na seed, na birorta
yozuvchi. Yonidagi `categories` esa DOIM do'konga bog'langan.

Bu testlar tuzatishning UCH xossasini mixlab qo'yadi:
  1. ustun va cheklovlar mavjud
  2. CROSS-TENANT bog'lanish BAZA DARAJASIDA imkonsiz (kompozit FK)
  3. purge ularni FK grafi orqali TABIIY o'chiradi (reyestrsiz)
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pgserver = pytest.importorskip("pgserver")


def _norm(url: str) -> str:
    for pfx in ("postgres://", "postgresql://"):
        if url.startswith(pfx):
            return "postgresql+psycopg://" + url[len(pfx):]
    return url


@pytest.fixture(scope="module")
def eng(tmp_path_factory):
    import app.models  # noqa: F401
    from app.db.base import Base

    srv = pgserver.get_server(str(tmp_path_factory.mktemp("tenancy_pg")))
    e = create_engine(_norm(srv.get_uri()), future=True)
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def two_companies(eng):
    """Ikki do'kon — har birida bitta guruh, brend, mijoz va mahsulot."""
    from decimal import Decimal as D

    S = sessionmaker(bind=eng, future=True)
    with eng.begin() as con:
        for t in ("products", "customers", "brands", "customer_groups", "units", "companies"):
            con.execute(text(f'DELETE FROM "{t}"'))

    out = {}
    with S() as s:
        from app.models.catalog import Brand, Product, Unit
        from app.models.customers import Customer, CustomerGroup
        from app.models.org import Company

        unit = Unit(code="dona", name="dona", allow_fraction=False); s.add(unit); s.flush()
        for tag in ("A", "B"):
            co = Company(name=f"Do'kon {tag}", code=tag.lower(), currency="UZS")
            s.add(co); s.flush()
            g = CustomerGroup(company_id=co.id, name="Ulgurji", discount_pct=D("10"))
            s.add(g); s.flush()
            b = Brand(company_id=co.id, name="Brend"); s.add(b); s.flush()
            c = Customer(company_id=co.id, code=f"M-{tag}", full_name="Mijoz",
                         group_id=g.id, credit_balance=D("0"), loyalty_points=0,
                         is_active=True)
            s.add(c); s.flush()
            p = Product(company_id=co.id, article_code=f"A-{tag}", name="Mahsulot",
                        unit_id=unit.id, brand_id=b.id, base_buy_price=D("1"),
                        base_sell_price=D("2"), tax_rate=D("0"), is_weighted=False,
                        scale_sync=False, is_active=True)
            s.add(p); s.flush()
            out[tag] = {"company": co.id, "group": g.id, "brand": b.id,
                        "customer": c.id, "product": p.id, "unit": unit.id}
        s.commit()
    return {"engine": eng, "factory": S, **out}


# ═══ 1) SXEMA ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("table", ["customer_groups", "brands"])
def test_A_company_id_is_not_null_with_fk(eng, table):
    """`company_id` mavjud, NOT NULL va `companies` ga FK."""
    with eng.connect() as c:
        col = c.execute(text("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name=:t AND column_name='company_id'"""), {"t": table}).scalar()
        assert col == "NO", f"{table}.company_id NOT NULL emas"

        fk = c.execute(text("""
            SELECT count(*) FROM pg_constraint con
            JOIN pg_class ch ON ch.oid = con.conrelid
            JOIN pg_class pa ON pa.oid = con.confrelid
            WHERE con.contype='f' AND ch.relname=:t AND pa.relname='companies'"""),
            {"t": table}).scalar()
        assert fk >= 1, f"{table} -> companies FK yo'q"


@pytest.mark.parametrize("table", ["customer_groups", "brands"])
def test_B_uniqueness_is_tenant_scoped(two_companies, table):
    """Bir xil nom IKKI do'konda bo'lishi MUMKIN; BITTA do'konda takror MUMKIN EMAS."""
    from sqlalchemy.exc import IntegrityError

    eng = two_companies["engine"]
    # Ikki do'konda ham "Ulgurji"/"Brend" bor — fixture buni allaqachon isbotladi.
    with eng.connect() as c:
        n = c.execute(text(f'SELECT count(*) FROM "{table}" WHERE name IN (:a,:b)'),
                      {"a": "Ulgurji", "b": "Brend"}).scalar()
        assert n == 2, "bir xil nom ikki do'konda yashay olmadi"

    # Ayni do'konda TAKROR — rad etilishi shart
    with pytest.raises(IntegrityError):
        with eng.begin() as c:
            c.execute(text(
                f'INSERT INTO "{table}" (id, company_id, name, created_at, updated_at,'
                ' row_version) VALUES (:i,:c,:n, now(), now(), 1)'),
                {"i": uuid.uuid4(), "c": two_companies["A"]["company"],
                 "n": "Ulgurji" if table == "customer_groups" else "Brend"})


# ═══ 2) CROSS-TENANT BOG'LANISH — ASOSIY KAFOLAT ════════════════════════════

def test_C_customer_cannot_use_another_companys_group(two_companies):
    """A do'koni mijozi B do'konining guruhini OLA OLMAYDI.

    Bu tuzatishning ASOSIY sababi. Oddiy FK bunga RUXSAT berardi: `group_id` faqat
    `customer_groups.id` ga qarardi va qaysi do'kon ekani tekshirilmasdi."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError) as ei:
        with two_companies["engine"].begin() as c:
            c.execute(text("UPDATE customers SET group_id = :g WHERE id = :cust"),
                      {"g": two_companies["B"]["group"], "cust": two_companies["A"]["customer"]})
    assert "fk_customers_group_same_company" in str(ei.value)


def test_D_product_cannot_use_another_companys_brand(two_companies):
    """A do'koni mahsuloti B do'konining brendini OLA OLMAYDI."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError) as ei:
        with two_companies["engine"].begin() as c:
            c.execute(text("UPDATE products SET brand_id = :b WHERE id = :p"),
                      {"b": two_companies["B"]["brand"], "p": two_companies["A"]["product"]})
    assert "fk_products_brand_same_company" in str(ei.value)


def test_E_null_link_is_still_allowed(two_companies):
    """Guruhsiz mijoz / brendsiz mahsulot — YAROQLI holat (MATCH SIMPLE)."""
    with two_companies["engine"].begin() as c:
        c.execute(text("UPDATE customers SET group_id = NULL WHERE id = :i"),
                  {"i": two_companies["A"]["customer"]})
        c.execute(text("UPDATE products SET brand_id = NULL WHERE id = :i"),
                  {"i": two_companies["A"]["product"]})
    with two_companies["engine"].connect() as c:
        assert c.execute(text("SELECT group_id FROM customers WHERE id=:i"),
                         {"i": two_companies["A"]["customer"]}).scalar() is None


def test_F_own_company_link_is_allowed(two_companies):
    """O'Z do'konining guruhi/brendi — normal ishlaydi (gard ortiqcha qattiq emas)."""
    with two_companies["engine"].begin() as c:
        c.execute(text("UPDATE customers SET group_id = :g WHERE id = :i"),
                  {"g": two_companies["A"]["group"], "i": two_companies["A"]["customer"]})
        c.execute(text("UPDATE products SET brand_id = :b WHERE id = :i"),
                  {"b": two_companies["A"]["brand"], "i": two_companies["A"]["product"]})


# ═══ 3) PURGE BILAN TABIIY ISHLASHI ═════════════════════════════════════════

def test_G_purge_graph_owns_both_tables_via_fk(two_companies):
    """Purge ularni FK grafi orqali topadi — REYESTR yozuvisiz."""
    from app.tools import tenant_purge as TP

    with two_companies["factory"]() as s:
        ownership, _order, meta = TP.build_ownership(s)
        for tbl in ("customer_groups", "brands"):
            node = ("public", tbl)
            assert node in ownership, f"{tbl} egalik grafida YO'Q"
            assert "direct_fk:company_id" in meta["how"][node], meta["how"][node]
            assert node not in TP.SEMANTIC_REGISTRY, f"{tbl} hamon reyestrda"


def test_H_purge_counts_and_isolates_both_tables(two_companies):
    """Quruq sinov ularni sanaydi; YONDOSH do'kon qatorlari sanoqqa KIRMAYDI."""
    from app.tools import tenant_purge as TP

    with two_companies["factory"]() as s:
        ownership, order, _m = TP.build_ownership(s)
        a = TP.collect_counts(s, two_companies["A"]["company"], ownership, order)
        b = TP.collect_counts(s, two_companies["B"]["company"], ownership, order)
    for counts in (a, b):
        assert counts.get("public.customer_groups") == 1, counts
        assert counts.get("public.brands") == 1, counts


def test_I_units_stay_global(two_companies):
    """`units` GLOBAL qolishi SHART — u fizik o'lchov, do'kon siyosati emas.

    Muhim amaliy sabab: `products._unit_map(db)` BARCHA birliklarni company filtri
    SIZ o'qiydi. Uni do'konga bog'lash mahsulot ro'yxatini JIMGINA buzardi."""
    from app.tools import tenant_purge as TP

    with two_companies["factory"]() as s:
        ownership, _o, _m = TP.build_ownership(s)
        assert ("public", "units") not in ownership, "units do'konga bog'lanib qoldi"
        assert TP.SEMANTIC_REGISTRY[("public", "units")]["klass"] == "GLOBAL_SHARED"
    with two_companies["engine"].connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='units'"))}
        assert "company_id" not in cols


# ═══ 4) MIGRATSIYA — ESKI sxemadan yangisiga ════════════════════════════════

@pytest.fixture
def legacy_db(tmp_path_factory):
    """ESKI sxemani QO'LDA quradi: `customer_groups`/`brands` da company_id YO'Q,
    bolalarida esa ODDIY FK. Bu production/staging'dagi haqiqiy boshlang'ich holat."""
    import app.models  # noqa: F401
    from app.db.base import Base

    srv = pgserver.get_server(str(tmp_path_factory.mktemp("legacy_pg")))
    e = create_engine(_norm(srv.get_uri()), future=True)
    Base.metadata.create_all(e)

    # Yangi sxemani ESKISIGA qaytaramiz (migratsiya sinovi uchun)
    with e.begin() as c:
        c.execute(text("ALTER TABLE customers DROP CONSTRAINT fk_customers_group_same_company"))
        c.execute(text("ALTER TABLE products  DROP CONSTRAINT fk_products_brand_same_company"))
        for tbl, pfx in (("customer_groups", "cgroup"), ("brands", "brand")):
            c.execute(text(f'ALTER TABLE "{tbl}" DROP CONSTRAINT uq_{pfx}_company_name'))
            c.execute(text(f'ALTER TABLE "{tbl}" DROP CONSTRAINT uq_{pfx}_company_id'))
            c.execute(text(f'ALTER TABLE "{tbl}" DROP COLUMN company_id'))
        c.execute(text("ALTER TABLE customers ADD CONSTRAINT customers_group_id_fkey "
                       "FOREIGN KEY (group_id) REFERENCES customer_groups(id)"))
        c.execute(text("ALTER TABLE products ADD CONSTRAINT products_brand_id_fkey "
                       "FOREIGN KEY (brand_id) REFERENCES brands(id)"))
    yield e
    e.dispose()


def _run_migration(engine_obj):
    """`initdb._ensure_tenant_scoped_catalogs` ni SHU bazaga qarshi yurgizadi."""
    import app.initdb as I
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(I, "engine", engine_obj)
    mp.setattr(I, "inspect", __import__("sqlalchemy").inspect)
    try:
        I._ensure_tenant_scoped_catalogs()
    finally:
        mp.undo()


def test_J_migration_adds_tenancy_to_empty_tables(legacy_db, capsys):
    """BO'SH jadvallarda migratsiya to'liq o'tadi (production holati: 0 qator)."""
    from decimal import Decimal as D

    # Staging shakli: bolalarida QATOR BOR, lekin bog'lam NULL
    S = sessionmaker(bind=legacy_db, future=True)
    with S() as s:
        from app.models.catalog import Product, Unit
        from app.models.customers import Customer
        from app.models.org import Company
        co = Company(name="Staging", code="stg", currency="UZS"); s.add(co); s.flush()
        u = Unit(code="dona", name="dona", allow_fraction=False); s.add(u); s.flush()
        for i in range(5):
            s.add(Customer(company_id=co.id, code=f"M{i}", full_name="M",
                           credit_balance=D("0"), loyalty_points=0, is_active=True))
        for i in range(19):
            s.add(Product(company_id=co.id, article_code=f"A{i}", name="P", unit_id=u.id,
                          base_buy_price=D("1"), base_sell_price=D("2"), tax_rate=D("0"),
                          is_weighted=False, scale_sync=False, is_active=True))
        s.commit()

    _run_migration(legacy_db)

    with legacy_db.connect() as c:
        for t in ("customer_groups", "brands"):
            nullable = c.execute(text("""
                SELECT is_nullable FROM information_schema.columns
                WHERE table_name=:t AND column_name='company_id'"""), {"t": t}).scalar()
            assert nullable == "NO", f"{t}: company_id qo'shilmadi"
        # Bolalardagi qatorlar SAQLANDI
        assert c.execute(text("SELECT count(*) FROM customers")).scalar() == 5
        assert c.execute(text("SELECT count(*) FROM products")).scalar() == 19
        # Kompozit FK o'rnatildi
        for name in ("fk_customers_group_same_company", "fk_products_brand_same_company"):
            n = c.execute(text("SELECT count(*) FROM pg_constraint WHERE conname=:n"),
                          {"n": name}).scalar()
            assert n == 1, f"{name} yaratilmadi"


def test_K_migration_is_idempotent(legacy_db):
    """Ikki marta ishga tushirish xavfsiz (har boot'da chaqiriladi)."""
    _run_migration(legacy_db)
    _run_migration(legacy_db)
    with legacy_db.connect() as c:
        n = c.execute(text("""
            SELECT count(*) FROM information_schema.columns
            WHERE table_name='customer_groups' AND column_name='company_id'""")).scalar()
        assert n == 1


def test_L_migration_refuses_to_guess_when_rows_exist(legacy_db, capsys):
    """Jadvalda QATOR bo'lsa — migratsiya TEGMAYDI va ogohlantiradi.

    `company_id NOT NULL` qo'shish uchun mavjud qatorlar EGASINI bilish kerak.
    Uni taxmin qilib bo'lmaydi, shu bois sxema O'ZGARMAYDI va operator xabardor
    qilinadi. Ilova baribir ko'tariladi (boot buzilmaydi)."""
    with legacy_db.begin() as c:
        # `legacy_db` faqat company_id va uniqlarni olib tashlaydi; FullMixin ustunlari
        # (row_version va h.k.) joyida qoladi, shu bois ular ham beriladi.
        c.execute(text("INSERT INTO customer_groups (id, name, discount_pct, created_at,"
                       " updated_at, row_version) "
                       "VALUES (:i, 'Eski guruh', 5, now(), now(), 1)"),
                  {"i": uuid.uuid4()})

    _run_migration(legacy_db)
    out = capsys.readouterr().out
    assert "company_id QO'SHILMADI" in out, out

    with legacy_db.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='customer_groups'"))}
        assert "company_id" not in cols, "qator bo'lsa ham ustun qo'shildi"
        assert c.execute(text("SELECT count(*) FROM customer_groups")).scalar() == 1
