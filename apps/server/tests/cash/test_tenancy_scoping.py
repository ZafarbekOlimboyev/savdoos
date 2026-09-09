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


def _schema_fingerprint(engine_obj) -> dict:
    """Sxemaning tegishli qismi — ustunlar + cheklovlar. Muvaffaqiyatsiz migratsiya
    bundan BIRORTASINI ham o'zgartirmasligi kerak."""
    with engine_obj.connect() as c:
        cols = {(r[0], r[1]) for r in c.execute(text("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name IN ('customer_groups','brands','customers','products')"""))}
        cons = {r[0] for r in c.execute(text("""
            SELECT con.conname FROM pg_constraint con
            JOIN pg_class ch ON ch.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = ch.relnamespace
            WHERE n.nspname='public'
              AND ch.relname IN ('customer_groups','brands','customers','products')"""))}
    return {"columns": cols, "constraints": cons}


# ═══ FAIL-CLOSED: egasi noma'lum LEGACY qatorlar ISHGA TUSHISHNI TO'XTATADI ══

@pytest.mark.parametrize("table,child", [("customer_groups", "customers"),
                                         ("brands", "products")])
def test_L_legacy_rows_fail_closed(legacy_db, table, child):
    """(C/D) LEGACY sxema + qator -> FATAL. Ilova ishga TUSHMASLIGI kerak.

    Ilgari bu holatda faqat ogohlantirish chiqib, backend baribir ko'tarilardi —
    ya'ni EGASI NOMA'LUM ma'lumot ustida "sog'lom" ishlayverardi. Bu fail-OPEN edi."""
    from app.initdb import UnsafeSchemaError

    with legacy_db.begin() as c:
        c.execute(text(
            f'INSERT INTO "{table}" (id, name, created_at, updated_at, row_version'
            + (", discount_pct" if table == "customer_groups" else "")
            + ") VALUES (:i, 'Eski', now(), now(), 1"
            + (", 5" if table == "customer_groups" else "") + ")"),
            {"i": uuid.uuid4()})

    before = _schema_fingerprint(legacy_db)

    with pytest.raises(UnsafeSchemaError) as ei:
        _run_migration(legacy_db)
    msg = str(ei.value)
    assert table in msg and "TO'XTATILDI" in msg, msg

    # (E) Sxema O'ZGARMAGAN — (F) yarim cheklov/ustun QOLMAGAN
    assert _schema_fingerprint(legacy_db) == before, "muvaffaqiyatsiz migratsiya sxemani o'zgartirdi"
    with legacy_db.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name=:t"), {"t": table})}
        assert "company_id" not in cols
        assert c.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() == 1


def test_M_partial_schema_fails_closed(legacy_db):
    """YARIM migratsiya qilingan sxema ham FATAL — jimgina davom etilmaydi.

    Yarim holatda ba'zi cheklovlar bor, ba'zilari yo'q, ya'ni cross-tenant himoyasi
    QISMAN ishlaydi. Bu eng xavfli holat: hammasi joyidadek KO'RINADI."""
    from app.initdb import UnsafeSchemaError

    # Ustunni qo'shamiz, LEKIN cheklovlarsiz -> PARTIAL
    with legacy_db.begin() as c:
        c.execute(text("ALTER TABLE customer_groups ADD COLUMN company_id uuid"))

    before = _schema_fingerprint(legacy_db)
    with pytest.raises(UnsafeSchemaError) as ei:
        _run_migration(legacy_db)
    assert "YARIM MIGRATSIYA" in str(ei.value), str(ei.value)
    assert _schema_fingerprint(legacy_db) == before


def test_N_migrated_table_with_rows_boots_normally(eng):
    """(B) MIGRATSIYA QILINGAN jadvalda qator bo'lishi — MUTLAQO NORMAL.

    Bu farq muhim: haqiqiy do'kon guruhlari/brendlari bor bazani bloklash
    mumkin emas. Faqat MIGRATSIYA QILINMAGAN jadvaldagi qatorlar bloklaydi."""
    from decimal import Decimal as D

    from app.models.customers import CustomerGroup
    from app.models.org import Company

    S = sessionmaker(bind=eng, future=True)
    with eng.begin() as c:
        for t in ("products", "customers", "brands", "customer_groups", "companies"):
            c.execute(text(f'DELETE FROM "{t}"'))
    with S() as s:
        co = Company(name="Real", code="real", currency="UZS"); s.add(co); s.flush()
        s.add(CustomerGroup(company_id=co.id, name="VIP", discount_pct=D("15")))
        s.commit()

    _run_migration(eng)          # xato KO'TARMASLIGI kerak

    with eng.connect() as c:
        assert c.execute(text("SELECT count(*) FROM customer_groups")).scalar() == 1


def test_O_readiness_is_not_healthy_on_legacy_schema(legacy_db, monkeypatch):
    """Xavfsiz BO'LMAGAN sxemada readiness HECH QACHON 'ready' bo'lmaydi.

    `initdb` ishga tushishni to'xtatadi, lekin kimdir uvicorn'ni to'g'ridan-to'g'ri
    ko'tarsa o'sha gard chetlab o'tilardi — shu bois ikkinchi qatlam."""
    import app.initdb as I

    monkeypatch.setattr(I, "engine", legacy_db)
    ok, detail = I.tenancy_schema_ok()
    assert ok is False, detail
    assert detail.get("customer_groups") == I._ST_LEGACY, detail


def test_P_readiness_healthy_after_migration(legacy_db, monkeypatch):
    """Migratsiyadan KEYIN readiness tiklanadi (gard ortiqcha qattiq emas)."""
    import app.initdb as I

    _run_migration(legacy_db)
    monkeypatch.setattr(I, "engine", legacy_db)
    ok, detail = I.tenancy_schema_ok()
    assert ok is True, detail
    assert set(detail.values()) == {I._ST_MIGRATED}, detail


# ═══ SXEMA EKVIVALENTLIGI: model yo'li == migratsiya yo'li ══════════════════

def _table_shape(engine_obj, tables=("customer_groups", "brands", "customers", "products")):
    """Jadvalning TO'LIQ shakli: ustunlar (tur/nullable/default) + cheklovlar."""
    shape = {"columns": {}, "constraints": set()}
    with engine_obj.connect() as c:
        for row in c.execute(text("""
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name = ANY(:t)
            ORDER BY 1,2"""), {"t": list(tables)}):
            # `column_default` da ketma-ketlik/now() farqlari bo'lishi mumkin —
            # faqat "default BORmi" faktini solishtiramiz.
            shape["columns"][(row[0], row[1])] = (row[2], row[3], row[4] is not None)
        for row in c.execute(text("""
            SELECT ch.relname, con.conname, con.contype,
                   pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            JOIN pg_class ch ON ch.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = ch.relnamespace
            WHERE n.nspname='public' AND ch.relname = ANY(:t)"""), {"t": list(tables)}):
            shape["constraints"].add((row[0], row[1], row[2], row[3]))
    return shape


def test_Q_model_and_migration_produce_identical_schema(tmp_path_factory):
    """MODEL yo'li (`create_all`) va MIGRATSIYA yo'li AYNAN bir xil sxema berishi SHART.

    Aks holda yangi o'rnatma va ko'chirilgan baza HAR XIL bo'lardi: keyingi
    migratsiyalar bir muhitda ishlab, boshqasida yiqilardi. (Aynan shunday nuqson
    allaqachon bir marta chiqqan edi — cheklov nomlari jadval nomining KESIMIDAN
    hosil qilingani uchun `uq_custom_...` va `uq_cgroup_...` farq qilgan edi.)"""
    import app.initdb as I
    import app.models  # noqa: F401
    from app.db.base import Base

    # (A) MODEL yo'li — toza create_all
    srv_a = pgserver.get_server(str(tmp_path_factory.mktemp("shape_model")))
    ea = create_engine(_norm(srv_a.get_uri()), future=True)
    Base.metadata.create_all(ea)

    # (B) MIGRATSIYA yo'li — legacy holatga qaytarib, keyin ko'chirish
    srv_b = pgserver.get_server(str(tmp_path_factory.mktemp("shape_migrated")))
    eb = create_engine(_norm(srv_b.get_uri()), future=True)
    Base.metadata.create_all(eb)
    with eb.begin() as c:
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
    _run_migration(eb)

    try:
        a, b = _table_shape(ea), _table_shape(eb)
        assert a["columns"] == b["columns"], (
            "USTUNLAR farq qildi:\n"
            f"  faqat modelda:      {set(a['columns']) - set(b['columns'])}\n"
            f"  faqat migratsiyada: {set(b['columns']) - set(a['columns'])}\n"
            f"  turi/nullable farq: "
            f"{{k for k in set(a['columns']) & set(b['columns']) if a['columns'][k] != b['columns'][k]}}")
        assert a["constraints"] == b["constraints"], (
            "CHEKLOVLAR farq qildi:\n"
            f"  faqat modelda:      {a['constraints'] - b['constraints']}\n"
            f"  faqat migratsiyada: {b['constraints'] - a['constraints']}")
    finally:
        ea.dispose(); eb.dispose()


def test_R_schema_sql_matches_the_models():
    """`db/schema.sql` (kanonik hujjat) modeldagi tenancy bilan MOS bo'lishi shart."""
    import pathlib

    sql = (pathlib.Path(__file__).resolve().parents[4] / "db" / "schema.sql").read_text(
        encoding="utf-8")
    for tbl in ("customer_groups", "brands"):
        block = sql[sql.index(f"CREATE TABLE {tbl} ("):]
        block = block[:block.index("\n);")]
        assert "company_id    uuid NOT NULL REFERENCES companies(id)" in block, tbl
        assert "UNIQUE (company_id, name)" in block, tbl
        assert "UNIQUE (company_id, id)" in block, tbl
    assert "fk_customers_group_same_company" in sql
    assert "fk_products_brand_same_company" in sql
    # Eski ODDIY FK'lar QOLMAGAN bo'lishi kerak
    assert "group_id      uuid REFERENCES customer_groups(id)" not in sql
    assert "brand_id      uuid REFERENCES brands(id)" not in sql
