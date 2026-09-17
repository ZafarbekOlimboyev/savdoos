# -*- coding: utf-8 -*-
"""PHASE 5C — ADVERSARIAL REVIEW TUZATISHLARI (server tomoni).

Har test AYNAN bitta tasdiqlangan topilmani mixlaydi va ESKI kodda QIZIL bo'ladi:

  D-2 · `/lots/enable` ochilish partiyalari KIRIM bilan AYNI aniqlik qoidasidan
        o'tmasdi: yig'indi Decimal'ning STANDART konteksti (ROUND_HALF_EVEN) bilan
        solishtirilardi, `create_lots` esa har partiyani `_q` (ROUND_HALF_UP) bilan
        yozadi. 1.2345 darvozadan O'TIB (1.234 == 1.234) partiya 1.235 bo'lib
        yozilardi va QAYTARIB BO'LMAYDIGAN yoqish yakuniy invariantda opaque 409
        («qo'llab-quvvatlashga murojaat qiling») bilan qulardi.
  D-3 · `opening_lots` ro'yxati cheksiz edi (kirimda cheklov BOR: `max_length=50`).
  T-1 · Kirim muharriri muddat maslahatini `GET /lots/products/{id}` dagi
        `business_date` dan oladi, kirimni esa `deps.actor_branch` filialiga
        yozadi. Endpoint esa filialsiz so'rovda «do'konning BIRINCHI filiali» ni
        (hatto NOFAOL bo'lsa ham) olardi: ko'p filialli do'konda maslahat BOSHQA
        vaqt zonasining sanasini ko'rsatardi.
  R-2 · `--lock-timeout-ms` / `--statement-timeout-ms` faqat apply/revert yo'lida
        tekshirilardi; `preflight`/`verify` xom qiymatni libpq `options` satriga
        qo'yardi (0 = CHEKSIZ sokin o'tib ketardi).
"""
import uuid
from decimal import Decimal

from app.services import lot_policy as LP

from tests.test_lot_receiving import (  # noqa: F401
    _db,
    _enable,
    _lots,
    ctx,
)

MIGID = "2026-09-17.uuid-client-columns-v1"
KASR_PARTIYA = ("'{nom}': partiya miqdori {q} da uchtadan ORTIQ kasr xonasi bor — miqdor "
                "0.001 aniqligida beriladi. Miqdor jimgina yaxlitlanmaydi.")


def _product(client, admin_headers, stock):
    nm = f"5C review {uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/products/bulk", headers=admin_headers, json={
        "items": [{"name": nm, "sell_price": 1000, "buy_price": 700,
                   "unit_code": "dona", "stock": stock}]})
    assert r.status_code in (200, 201), r.text
    return r.json()[0]["id"], nm


# ══ D-2 · OCHILISH PARTIYASI: ANIQLIK VA YAXLITLASH KIRIM BILAN AYNI ═════════

def test_ochilish_partiyasi_UCHTADAN_ORTIQ_kasrda_ANIQ_400_beradi(client, admin_headers, ctx):
    """ESKI kodda: darvoza (half-even) O'TKAZARDI -> partiya 1.235, qoldiq 1.234 ->
    invariant 409 «qo'llab-quvvatlashga murojaat qiling». Endi: ANIQ 400."""
    pid, nom = _product(client, admin_headers, 1.234)
    r = _enable(client, admin_headers, pid,
                opening_lots=[{"qty": 1.2345, "unit_cost": 700}])
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == KASR_PARTIYA.format(nom=nom, q="1.2345"), r.text
    # QAYTARIB BO'LMAYDIGAN amal BAJARILMADI: bayroq ham, partiya ham yo'q.
    assert _lots(pid) == []
    assert client.get(f"/api/v1/products/{pid}", headers=admin_headers).json()["track_lots"] is False


def test_ochilish_partiyasi_ANIQ_miqdorda_ISHLAYDI_nazorat(client, admin_headers, ctx):
    pid, _nom = _product(client, admin_headers, 1.234)
    r = _enable(client, admin_headers, pid,
                opening_lots=[{"qty": 1.234, "unit_cost": 700}])
    assert r.status_code == 200, r.text
    lots = _lots(pid)
    assert len(lots) == 1 and Decimal(str(lots[0].remaining_qty)) == Decimal("1.234")


def test_ochilish_partiyalari_yigindisi_teng_emas_400_nazorat(client, admin_headers, ctx):
    pid, _nom = _product(client, admin_headers, 2)
    r = _enable(client, admin_headers, pid,
                opening_lots=[{"qty": 1, "unit_cost": 700}])
    assert r.status_code == 400, r.text
    assert "TENG EMAS" in r.json()["detail"], r.text
    assert _lots(pid) == []


# ══ D-3 · OCHILISH PARTIYALARI SONI ══════════════════════════════════════════

def test_ochilish_partiyalari_soni_KIRIM_bilan_ayni_cheklangan(client, admin_headers, ctx):
    pid, _nom = _product(client, admin_headers, 51)
    r = _enable(client, admin_headers, pid,
                opening_lots=[{"qty": 1, "unit_cost": 700} for _ in range(51)])
    assert r.status_code == 422, r.text
    assert _lots(pid) == []
    # NAZORAT: chegaraning O'ZI (50) pydantic'da yiqilmaydi.
    pid2, _n2 = _product(client, admin_headers, 50)
    r2 = _enable(client, admin_headers, pid2,
                 opening_lots=[{"qty": 1, "unit_cost": 700} for _ in range(50)])
    assert r2.status_code == 200, r2.text
    assert len(_lots(pid2)) == 50


# ══ T-1 · BIZNES SANASI — YOZUVCHINING FILIALIDAN ════════════════════════════

def test_partiya_royxati_va_biznes_sanasi_YOZUVCHI_filialidan_olinadi(client, admin_headers, ctx):
    """Do'konning BIRINCHI filiali (nofaol bo'lsa ham) emas, `deps.actor_branch`.

    ⚠️  VAQTGA BOG'LIQ EMAS. Ikki zona AYNI sanani berishi mumkin (jadvaldagi
        farq eng ko'pi 4 soat), shu bois asosiy dalil — QAYSI filial partiyalari
        ko'rinishi; sana esa o'sha filialning sanasiga TENGligi bilan mixlanadi.
    """
    import uuid as _uuid
    from datetime import datetime, timezone as _tz
    from decimal import Decimal as _D

    from app.models.inventory import StockBatch
    from app.models.org import Branch
    cid, bid = ctx
    with _db() as db:
        birinchi = (db.query(Branch).filter(Branch.company_id == cid, Branch.deleted_at.is_(None))
                    .order_by(Branch.created_at).first())
        saqlangan = (birinchi.id, birinchi.timezone, birinchi.is_active, bid,
                     db.get(Branch, bid).timezone)
    qoshildi = None
    try:
        with _db() as db:
            b1 = db.get(Branch, saqlangan[0])
            b2 = db.get(Branch, saqlangan[3])
            if b1.id == b2.id:                      # bitta filial — yozuvchisini QO'SHAMIZ
                b2 = Branch(id=_uuid.uuid4(), company_id=cid, code=f"5c{_uuid.uuid4().hex[:6]}",
                            name="5C yozuvchi filial", timezone="Asia/Novosibirsk", is_active=True)
                db.add(b2)
                db.flush()
                from app.models.auth import Employee, EmployeeBranch
                emp = (db.query(Employee).filter(Employee.company_id == cid,
                                                 Employee.deleted_at.is_(None))
                       .order_by(Employee.created_at).first())
                db.add(EmployeeBranch(employee_id=emp.id, branch_id=b2.id))
            b1.timezone, b1.is_active = "Europe/Moscow", False   # `_branch(None)` BUNI tanlardi
            b2.timezone, b2.is_active = "Asia/Novosibirsk", True
            db.commit()
            yozuvchi_bid, eski_bid = b2.id, b1.id
            qoshildi = b2.id if b2.id not in (saqlangan[0], saqlangan[3]) else None
        pid, _nom = _product(client, admin_headers, 0)
        assert _enable(client, admin_headers, pid).status_code == 200
        _now = datetime.now(_tz.utc)
        with _db() as db:
            for b_, no in ((eski_bid, "5C-ESKI-FILIAL"), (yozuvchi_bid, "5C-YOZUVCHI")):
                db.add(StockBatch(id=_uuid.uuid4(), company_id=cid, product_id=_uuid.UUID(str(pid)),
                                  branch_id=b_, batch_no=no, received_qty=_D("1"),
                                  remaining_qty=_D("1"), qty=_D("1"), unit_cost=_D("100"),
                                  status="open", source_type="opening",
                                  received_at=_now, created_at=_now, updated_at=_now))
            db.commit()
        r = client.get(f"/api/v1/lots/products/{pid}", headers=admin_headers)
        assert r.status_code == 200, r.text
        nos = sorted(x["batch_number"] for x in r.json()["lots"])
        assert nos == ["5C-YOZUVCHI"], (nos, r.json())
        with _db() as db:
            assert r.json()["business_date"] == LP.business_date(db, yozuvchi_bid).isoformat()
        # ANIQ so'ralgan filial esa HAMON hurmat qilinadi (IDOR darvozasi o'z joyida).
        r2 = client.get(f"/api/v1/lots/products/{pid}?branch_id={eski_bid}", headers=admin_headers)
        assert r2.status_code in (200, 404), r2.text
        if r2.status_code == 200:
            assert sorted(x["batch_number"] for x in r2.json()["lots"]) == ["5C-ESKI-FILIAL"], r2.json()
    finally:
        with _db() as db:
            b1 = db.get(Branch, saqlangan[0])
            b1.timezone, b1.is_active = saqlangan[1], saqlangan[2]
            db.get(Branch, saqlangan[3]).timezone = saqlangan[4]
            db.query(StockBatch).filter(StockBatch.batch_no.in_(
                ["5C-ESKI-FILIAL", "5C-YOZUVCHI"])).delete(synchronize_session=False)
            # ⚠️  Seed do'koni FILIALLARI o'zgarmasin (conftest qo'riqchisi): o'zimiz
            #     qo'shgan filialni va uning biriktirmasini O'CHIRAMIZ.
            if qoshildi is not None:
                from app.models.auth import EmployeeBranch as _EB
                from app.models.inventory import Inventory as _Inv
                db.query(_EB).filter(_EB.branch_id == qoshildi).delete(synchronize_session=False)
                db.query(StockBatch).filter(StockBatch.branch_id == qoshildi).delete(synchronize_session=False)
                db.query(_Inv).filter(_Inv.branch_id == qoshildi).delete(synchronize_session=False)
                db.flush()
                db.query(Branch).filter(Branch.id == qoshildi).delete(synchronize_session=False)
            db.commit()


# ══ R-2 · CLI CHEGARALARI HAR BUYRUQDA TEKSHIRILADI ═════════════════════════

def test_CLI_chegara_qiymati_preflight_va_verify_da_ham_tekshiriladi(capsys):
    from app.db.migrations import contract as C
    from app.tools import schema_migrate as SM
    for cmd in ("preflight", "verify"):
        for bad in ("0", "-1", "2147483648"):
            code = SM.main([cmd, "--migration", MIGID, "--statement-timeout-ms", bad])
            assert code == C.EXIT_USAGE, (cmd, bad, code)
            err = capsys.readouterr().err
            assert "--statement-timeout-ms yaroqsiz" in err, (cmd, bad, err)
    # NAZORAT: yaroqli qiymat usage darvozasida TO'XTAMAYDI (SQLite -> NOT_APPLICABLE).
    assert SM.main(["preflight", "--migration", MIGID, "--statement-timeout-ms", "1000"]) == C.EXIT_OK


# ══ S-1 · INTROSPEKSIYA ENGINE'DA HAM, CONNECTION'DA HAM ISHLASIN ═══════════
#  ⚠️  O'ZIM TOPDIM (5C staging smoke dry-run). `required_schema` tekshiruvlari
#      `bind.connect()` chaqirardi — `Connection` da bu AttributeError beradi va
#      har biri «o'qib bo'lmadi» soxta muammosiga aylanardi. Natija: ochiq
#      tranzaksiyaga bog'langan sessiyada `/lots/enable` HAR DOIM 409 va operatorga
#      YOLG'ON sabab («4 ta FK/cheklov tayyor emas»), holbuki sxema BUTUN.

def test_sxema_introspeksiyasi_CONNECTION_da_ham_ENGINE_bilan_AYNI(client, admin_headers, ctx):
    from app.core import required_schema as rs
    from app.services import lot_policy as _LP
    with _db() as db:
        eng = db.get_bind()
    kutilgan = (rs._fatal(eng), rs.soft_missing(eng), rs.missing(eng),
                rs.idempotency_missing(eng), rs.column_type_problems(eng),
                _LP.activation_readiness(eng))
    assert kutilgan[2] == [], kutilgan[2]          # nazorat: sxema BUTUN
    con = eng.connect()
    tx = con.begin()
    try:
        olingan = (rs._fatal(con), rs.soft_missing(con), rs.missing(con),
                   rs.idempotency_missing(con), rs.column_type_problems(con),
                   _LP.activation_readiness(con))
    finally:
        tx.rollback()
        con.close()
    assert olingan == kutilgan, (olingan, kutilgan)
    assert all(olingan[5].values()), olingan[5]
