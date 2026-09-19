# -*- coding: utf-8 -*-
"""CHEK / CHOP ETISH POYGALARI — HAQIQIY POSTGRES (Phase 5F).

⚠️  NEGA SQLite YETMAYDI. Bu yerdagi kafolatlar QULF va NOYOB INDEKSDAN keladi:
    SQLite'da `with_for_update()` no-op, advisory qulf yo'q, yozuvchilar fayl qulfi
    bilan baribir ketma-ket — ya'ni «ikki oyna ayni chekni bir vaqtda asl deb yozdi»
    holati mahalliy to'plamda UMUMAN o'lchanmaydi.

⚠️  INTERLEAVING MAJBURIY (`test_lot_tz_confirm_pg._navbat`): birinchi tranzaksiya
    yozib commit QILMAY turadi, ikkinchisi uning qulfini KUTAYOTGANI `pg_blocking_pids`
    da ko'rilgach birinchisi commit qiladi (`kutdi`). Kutish ko'rilmasa sinov QIZIL.

Bu fayl isbotlaydi:
  1. ikki parallel ASL chek (boshqa id) — BITTASI yoziladi, ikkinchisi 409
     `PRINT_ORIGINAL_EXISTS`; ayni id bilan parallel takror — `duplicate`, BITTA qator;
     `ux_print_jobs_original` boot'dan keyin joyida, tayyorlik yashil;
  2. ikki parallel NUSXA — raqamlar 1 va 2 (advisory qulf); SALBIY NAZORAT: qulfsiz ikkalasi
     AYNI raqamni oladi;
  3. logo `bytea` — original/rastr/PNG bayt-bayt qaytadi, `original` deferred; ayni
     faylni parallel yuklash — BITTA qator; yangi jadvallarda FAQAT `companies` FK;
  4. filial ustamasi BIRINCHI yozuv poygasi (UNIQUE(company_id, branch_id, key)) va
     kompaniya qatori poygasi (`ux_settings_company_key`) — istisno yo'q, BITTA qator,
     ikkala maydon ham saqlanadi; mavjud qatorda FOR UPDATE — yo'qolgan yangilanish yo'q.
  5. chek DTO Postgres'da: qatorlar `ctid` bo'yicha SAVAT tartibida, qaytarishda TILL
     kodi `cash` sxemasidan SAVEPOINT ichida o'qiladi (sessiya buzilmaydi).

Maqsad-baza: `test_check_defs_pg.pg_target` (har test uchun alohida baza; CI'da `-k external`).
"""
import io
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import text

from tests.test_check_defs_pg import _initdb, pg_target  # noqa: F401
from tests.test_lot_tz_confirm_pg import _mk, _navbat

NOW = datetime.now(timezone.utc)


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════
def _baza(url):
    _initdb(url)
    eng, S = _mk(url)
    # ⚠️  SQLite'ga jimgina tushib qolsa, poygalar YASHIL bo'lib qolardi va hech narsani
    #     isbotlamasdi.
    assert eng.dialect.name == "postgresql", eng.dialect.name
    return eng, S


def _dokon(S):
    """Kompaniya + 2 filial + ega + bitta sotuv (qoldiq/kassaga tegmasdan)."""
    from app.models.auth import Employee, Role
    from app.models.org import Branch, Company
    from app.models.sales import Sale
    s = S()
    try:
        co = Company(id=uuid.uuid4(), name="5F PG", code="c5f" + uuid.uuid4().hex[:8], currency="UZS")
        s.add(co)
        s.flush()
        bids = []
        for i in (1, 2):
            b = Branch(id=uuid.uuid4(), company_id=co.id, code=f"F0{i}", name=f"5F B{i}",
                       timezone="Asia/Tashkent", is_active=True)
            s.add(b)
            s.flush()
            bids.append(b.id)
        ega = s.query(Role).filter(Role.code == "ega").one()
        e = Employee(id=uuid.uuid4(), company_id=co.id, full_name="5F ega",
                     phone="+9989" + str(uuid.uuid4().int)[:8], role_id=ega.id)
        s.add(e)
        s.flush()
        sale = Sale(id=uuid.uuid4(), company_id=co.id, branch_id=bids[0], cashier_id=e.id,
                    receipt_no="#1", uid="2609191", subtotal=Decimal("100"), total=Decimal("100"),
                    discount_total=Decimal("0"), cost_total=Decimal("0"), sold_at=NOW)
        s.add(sale)
        s.commit()
        return {"cid": co.id, "b1": bids[0], "b2": bids[1], "emp": e.id, "sale": sale.id}
    finally:
        s.close()


def _emp(s, d):
    from app.models.auth import Employee
    return s.get(Employee, d["emp"])


def _job(d, copy="ORIGINAL", jid=None):
    from app.services.receipt import jobs as RJ
    return RJ.parse_create({"id": jid or str(uuid.uuid4()), "doc_type": "SALE",
                            "doc_id": str(d["sale"]), "copy": copy})


def _create(d, data):
    from app.services.receipt import jobs as RJ
    return lambda s: RJ.create_job(s, _emp(s, d), data)[1]


def _rows(eng, sql, **kw):
    with eng.connect() as con:
        return con.execute(text(sql), kw).all()


def _xatosiz(r):
    assert not isinstance(r.get("a"), Exception) and not isinstance(r.get("b"), Exception), r
    assert r["kutdi"] is True, f"ikkinchi tranzaksiya qulfni KUTMADI — poyga oynasi ochilmadi: {r}"


# ══ 1 · ASL CHEK NOYOBLIGI ═══════════════════════════════════════════════════
def test_PG_ikki_parallel_ASL_chek_BITTASI_yoziladi_ikkinchisi_409(pg_target):
    from app.core import required_schema as rs
    eng, S = _baza(pg_target)
    try:
        ddl = _rows(eng, "SELECT indexdef FROM pg_indexes WHERE indexname = 'ux_print_jobs_original'")
        assert ddl and "UNIQUE" in ddl[0][0] and "'ORIGINAL'" in ddl[0][0], ddl
        assert _rows(eng, "SELECT 1 FROM pg_indexes WHERE indexname = 'ix_print_jobs_doc'")
        ok, missing = rs.ok(eng)
        assert ok, missing
        d = _dokon(S)
        a, b = _job(d), _job(d)
        r = _navbat(eng, S, _create(d, a), _create(d, b))
        assert r["kutdi"] is True, r
        assert r["a"] is True, r
        assert isinstance(r["b"], HTTPException) and r["b"].status_code == 409, r
        assert r["b"].headers == {"X-Error-Code": "PRINT_ORIGINAL_EXISTS"}
        got = _rows(eng, "SELECT id FROM print_jobs WHERE copy = 'ORIGINAL' AND doc_id = :d",
                    d=d["sale"])
        assert [g[0] for g in got] == [a["id"]]
        # Ayni id bilan parallel takror (boshqa hujjat) — `duplicate`, BITTA qator, istisnosiz.
        d2 = dict(d)
        from app.models.sales import Sale
        s = S()
        s2 = Sale(id=uuid.uuid4(), company_id=d["cid"], branch_id=d["b1"], cashier_id=d["emp"],
                  receipt_no="#2", subtotal=Decimal("1"), total=Decimal("1"),
                  discount_total=Decimal("0"), cost_total=Decimal("0"), sold_at=NOW)
        s.add(s2)
        s.commit()
        s.close()
        d2["sale"] = s2.id
        same = _job(d2)
        r = _navbat(eng, S, _create(d2, same), _create(d2, same))
        _xatosiz(r)
        assert (r["a"], r["b"]) == (True, False), r
        assert len(_rows(eng, "SELECT 1 FROM print_jobs WHERE id = :i", i=same["id"])) == 1
    finally:
        eng.dispose()


# ══ 2 · NUSXA RAQAMI ═════════════════════════════════════════════════════════
def test_PG_ikki_parallel_NUSXA_raqamlari_1_va_2_qulfsiz_AYNI_raqam(pg_target, monkeypatch):
    from app.services.receipt import jobs as RJ
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        a, b = _job(d, "REPRINT"), _job(d, "REPRINT")
        r = _navbat(eng, S, _create(d, a), _create(d, b))
        _xatosiz(r)
        got = dict(_rows(eng, "SELECT id, copy_no FROM print_jobs WHERE doc_id = :d", d=d["sale"]))
        assert (got[a["id"]], got[b["id"]]) == (1, 2), got
        # SALBIY NAZORAT: advisory qulf olib tashlansa ikkinchi tranzaksiya kutmaydi va
        # AYNI raqamni oladi — ya'ni sinov qulfni haqiqatan o'lchaydi.
        monkeypatch.setattr(RJ, "_doc_lock", lambda *a, **k: None)
        c, e = _job(d, "REPRINT"), _job(d, "REPRINT")
        r = _navbat(eng, S, _create(d, c), _create(d, e))
        assert r["kutdi"] is False and r["a"] is True and r["b"] is True, r
        got = dict(_rows(eng, "SELECT id, copy_no FROM print_jobs WHERE doc_id = :d", d=d["sale"]))
        assert got[c["id"]] == got[e["id"]] == 3, got
    finally:
        eng.dispose()


# ══ 3 · LOGO BYTEA ═══════════════════════════════════════════════════════════
def test_PG_logo_bytea_ROUNDTRIP_parallel_takror_va_FAQAT_companies_FK(pg_target):
    from PIL import Image, ImageDraw

    from app.models.receipt import ReceiptLogo
    from app.services.receipt import logo as RL
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        img = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((20, 10, 280, 110), fill=(0, 0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        raw = buf.getvalue()
        assert b"\x00" in raw                  # NUL baytlar ham bayt-bayt qaytishi shart

        def up(branch_id):
            return lambda s: RL.store_logo(s, _emp(s, d), branch_id, raw)[1]
        r = _navbat(eng, S, up(None), up(None))
        _xatosiz(r)
        assert (r["a"], r["b"]) == (True, False), r
        lid = RL.logo_uuid(d["cid"], None, __import__("hashlib").sha256(raw).hexdigest())
        s = S()
        try:
            row = s.get(ReceiptLogo, lid)
            assert "original" not in row.__dict__
            assert bytes(row.original) == raw
            p = RL.process(raw)
            for k, v in p.variants.items():
                assert bytes(getattr(row, f"raster{k}")) == v.raster, k
                assert bytes(getattr(row, f"png{k}")) == v.png, k
                assert (getattr(row, f"raster{k}_w"), getattr(row, f"raster{k}_h")) == (v.width, v.height)
        finally:
            s.close()
        assert len(_rows(eng, "SELECT 1 FROM receipt_logos")) == 1
        types = dict(_rows(eng, "SELECT column_name, data_type FROM information_schema.columns "
                                "WHERE table_name = 'receipt_logos' AND column_name IN "
                                "('original', 'raster58', 'raster80', 'png58', 'png80')"))
        assert set(types.values()) == {"bytea"} and len(types) == 5, types
        fks = _rows(eng, "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint "
                         "WHERE contype = 'f' AND conrelid::regclass::text IN ('receipt_logos', 'print_jobs') "
                         "ORDER BY 1")
        assert fks == [("print_jobs", "companies"), ("receipt_logos", "companies")], fks
        assert not _rows(eng, "SELECT 1 FROM pg_constraint WHERE contype = 'c' AND "
                              "conrelid::regclass::text IN ('receipt_logos', 'print_jobs')")
    finally:
        eng.dispose()


# ══ 4 · SOZLAMA QATORI POYGALARI ═════════════════════════════════════════════
def test_PG_filial_va_kompaniya_BIRINCHI_yozuv_poygasi_va_FOR_UPDATE_merge(pg_target):
    from app.models.org import Branch
    from app.services.receipt import settings as RS
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        assert _rows(eng, "SELECT 1 FROM pg_indexes WHERE indexname = 'ux_settings_company_key'")

        def w(patch, bid):
            return lambda s: RS.write_receipt_settings(
                s, _emp(s, d), s.get(Branch, bid) if bid else None, RS.validate_receipt_patch(patch))

        def rows(bid):
            sql = "SELECT value, row_version FROM settings WHERE company_id = :c AND key = 'receipt' "
            if bid is None:
                return _rows(eng, sql + "AND branch_id IS NULL", c=d["cid"])
            return _rows(eng, sql + "AND branch_id = :b", c=d["cid"], b=bid)

        # Filial: qator YO'Q, ikki birinchi INSERT — UNIQUE(company_id, branch_id, key).
        r = _navbat(eng, S, w({"footer": "A rahmat"}, d["b1"]), w({"width_mm": 58}, d["b1"]))
        _xatosiz(r)
        [(val, ver)] = rows(d["b1"])
        assert val == {"footer": "A rahmat", "width_mm": 58} and ver == 2, (val, ver)
        # Kompaniya: qator YO'Q, ikki birinchi INSERT — `ux_settings_company_key`.
        r = _navbat(eng, S, w({"header": "Aksiya"}, None), w({"copies": 2}, None))
        _xatosiz(r)
        [(val, ver)] = rows(None)
        assert val == {"header": "Aksiya", "copies": 2} and ver == 2, (val, ver)
        # Qator BOR: FOR UPDATE — ikkinchi yozuvchi birinchisining natijasi USTIGA qo'shadi.
        r = _navbat(eng, S, w({"show_till": True}, d["b1"]), w({"auto_print": True}, d["b1"]))
        _xatosiz(r)
        [(val, ver)] = rows(d["b1"])
        assert val == {"footer": "A rahmat", "width_mm": 58, "show_till": True, "auto_print": True}
        assert ver == 4
        # B2 ga tegilmagan.
        assert rows(d["b2"]) == []
    finally:
        eng.dispose()


# ══ 5 · DTO POSTGRES'DA (ctid tartibi, TILL savepoint) ═══════════════════════
def test_PG_chek_DTO_qatorlar_SAVAT_tartibida_qaytarish_TILL_yoli(pg_target):
    """`ORDER BY sale_items.ctid` / `return_items.ctid` — faqat Postgres'da ishlaydigan yo'l;
    qaytarishda `till_id` bor bo'lsa `cash` sxemasi SAVEPOINT ichida o'qiladi (topilmasa —
    TILL kodi shunchaki yo'q, tranzaksiya buzilmaydi)."""
    from app.models.catalog import Product, Unit
    from app.models.sales import Return, ReturnItem, Sale, SaleItem, SalePayment
    from app.services.receipt.dto import build_return_receipt, build_sale_receipt
    eng, S = _baza(pg_target)
    try:
        d = _dokon(S)
        names = [f"Q{i:02d} {uuid.uuid4().hex[:4]}" for i in range(12)]
        s = S()
        try:
            unit = s.query(Unit).filter(Unit.code == "dona").one()
            p = Product(id=uuid.uuid4(), company_id=d["cid"], name="5F mahsulot",
                        article_code="5F-" + uuid.uuid4().hex[:8], unit_id=unit.id,
                        base_buy_price=Decimal("1"), base_sell_price=Decimal("10"), tax_rate=0)
            s.add(p)
            s.flush()
            sale = Sale(id=uuid.uuid4(), company_id=d["cid"], branch_id=d["b1"], cashier_id=d["emp"],
                        receipt_no="#77", uid="26091977", subtotal=Decimal("120"),
                        total=Decimal("120"), discount_total=Decimal("0"), cost_total=Decimal("0"),
                        sold_at=NOW)
            for n in names:
                sale.items.append(SaleItem(product_id=p.id, name_snapshot=n, qty=Decimal("1"),
                                           unit_price=Decimal("10"), unit_cost=Decimal("0"),
                                           discount=Decimal("0"), line_total=Decimal("10")))
            sale.payments.append(SalePayment(method_code="card", amount=Decimal("120"), paid_at=NOW))
            s.add(sale)
            s.flush()
            ret = Return(id=uuid.uuid4(), return_no="QAY-77", company_id=d["cid"], branch_id=d["b1"],
                         cashier_id=d["emp"], original_sale_id=sale.id, refund_method="card",
                         total=Decimal("20"), till_id=uuid.uuid4())
            for it in sale.items[:2]:
                ret.items.append(ReturnItem(product_id=p.id, sale_item_id=it.id, qty=Decimal("1"),
                                            unit_price=Decimal("10"), unit_cost=Decimal("0"),
                                            line_total=Decimal("10")))
            s.add(ret)
            s.commit()
            sid, rid = sale.id, ret.id
        finally:
            s.close()
        s = S()
        try:
            dto = build_sale_receipt(s, s.get(Sale, sid))
            assert [ln["name"] for ln in dto["lines"]] == names
            assert dto["totals"]["total"] == "120.00" and dto["doc"]["uid"] == "26091977"
            rdto = build_return_receipt(s, s.get(Return, rid))
            assert [ln["name"] for ln in rdto["lines"]] == names[:2]
            assert rdto["actor"]["till_code"] is None and rdto["original"]["number"] == "#77"
            # Savepoint'dan keyin sessiya SOG'LOM — keyingi so'rov ishlaydi.
            assert s.execute(text("SELECT 1")).scalar() == 1
        finally:
            s.close()
    finally:
        eng.dispose()
