# -*- coding: utf-8 -*-
"""`POST /historical/events` — SEMANTIKA: `at` uzatilishi, suppression, xronologiya.

Uch shartnoma qoplanadi:
 1. HAR BIR hodisa KANONIK yozuvchiga `at=occurred_at` bilan boradi (bypass yo'q);
 2. tashqi effektlar kontekst ichida TO'SILADI — va nazorat sahnasi ularning
    kontekstdan TASHQARIDA ishlashini isbotlaydi (aks holda test bo'sh bo'lardi);
 3. mutlaq yozuvchining (inventarizatsiya) xronologiya gardi SAQLANADI.
"""
import uuid
from datetime import timedelta, timezone

import pytest

from tests._hist_scene import D0, db_, env, post, sahna, smena_ochish


# ══ 1. `at` UZATILISHI — HAR 12 HODISA UCHUN ════════════════════════════
#  ⚠️  BU TO'PLAMDAGI ENG KUCHLI TEST. U ikki narsani birga isbotlaydi:
#      (a) bypass yo'q — AYNAN kanonik yozuvchi chaqiriladi;
#      (b) tarixiy lahza unga YETIB BORADI (`at=` kalit-so'zi bilan).
#      Yozuvchi JOSUS bilan almashtiriladi, shu bois biznes shartlari (qoldiq,
#      qarz, ochiq smena) kerak emas — maqsad chaqiruv SHARTNOMASI.

_JOSUS_PAYLOAD = {
    "shift_open": {"opening_cash": 1000},
    "shift_close": {"shift_id": "11111111-1111-1111-1111-111111111111",
                    "counted_cash": 1000},
    "sale": {"items": [], "payments": []},
    "purchase": {"items": [], "supplier_id": "11111111-1111-1111-1111-111111111111"},
    "receiving": {"items": []},
    "return": {"original_sale_id": "11111111-1111-1111-1111-111111111111",
               "items": []},
    "inventory_count": {"items": []},
    "writeoff": {"product_id": "11111111-1111-1111-1111-111111111111",
                 "qty": 1, "reason": "brak"},
    "cash_payin": {"type": "payin", "amount": 100},
    "cash_expense": {"type": "expense", "amount": 100, "reason": "x"},
    "customer_debt_payment": {"customer_id": "11111111-1111-1111-1111-111111111111",
                              "amount": 100},
    "supplier_payment": {"supplier_id": "11111111-1111-1111-1111-111111111111",
                         "amount": 100},
}

#: hodisa -> (almashtiriladigan modul yo'li, funksiya nomi)
_YOZUVCHI = {
    "shift_open": ("app.api.v1.historical_exec", "open_shift_svc"),
    "shift_close": ("app.api.v1.historical_exec", "close_shift_svc"),
    "sale": ("app.services.sales", "create_sale"),
    "purchase": ("app.api.v1.historical_exec", "_create_purchase_once"),
    "receiving": ("app.api.v1.historical_exec", "_commit_once"),
    "return": ("app.api.v1.historical_exec", "_create_return_once"),
    "inventory_count": ("app.api.v1.historical_exec", "_stock_count_once"),
    "writeoff": ("app.api.v1.historical_exec", "_writeoff_once"),
    "cash_payin": ("app.api.v1.historical_exec", "_cash_op_once"),
    "cash_expense": ("app.api.v1.historical_exec", "_cash_op_once"),
    "customer_debt_payment": ("app.api.v1.historical_exec", "_pay_credit_once"),
    "supplier_payment": ("app.api.v1.historical_exec", "_pay_supplier_once"),
}


class _SoxtaSotuv:
    """`create_sale` ORM obyekti qaytaradi — dispatch `.id` ni o'qiydi."""
    def __init__(self):
        self.id = uuid.uuid4()
        self.receipt_no = "X-1"
        self.total = 0


@pytest.mark.parametrize("turi", sorted(_JOSUS_PAYLOAD))
def test_KANONIK_yozuvchi_at_bilan_CHAQIRILADI(client, monkeypatch, turi):
    import importlib
    chaqiruvlar = []
    mod_yoli, fn_nomi = _YOZUVCHI[turi]
    mod = importlib.import_module(mod_yoli)

    def _josus(*a, **kw):
        chaqiruvlar.append((a, kw))
        if turi == "sale":
            return _SoxtaSotuv()
        if turi == "purchase":
            class _P:
                id = uuid.uuid4()
            return _P()
        if turi in ("shift_open", "shift_close"):
            return {"id": str(uuid.uuid4())}
        if turi == "return":
            return {"id": str(uuid.uuid4())}
        if turi == "receiving":
            return {"ok": True, "receiving_id": str(uuid.uuid4())}
        return {"ok": True}

    monkeypatch.setattr(mod, fn_nomi, _josus)
    s = sahna()
    r = post(client, env(s, event_type=turi, payload=_JOSUS_PAYLOAD[turi],
                         at=D0 + timedelta(hours=4)))
    assert r.status_code == 200, r.text
    assert len(chaqiruvlar) == 1, f"yozuvchi {len(chaqiruvlar)} marta chaqirildi"
    _a, kw = chaqiruvlar[0]
    assert "at" in kw, f"{turi}: `at` UZATILMAGAN — tarixiy lahza yo'qoladi"
    kutilgan = (D0 + timedelta(hours=4)).astimezone(timezone.utc)
    assert kw["at"] == kutilgan, f"{turi}: at={kw['at']}, kutilgan={kutilgan}"


def test_SHIFT_OPEN_ga_client_uuid_SERVER_tomonidan_uzatiladi(client, monkeypatch):
    """⚠️  `shift_open` kaliti DTO'da YO'Q — u kalit-so'zli SERVIS parametri.

    Shu bois boshqa hodisalardan farqli, uni `model_copy` bilan payloadga
    qo'yib bo'lmaydi: dispatch uni ALOHIDA uzatishi shart. Bu test shuni
    qadaydi, aks holda `shifts.client_uuid` bo'sh qolib tiklanish zondi
    ishlamasdi.
    """
    import app.api.v1.historical_exec as HX
    from app.services.historical import event_key
    tutilgan = {}

    def _josus(data, emp, db, *, at=None, client_uuid=None):
        tutilgan["client_uuid"] = client_uuid
        return {"id": str(uuid.uuid4())}

    monkeypatch.setattr(HX, "open_shift_svc", _josus)
    s = sahna()
    seq = ["d1", "open"]
    assert post(client, env(s, event_type="shift_open",
                            payload={"opening_cash": 0},
                            seq=seq)).status_code == 200
    assert tutilgan["client_uuid"] == event_key(
        uuid.UUID(s["cid"]), s["plan"], *seq), tutilgan


def test_NAIVE_occurred_at_UTC_ga_keltiriladi(client):
    from app.models.shifts import Shift
    s = sahna()
    naive = (D0 + timedelta(hours=5)).replace(tzinfo=None)
    e = env(s, event_type="shift_open", payload={"opening_cash": 0})
    e["occurred_at"] = naive.isoformat()          # mintaqasiz
    r = post(client, e)
    assert r.status_code == 200, r.text
    with db_() as db:
        sh = db.get(Shift, uuid.UUID(r.json()["result_id"]))
        got = sh.opened_at if sh.opened_at.tzinfo else sh.opened_at.replace(
            tzinfo=timezone.utc)
        assert got == naive.replace(tzinfo=timezone.utc)


def test_KONTEKST_sorovdan_keyin_OQIB_KETMAYDI(client, monkeypatch):
    """`historical.active()` — so'rovdan keyin `None`, XATO bo'lsa HAM.

    ⚠️  NEGA MUHIM. Kontekst oqib ketsa, KEYINGI so'rov — oddiy POS sotuvi —
        tarixiy rejimda bajarilardi: tashqi effektlar to'silib, vaqt
        boshqasidan olinardi. Bu jim va eng yomon turdagi buzilish.
    """
    import app.api.v1.historical_exec as HX
    from app.services import historical as H
    s = sahna()
    assert post(client, env(s, event_type="shift_open",
                            payload={"opening_cash": 0})).status_code == 200
    assert H.active() is None, "kontekst MUVAFFAQIYATDAN keyin oqib ketdi"

    #  (a) BAJARUVCHI SHARTNOMASI xatosi -> 409 (tarixiy qatlam `RuntimeError`
    #      ko'taradi, endpoint uni diagnoz beradigan javobga aylantiradi).
    monkeypatch.setattr(HX, "_dispatch_retry",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            RuntimeError("ATAYLAB SHARTNOMA")))
    r = post(client, env(s, event_type="shift_open",
                         payload={"opening_cash": 0}, seq=["x2"]))
    assert r.status_code == 409 and "ATAYLAB SHARTNOMA" in r.text, r.text
    assert H.active() is None, "kontekst 409 yo'lidan keyin oqib ketdi"

    #  (b) KUTILMAGAN istisno -> yuqoriga chiqadi (yashirilmaydi), lekin
    #      kontekst baribir TOZALANADI (`enter` ning `try/finally` si).
    monkeypatch.setattr(HX, "_dispatch_retry",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            ValueError("ATAYLAB KUTILMAGAN")))
    with pytest.raises(ValueError, match="ATAYLAB KUTILMAGAN"):
        post(client, env(s, event_type="shift_open",
                         payload={"opening_cash": 0}, seq=["x3"]))
    assert H.active() is None, "kontekst KUTILMAGAN xatodan keyin oqib ketdi"


# ══ 2. TASHQI EFFEKTLAR — QUROLLANGAN NOL-EGRESS ════════════════════════

@pytest.fixture
def push_josusi(monkeypatch):
    """`push.send_ex` ni GARDDAN PASTDA tutadi.

    ⚠️  PASTDA tutish SHART: gard `notify_low_stock` ichida (`push.py:74-76`),
        shu bois `send_ex` ni almashtirish gardni O'CHIRSA testni QIZIL qiladi.
        Yuqorida tutilsa test gardni umuman o'lchamasdi.
    """
    from app.services import push
    yuborilgan: list = []
    monkeypatch.setattr(push, "send_ex",
                        lambda *a, **k: (yuborilgan.append(a), (0, []))[1])

    class _S:
        fcm_enabled = True
    monkeypatch.setattr(push, "settings", _S())
    return yuborilgan


def _qurollantir(s, min_qty=50):
    """Past-qoldiq chegarasini KO'TARAMIZ — sotuv/chiqarish uni KESIB o'tsin.

    Qurollantirmasak push shoxi umuman ishlamasdi va «nol egress» testi BO'SH
    bo'lardi.
    """
    from app.models.inventory import Inventory
    with db_() as db:
        inv = (db.query(Inventory)
               .filter(Inventory.product_id == uuid.UUID(s["pid"]),
                       Inventory.branch_id == uuid.UUID(s["a"])).one())
        inv.min_qty = min_qty
        db.commit()


@pytest.mark.parametrize("turi", ["sale", "writeoff", "inventory_count"])
def test_TASHQI_EFFEKT_kontekst_ichida_TOSILADI(client, push_josusi, turi):
    s = sahna()
    _qurollantir(s)
    smena_ochish(client, s, opening=5000)
    payload = {
        "sale": {"items": [{"product_id": s["pid"], "qty": 40, "price": 100}],
                 "payments": [{"method": "cash", "amount": 4000}]},
        "writeoff": {"product_id": s["pid"], "qty": 45, "reason": "brak",
                     "branch_id": s["a"]},
        "inventory_count": {"branch_id": s["a"],
                            "items": [{"product_id": s["pid"], "counted": 1}]},
    }[turi]
    r = post(client, env(s, event_type=turi, at=D0 + timedelta(hours=2),
                         payload=payload))
    assert r.status_code == 200, r.text
    assert push_josusi == [], (
        f"{turi}: tarixiy kontekst ichida FCM yuborildi — suppression buzilgan")


def test_NAZORAT_kontekstdan_TASHQARIDA_push_ISHLAYDI(client, push_josusi,
                                                      admin_headers):
    """⚠️  BU TESTSIZ YUQORIDAGILAR BO'SH.

    Agar past-qoldiq shoxi umuman ishlamasa (chegara noto'g'ri, qurilma
    token'i yo'q, boshqa sabab), «nol egress» testi hech narsa isbotlamasdi.
    Shu yerda AYNI mexanizm kontekstdan TASHQARIDA ishga tushadi.
    """
    from app.models.devices import DeviceToken
    from app.models.org import Branch
    #  Seed do'koni (oddiy POS yo'li) uchun qurilma token'i kerak.
    with db_() as db:
        br = db.query(Branch).order_by(Branch.created_at).first()
        db.add(DeviceToken(id=uuid.uuid4(), company_id=br.company_id,
                           token="d3-test-" + uuid.uuid4().hex[:8],
                           platform="android"))
        db.commit()
    from app.services import push
    push.notify_low_stock(_sessiya(), br.company_id, [("Tovar", 0.0)])
    assert push_josusi, (
        "kontekstdan TASHQARIDA ham push ishlamadi — yuqoridagi nol-egress "
        "testlari BO'SH bo'lar edi")


def _sessiya():
    from app.db.session import SessionLocal
    return SessionLocal()


def test_SUPPRESSION_voronkasi_YAGONA(client):
    """`push.send*` ning app-ichki chaqiruvchilari — faqat ikki joy.

    ⚠️  NEGA. Gard `notify_low_stock` ICHIDA. Agar kelajakda yozuvchi FCM'ni
        to'g'ridan chaqirsa, u gardni CHETLAB o'tardi va suppression bayonoti
        jimgina yolg'on bo'lardi.
    """
    import pathlib
    import re
    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    naqsh = re.compile(r"(?<![\w.])push\.send(?:_ex)?\s*\(")
    topilgan = set()
    for f in app_dir.rglob("*.py"):
        if naqsh.search(f.read_text(encoding="utf-8")):
            topilgan.add(f.relative_to(app_dir).as_posix())
    topilgan.discard("services/push.py")          # ta'rifning o'zi
    assert topilgan <= {"api/v1/devices.py"}, (
        f"`push.send*` yangi joydan chaqirilgan: {topilgan} — suppression "
        f"voronkasi endi YAGONA emas")


# ══ 3. XRONOLOGIYA GARDI — MUTLAQ YOZUVCHI ══════════════════════════════

def test_TARTIBSIZ_SANOQ_rad_va_HECH_NARSA_yozilmaydi(client):
    """Sanoq MUTLAQ yozuvchi: tartibsiz replay qoldiqni BUZARDI.

    ⚠️  Gard `MAX(stock_movements.created_at) > at` ga tayanadi va MUTATSIYADAN
        OLDIN ishlaydi (fail-closed).
    """
    from app.models.inventory import Inventory, StockMovement
    s = sahna()
    smena_ochish(client, s, opening=0)
    #  D+2 da sanoq.
    r1 = post(client, env(s, event_type="inventory_count",
                          at=D0 + timedelta(days=2), seq=["c1"],
                          payload={"branch_id": s["a"],
                                   "items": [{"product_id": s["pid"],
                                              "counted": 45}]}))
    assert r1.status_code == 200, r1.text
    with db_() as db:
        qoldiq = db.query(Inventory).filter(
            Inventory.product_id == uuid.UUID(s["pid"]),
            Inventory.branch_id == uuid.UUID(s["a"])).one().qty
        harakat = db.query(StockMovement.id).filter(
            StockMovement.branch_id == uuid.UUID(s["a"])).count()

    #  ...keyin D+1 da (ORQADA) sanoq — RAD etilishi shart.
    r2 = post(client, env(s, event_type="inventory_count",
                          at=D0 + timedelta(days=1), seq=["c2"],
                          payload={"branch_id": s["a"],
                                   "items": [{"product_id": s["pid"],
                                              "counted": 10}]}))
    assert r2.status_code == 409, f"tartibsiz sanoq: {r2.status_code} {r2.text[:200]}"
    #  Xabar AYNAN saqlanishi SHART — unda bajaruvchi nima qilishi yozilgan.
    assert "TARTIBSIZ" in r2.text and "GLOBAL tartiblang" in r2.text, r2.text
    with db_() as db:
        assert db.query(Inventory).filter(
            Inventory.product_id == uuid.UUID(s["pid"]),
            Inventory.branch_id == uuid.UUID(s["a"])).one().qty == qoldiq, (
            "RAD ETILGAN sanoq qoldiqni O'ZGARTIRDI")
        assert db.query(StockMovement.id).filter(
            StockMovement.branch_id == uuid.UUID(s["a"])).count() == harakat, (
            "RAD ETILGAN sanoq harakat yozdi")


def test_TENGLIK_holati_QABUL_qilinadi(client):
    """Aynan `MAX(created_at)` paytidagi sanoq O'TADI — qat'iy `>` ataylab."""
    from app.models.inventory import StockMovement
    s = sahna()
    smena_ochish(client, s, opening=0)
    t = D0 + timedelta(days=2)
    assert post(client, env(s, event_type="inventory_count", at=t, seq=["c1"],
                            payload={"branch_id": s["a"],
                                     "items": [{"product_id": s["pid"],
                                                "counted": 45}]})).status_code == 200
    with db_() as db:
        mx = max(m.created_at for m in db.query(StockMovement).filter(
            StockMovement.branch_id == uuid.UUID(s["a"])).all())
    mx = mx if mx.tzinfo else mx.replace(tzinfo=timezone.utc)
    r = post(client, env(s, event_type="inventory_count", at=mx, seq=["c2"],
                         payload={"branch_id": s["a"],
                                  "items": [{"product_id": s["pid"],
                                             "counted": 44}]}))
    assert r.status_code == 200, (
        f"tenglik holati RAD etildi — qat'iy `>` buzilgan: {r.text[:200]}")
