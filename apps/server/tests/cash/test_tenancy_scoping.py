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
        # ⚠️  HAQIQIY legacy shakli. Ilgari bu yerda faqat `company_id` tashlanardi va
        # `FullMixin` ustunlari (`created_at`/`updated_at`/`row_version`/`client_uuid`)
        # `create_all` yaratgan TO'G'RI ta'rifi bilan qolib ketardi. Natijada migratsiya
        # ularni UMUMAN qayta yaratmasdi va parity testi `row_version` server default
        # farqini KO'RMASDI. Production'dagi haqiqiy jadval esa asl `PKMixin` modeliga
        # mos: CustomerGroup -> (id, name, discount_pct), Brand -> (id, name, deleted_at).
        for tbl, pfx, drop_cols in (
            ("customer_groups", "cgroup",
             ("company_id", "created_at", "updated_at", "deleted_at",
              "row_version", "client_uuid")),
            ("brands", "brand",
             ("company_id", "created_at", "updated_at", "row_version", "client_uuid")),
        ):
            c.execute(text(f'ALTER TABLE "{tbl}" DROP CONSTRAINT uq_{pfx}_company_name'))
            c.execute(text(f'ALTER TABLE "{tbl}" DROP CONSTRAINT uq_{pfx}_company_id'))
            for col in drop_cols:
                c.execute(text(f'ALTER TABLE "{tbl}" DROP COLUMN {col}'))
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

    # LEGACY jadvalda faqat asl `PKMixin` ustunlari bor:
    #   customer_groups -> (id, name, discount_pct) · brands -> (id, name, deleted_at)
    cols = "id, name, discount_pct" if table == "customer_groups" else "id, name"
    vals = ":i, 'Eski', 5" if table == "customer_groups" else ":i, 'Eski'"
    with legacy_db.begin() as c:
        c.execute(text(f'INSERT INTO "{table}" ({cols}) VALUES ({vals})'),
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
    """Jadvalning TO'LIQ shakli — HECH NARSA normallashtirilmaydi.

    ⚠️  `column_default` XOM ifoda sifatida solishtiriladi ("1", "now()", None).
    Ilgari bu yerda `row[4] is not None` ishlatilardi, ya'ni "default BORmi" degan
    ZAIF savol. Shu sabab `row_version` da model `None`, migratsiya esa `'1'` bergani
    KO'RINMASDI va "ikkala yo'l bir xil sxema beradi" degan da'vo YOLG'ON edi."""
    shape = {"columns": {}, "constraints": set()}
    with engine_obj.connect() as c:
        for row in c.execute(text("""
            SELECT table_name, column_name, data_type, is_nullable, column_default,
                   character_maximum_length, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name = ANY(:t)
            ORDER BY 1,2"""), {"t": list(tables)}):
            shape["columns"][(row[0], row[1])] = {
                "type": row[2], "nullable": row[3],
                "server_default": row[4],          # XOM ifoda — normallashtirilmaydi
                "max_len": row[5], "precision": row[6], "scale": row[7],
            }
        # PK / FK / UNIQUE / CHECK — to'liq ta'rifi bilan
        for row in c.execute(text("""
            SELECT ch.relname, con.conname, con.contype, pg_get_constraintdef(con.oid)
            FROM pg_constraint con
            JOIN pg_class ch ON ch.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = ch.relnamespace
            WHERE n.nspname='public' AND ch.relname = ANY(:t)"""), {"t": list(tables)}):
            shape["constraints"].add((row[0], row[1], row[2], row[3]))
    return shape


def test_Q_model_and_migration_produce_identical_schema(tmp_path_factory):
    """MODEL yo'li (`create_all`) va MIGRATSIYA yo'li AYNAN bir xil sxema berishi SHART.

    Solishtiriladi: ustun nomi, turi, nullability, ANIQ server default ifodasi,
    uzunlik/aniqlik, hamda PK/FK/UNIQUE/CHECK ta'riflari.

    Aks holda yangi o'rnatma va ko'chirilgan baza HAR XIL bo'lardi: keyingi
    migratsiyalar bir muhitda ishlab, boshqasida yiqilardi. (Bu allaqachon IKKI marta
    chiqqan: cheklov nomlari jadval nomining kesimidan olingani, va `row_version` da
    migratsiya doimiy `DEFAULT 1` qoldirgani.)"""
    import app.models  # noqa: F401
    from app.db.base import Base

    # (A) MODEL yo'li — toza create_all
    srv_a = pgserver.get_server(str(tmp_path_factory.mktemp("shape_model")))
    ea = create_engine(_norm(srv_a.get_uri()), future=True)
    Base.metadata.create_all(ea)

    # (B) MIGRATSIYA yo'li — HAQIQIY legacy holatiga qaytarib, keyin ko'chirish
    srv_b = pgserver.get_server(str(tmp_path_factory.mktemp("shape_migrated")))
    eb = create_engine(_norm(srv_b.get_uri()), future=True)
    Base.metadata.create_all(eb)
    with eb.begin() as c:
        c.execute(text("ALTER TABLE customers DROP CONSTRAINT fk_customers_group_same_company"))
        c.execute(text("ALTER TABLE products  DROP CONSTRAINT fk_products_brand_same_company"))
        for tbl, pfx, drop_cols in (
            ("customer_groups", "cgroup",
             ("company_id", "created_at", "updated_at", "deleted_at",
              "row_version", "client_uuid")),
            ("brands", "brand",
             ("company_id", "created_at", "updated_at", "row_version", "client_uuid")),
        ):
            c.execute(text(f'ALTER TABLE "{tbl}" DROP CONSTRAINT uq_{pfx}_company_name'))
            c.execute(text(f'ALTER TABLE "{tbl}" DROP CONSTRAINT uq_{pfx}_company_id'))
            for col in drop_cols:
                c.execute(text(f'ALTER TABLE "{tbl}" DROP COLUMN {col}'))
        c.execute(text("ALTER TABLE customers ADD CONSTRAINT customers_group_id_fkey "
                       "FOREIGN KEY (group_id) REFERENCES customer_groups(id)"))
        c.execute(text("ALTER TABLE products ADD CONSTRAINT products_brand_id_fkey "
                       "FOREIGN KEY (brand_id) REFERENCES brands(id)"))
    _run_migration(eb)

    try:
        a, b = _table_shape(ea), _table_shape(eb)

        only_a = set(a["columns"]) - set(b["columns"])
        only_b = set(b["columns"]) - set(a["columns"])
        assert not only_a and not only_b, (
            f"USTUN TO'PLAMI farq qildi:\n  faqat modelda: {only_a}\n"
            f"  faqat migratsiyada: {only_b}")

        mism = {k: (a["columns"][k], b["columns"][k])
                for k in a["columns"] if a["columns"][k] != b["columns"][k]}
        assert not mism, "USTUN TA'RIFI farq qildi:\n" + "\n".join(
            f"  {k[0]}.{k[1]}\n      model     : {v[0]}\n      migratsiya: {v[1]}"
            for k, v in sorted(mism.items()))

        assert a["constraints"] == b["constraints"], (
            "CHEKLOVLAR farq qildi:\n"
            f"  faqat modelda:      {a['constraints'] - b['constraints']}\n"
            f"  faqat migratsiyada: {b['constraints'] - a['constraints']}")
    finally:
        ea.dispose(); eb.dispose()


@pytest.mark.parametrize("table", ["customer_groups", "brands"])
def test_Q2_row_version_has_no_server_default_after_migration(legacy_db, table):
    """`row_version` da SERVER DEFAULT bo'lmasligi SHART — model uni Python tomonda beradi.

        SyncMixin:  row_version: Mapped[int] = mapped_column(BigInteger, default=1)

    `default=` — Python qiymati, `server_default=` EMAS. Migratsiya generik DDL
    xavfsizligi uchun VAQTINCHA `DEFAULT 1` qo'yadi va AYNI TRANZAKSIYADA olib
    tashlaydi; yakuniy sxemada default QOLMASLIGI kerak."""
    _run_migration(legacy_db)
    with legacy_db.connect() as c:
        d = c.execute(text("""
            SELECT column_default FROM information_schema.columns
            WHERE table_schema='public' AND table_name=:t AND column_name='row_version'
        """), {"t": table}).scalar()
        assert d is None, f"{table}.row_version da server default QOLDI: {d!r}"
        # NOT NULL esa SAQLANISHI kerak
        nn = c.execute(text("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_schema='public' AND table_name=:t AND column_name='row_version'
        """), {"t": table}).scalar()
        assert nn == "NO", f"{table}.row_version NOT NULL emas"


def _readd_old_default(engine_obj, tables=("customer_groups", "brands")):
    """1386599 migratsiyasi qoldirgan `DEFAULT 1` ni QAYTARADI.

    Ya'ni production/staging bazasining 2026-09-09 18:01 dagi AYNAN holati."""
    with engine_obj.begin() as c:
        for t in tables:
            c.execute(text(f'ALTER TABLE "{t}" ALTER COLUMN row_version SET DEFAULT 1'))


def test_Q3_leftover_server_default_is_needs_repair_not_partial(legacy_db):
    """Qolib ketgan default — PARTIAL emas, NEEDS_REPAIR.

    Bu FARQ production'ni ishdan chiqargan edi. `DEFAULT 1` — MODEL BILAN MOSLIK
    nuqsoni; cross-tenant himoyasiga (company_id NOT NULL + companies FK + ikkala
    UNIQUE + bola KOMPOZIT FK) MUTLAQO ta'sir qilmaydi. Uni PARTIAL deb baholash
    TO'G'RI ko'chirilgan bazani "yarim migratsiya" deb e'lon qilib, boot'ni
    abadiy bloklaydi."""
    import app.initdb as I

    _run_migration(legacy_db)
    _readd_old_default(legacy_db, ("customer_groups",))

    spec = next(sp for sp in I._TENANCY_TABLES if sp["table"] == "customer_groups")
    with legacy_db.connect() as c:
        state, ev = I._tenancy_state(c, spec)
    assert state == I._ST_NEEDS_REPAIR, (state, ev)
    assert state != I._ST_PARTIAL
    assert ev["row_version_server_default"] == "1", ev


def test_S_database_migrated_by_the_old_code_self_heals(legacy_db, capsys):
    """⚠️  PRODUCTION REGRESSIYASI. 1386599 ko'chirgan baza 865f562 da boot BO'LMADI.

    Ketma-ketlik (2026-09-09):
      15:55  1386599 -> production'ga avto-deploy; migratsiya `DEFAULT 1` QOLDIRDI
      17:10  a10ed10 -> normal ishladi
      18:01  865f562 -> `_tenancy_state` default'ni ham talab qila boshladi;
             TO'LIQ ko'chirilgan baza PARTIAL deb baholandi -> UnsafeSchemaError
             -> production VA staging crash-loop, HTTP 502.

    Ya'ni yangi versiya ESKI versiyasi ko'chirgan bazani boot qila olmasdi.
    Endi u default'ni o'zi olib tashlaydi va normal ko'tariladi."""
    from app.initdb import UnsafeSchemaError

    _run_migration(legacy_db)          # 1) yangi sxema
    _readd_old_default(legacy_db)      # 2) eski migratsiya qoldirgan holatga qaytaramiz

    capsys.readouterr()
    try:
        _run_migration(legacy_db)      # 3) YANGI kod ESKI baza ustida boot bo'ladi
    except UnsafeSchemaError as e:     # noqa: BLE001
        raise AssertionError(
            "eski migratsiya qoldirgan baza boot BO'LMADI — bu aynan "
            f"production'ni ishdan chiqargan regressiya:\n{e}") from e

    out = capsys.readouterr().out
    assert "row_version" in out, f"tuzatish haqida xabar chiqmadi: {out!r}"

    with legacy_db.connect() as c:
        for t in ("customer_groups", "brands"):
            d = c.execute(text("""
                SELECT column_default FROM information_schema.columns
                WHERE table_schema='public' AND table_name=:t AND column_name='row_version'
            """), {"t": t}).scalar()
            assert d is None, f"{t}.row_version da default QOLDI: {d!r}"
        # Tenancy cheklovlari BUZILMAGAN va TAKRORLANMAGAN
        for name in ("uq_cgroup_company_name", "uq_cgroup_company_id",
                     "uq_brand_company_name", "uq_brand_company_id",
                     "fk_customers_group_same_company", "fk_products_brand_same_company"):
            n = c.execute(text("SELECT count(*) FROM pg_constraint WHERE conname=:n"),
                          {"n": name}).scalar()
            assert n == 1, f"{name}: {n} ta (aynan 1 bo'lishi kerak)"


def test_T_repair_works_on_a_table_that_has_rows(legacy_db):
    """Tuzatish QATORLI jadvalda ham ishlaydi — u METAMA'LUMOT amali.

    Bu muhim: haqiqiy do'konda `brands`/`customer_groups` da qatorlar BO'LADI.
    LEGACY migratsiyasidagi "qator bo'lsa to'xta" qoidasi bu yerga TEGISHLI EMAS,
    chunki `DROP DEFAULT` hech qanday qatorni o'qimaydi ham, yozmaydi ham va
    egalik savoli umuman tug'ilmaydi."""
    _run_migration(legacy_db)

    S = sessionmaker(bind=legacy_db, future=True)
    with S() as ss:
        from app.models.catalog import Brand
        from app.models.customers import CustomerGroup
        from app.models.org import Company
        co = Company(name="Do'kon", code="d1", currency="UZS"); ss.add(co); ss.flush()
        ss.add(CustomerGroup(company_id=co.id, name="VIP", discount_pct=5))
        ss.add(Brand(company_id=co.id, name="Nestle"))
        ss.commit()

    _readd_old_default(legacy_db)
    _run_migration(legacy_db)          # xato KO'TARMASLIGI kerak

    with legacy_db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM customer_groups")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM brands")).scalar() == 1
        for t in ("customer_groups", "brands"):
            assert c.execute(text("""
                SELECT column_default FROM information_schema.columns
                WHERE table_schema='public' AND table_name=:t AND column_name='row_version'
            """), {"t": t}).scalar() is None
        # Qatorlar EGASI saqlanib qoldi
        assert c.execute(text(
            "SELECT count(*) FROM customer_groups WHERE company_id IS NULL")).scalar() == 0


def test_U_readiness_recovers_after_self_heal(legacy_db, monkeypatch):
    """Tuzatishdan keyin readiness YASHIL bo'ladi (502 dan chiqish yo'li)."""
    import app.initdb as I

    _run_migration(legacy_db)
    _readd_old_default(legacy_db)
    monkeypatch.setattr(I, "engine", legacy_db)

    ok_before, ev_before = I.tenancy_schema_ok()
    assert ok_before is False, ev_before      # tuzatilmagan holat readiness BERMAYDI

    _run_migration(legacy_db)
    ok_after, ev_after = I.tenancy_schema_ok()
    assert ok_after is True, ev_after


def test_V_repair_is_idempotent(legacy_db):
    """Ketma-ket boot'lar xavfsiz — ikkinchi marta tuzatadigan narsa qolmaydi."""
    _run_migration(legacy_db)
    _readd_old_default(legacy_db)
    _run_migration(legacy_db)
    _run_migration(legacy_db)
    _run_migration(legacy_db)
    with legacy_db.connect() as c:
        n = c.execute(text("""
            SELECT count(*) FROM pg_constraint WHERE conname='uq_cgroup_company_id'""")).scalar()
        assert n == 1
        assert c.execute(text("""
            SELECT column_default FROM information_schema.columns
            WHERE table_name='customer_groups' AND column_name='row_version'""")).scalar() is None


@pytest.mark.parametrize("broken", ["uq_cgroup_company_name", "uq_cgroup_company_id",
                                    "fk_customers_group_same_company"])
def test_W_genuinely_partial_schema_still_fails_closed(legacy_db, broken):
    """⚠️  NEEDS_REPAIR yo'li fail-closed himoyasini TESHIB QO'YMAGAN.

    Agar TENANCY cheklovlarining o'zi chala bo'lsa — cross-tenant himoyasi
    haqiqatan QISMAN — va boot HAMON to'xtashi kerak."""
    from app.initdb import UnsafeSchemaError

    _run_migration(legacy_db)
    tbl = "customers" if broken.startswith("fk_") else "customer_groups"
    # CASCADE kerak: bola KOMPOZIT FK `uq_..._company_id` indeksiga tayanadi.
    # U ham tushib ketadi — sxema bundan yanada CHALAROQ bo'ladi, ya'ni sinov
    # zaiflashmaydi.
    with legacy_db.begin() as c:
        c.execute(text(f'ALTER TABLE "{tbl}" DROP CONSTRAINT "{broken}" CASCADE'))

    before = _schema_fingerprint(legacy_db)
    with pytest.raises(UnsafeSchemaError) as ei:
        _run_migration(legacy_db)
    assert "YARIM MIGRATSIYA" in str(ei.value), str(ei.value)
    assert _schema_fingerprint(legacy_db) == before


def _state_of(engine_obj, table="customer_groups"):
    """`_tenancy_state` ni SHU baza ustida chaqiradi."""
    import app.initdb as I
    spec = next(sp for sp in I._TENANCY_TABLES if sp["table"] == table)
    with engine_obj.connect() as c:
        return I._tenancy_state(c, spec)


# ═══ 6) CHEKLOV NOMI EMAS, SHAKLI ══════════════════════════════════════════

def test_X_same_named_constraint_on_another_table_does_not_count(legacy_db):
    """⚠️  Cheklov NOMI dalil emas — u AYNAN SHU jadvalda bo'lishi kerak.

    Ilgari tekshiruv `WHERE conname = :n` edi: na jadval, na sxema, na turi
    solishtirilmasdi. Ya'ni butun bazada shu nomdagi BEGONA cheklov ham
    "tenancy himoyasi joyida" degan xulosaga yetardi — va xulosa MIGRATED
    bo'lgach backend trafik qabul qilaverardi."""
    _run_migration(legacy_db)
    assert _state_of(legacy_db)[0] == "MIGRATED"

    with legacy_db.begin() as c:
        # Haqiqiysini olib tashlaymiz...
        c.execute(text("ALTER TABLE customer_groups DROP CONSTRAINT uq_cgroup_company_name"))
        # ...va AYNAN SHU NOMDAGI cheklovni BOSHQA jadvalga qo'yamiz (aldamchi).
        c.execute(text("ALTER TABLE categories "
                       "ADD CONSTRAINT uq_cgroup_company_name UNIQUE (company_id, name)"))

    state, ev = _state_of(legacy_db)
    assert state == "PARTIAL", (state, ev)
    assert ev["uq_cgroup_company_name"] is False, ev


def test_X2_wrong_constraint_type_with_the_right_name_does_not_count(legacy_db):
    """Nomi to'g'ri, TURI noto'g'ri (CHECK) — bu UNIQUE kafolatini bermaydi."""
    _run_migration(legacy_db)
    with legacy_db.begin() as c:
        # CASCADE kerak: kompozit FK shu unique indeksga tayanadi. U ham tushadi,
        # ya'ni PARTIAL ikki sababdan kelib chiqadi — lekin quyidagi ANIQ dalil
        # tekshiruvi aynan TUR nomosligini isbotlaydi.
        c.execute(text("ALTER TABLE customer_groups "
                       "DROP CONSTRAINT uq_cgroup_company_id CASCADE"))
        c.execute(text("ALTER TABLE customer_groups "
                       "ADD CONSTRAINT uq_cgroup_company_id CHECK (company_id IS NOT NULL)"))
    state, ev = _state_of(legacy_db)
    assert state == "PARTIAL", (state, ev)
    assert ev["uq_cgroup_company_id"] is False, ev


def test_X3_unique_on_the_wrong_columns_does_not_count(legacy_db):
    """Nomi to'g'ri, USTUNLARI noto'g'ri — noyoblik boshqa narsani qo'riqlaydi."""
    _run_migration(legacy_db)
    with legacy_db.begin() as c:
        c.execute(text("ALTER TABLE customer_groups DROP CONSTRAINT uq_cgroup_company_name"))
        c.execute(text("ALTER TABLE customer_groups "
                       "ADD CONSTRAINT uq_cgroup_company_name UNIQUE (id, name)"))
    state, ev = _state_of(legacy_db)
    assert state == "PARTIAL", (state, ev)


def test_X4_column_order_does_not_matter(legacy_db):
    """`UNIQUE (name, company_id)` — AYNI kafolat, PARTIAL bo'lmasligi kerak.

    Ortiqcha qat'iylik ham xavfli: u bekordan-bekorga boot'ni bloklardi —
    aynan shu sinf xatosi production'ni ishdan chiqargan edi."""
    _run_migration(legacy_db)
    with legacy_db.begin() as c:
        c.execute(text("ALTER TABLE customer_groups DROP CONSTRAINT uq_cgroup_company_name"))
        c.execute(text("ALTER TABLE customer_groups "
                       "ADD CONSTRAINT uq_cgroup_company_name UNIQUE (name, company_id)"))
    state, ev = _state_of(legacy_db)
    assert state == "MIGRATED", (state, ev)


def test_Y_not_valid_composite_fk_does_not_count(legacy_db):
    """⚠️  `NOT VALID` FK tenancy artefakti EMAS.

    U yangi yozuvlarni tekshiradi, lekin MAVJUD qatorlarni TEKSHIRMAYDI — ya'ni
    allaqachon BOSHQA do'kon guruhiga ishora qilayotgan qatorlar joyida qolaveradi.
    Bunday cheklov "cross-tenant bog'lanish BAZA DARAJASIDA imkonsiz" degan
    da'voni bajarmaydi, shuning uchun MIGRATED bermasligi kerak."""
    _run_migration(legacy_db)
    with legacy_db.begin() as c:
        c.execute(text("ALTER TABLE customers DROP CONSTRAINT fk_customers_group_same_company"))
        c.execute(text("ALTER TABLE customers ADD CONSTRAINT fk_customers_group_same_company "
                       "FOREIGN KEY (company_id, group_id) "
                       "REFERENCES customer_groups(company_id, id) NOT VALID"))

    state, ev = _state_of(legacy_db)
    assert state == "PARTIAL", (state, ev)
    assert ev["fk_customers_group_same_company"] is False, ev
    # Dalillarda SABABI ko'rinsin
    assert ev.get("fk_customers_group_same_company__shakli", {}).get("validated") is False, ev


def test_Y2_validated_composite_fk_counts(legacy_db):
    """`VALIDATE CONSTRAINT` dan keyin AYNI cheklov yana hisobga olinadi."""
    _run_migration(legacy_db)
    with legacy_db.begin() as c:
        c.execute(text("ALTER TABLE customers DROP CONSTRAINT fk_customers_group_same_company"))
        c.execute(text("ALTER TABLE customers ADD CONSTRAINT fk_customers_group_same_company "
                       "FOREIGN KEY (company_id, group_id) "
                       "REFERENCES customer_groups(company_id, id) NOT VALID"))
    assert _state_of(legacy_db)[0] == "PARTIAL"

    with legacy_db.begin() as c:
        c.execute(text("ALTER TABLE customers "
                       "VALIDATE CONSTRAINT fk_customers_group_same_company"))
    state, ev = _state_of(legacy_db)
    assert state == "MIGRATED", (state, ev)


def test_Y3_composite_fk_to_the_wrong_table_does_not_count(legacy_db):
    """FK mavjud, lekin BOSHQA jadvalga ishora qiladi — kafolat yo'q."""
    _run_migration(legacy_db)
    with legacy_db.begin() as c:
        c.execute(text("ALTER TABLE customers DROP CONSTRAINT fk_customers_group_same_company"))
        # `brands` ham `(company_id, id)` unique'ga ega — sintaktik jihatdan o'tadi
        c.execute(text("ALTER TABLE customers ADD CONSTRAINT fk_customers_group_same_company "
                       "FOREIGN KEY (company_id, group_id) REFERENCES brands(company_id, id)"))
    state, ev = _state_of(legacy_db)
    assert state == "PARTIAL", (state, ev)


def test_Y4_a_shape_mismatch_never_silently_repairs(legacy_db):
    """Shakl nomos bo'lsa — NEEDS_REPAIR emas, PARTIAL. Ya'ni tuzatish yo'li
    tenancy teshigini yopib yubormaydi."""
    from app.initdb import UnsafeSchemaError

    _run_migration(legacy_db)
    with legacy_db.begin() as c:
        c.execute(text("ALTER TABLE customers DROP CONSTRAINT fk_customers_group_same_company"))
        c.execute(text("ALTER TABLE customers ADD CONSTRAINT fk_customers_group_same_company "
                       "FOREIGN KEY (company_id, group_id) "
                       "REFERENCES customer_groups(company_id, id) NOT VALID"))
        c.execute(text("ALTER TABLE customer_groups ALTER COLUMN row_version SET DEFAULT 1"))

    before = _schema_fingerprint(legacy_db)
    with pytest.raises(UnsafeSchemaError) as ei:
        _run_migration(legacy_db)
    assert "YARIM MIGRATSIYA" in str(ei.value), str(ei.value)
    assert _schema_fingerprint(legacy_db) == before
    # Default HAM olib tashlanmagan bo'lishi kerak (tranzaksiya qaytdi)
    with legacy_db.connect() as c:
        assert c.execute(text("""
            SELECT column_default FROM information_schema.columns
            WHERE table_name='customer_groups' AND column_name='row_version'""")).scalar() == "1"


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
        # ORM bilan AYNAN mos: `row_version` da server default YO'Q
        assert "row_version   bigint NOT NULL," in block, tbl
        assert "row_version   bigint NOT NULL DEFAULT" not in block, tbl
    assert "fk_customers_group_same_company" in sql
    assert "fk_products_brand_same_company" in sql
    # Eski ODDIY FK'lar QOLMAGAN bo'lishi kerak
    assert "group_id      uuid REFERENCES customer_groups(id)" not in sql
    assert "brand_id      uuid REFERENCES brands(id)" not in sql
