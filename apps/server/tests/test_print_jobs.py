# -*- coding: utf-8 -*-
"""PHASE 5F — CHOP ETISH JURNALI (`POST/PATCH/GET /print-jobs`).

Isbotlanadi:
  · hayot sikli: PENDING/FAILED → istalgan, PRINTED → PRINTED (no-op), PRINTED → boshqa 409
    (`PRINT_JOB_FINAL`); `attempts` faqat o'sadi; `printed_at` birinchi PRINTED da;
  · ayni `id` qayta POST — holat o'tishi, `duplicate: true`, 200;
  · hujjatga BITTA asl chek: boshqa id bilan ikkinchi ORIGINAL — 409 `PRINT_ORIGINAL_EXISTS`;
  · nusxa raqami 1, 2, 3 … (takror POST raqamni o'zgartirmaydi);
  · noto'g'ri tana — 400 `PRINT_JOB_INVALID` (TEST — hujjat turi emas);
  · begona do'kon id'si — 404 (mavjudlik ochilmaydi); hujjatni o'qish qoidasi chek
    endpointlari bilan AYNI (`access.readable_*`);
  · jurnal sotuv/qaytarish/qoldiq/kassa/smena jadvallariga TEGMAYDI.
"""
import uuid

import pytest

from app.services.receipt import errors as E
from tests.test_lot_fefo_sale import _product
from tests.test_receipt_no_writes import _farq, iz
from tests.test_receipt_settings import _dokon
from tests.test_sales_read_permissions import _filial, _karta_sotuv, _qaytar, _qoldiq, _xodim

URL = "/api/v1/print-jobs"
INVALID = {"detail": E.PRINT_JOB_INVALID}
KEYS = {"id", "doc_type", "doc_id", "copy", "copy_no", "status", "attempts", "error", "printer",
        "transport", "created_at", "updated_at", "printed_at"}
_TEGILMAS = ("sales", "sale_items", "sale_payments", "returns", "return_items", "inventory",
             "stock_movements", "stock_batches", "shifts", "cash_movements", "doc_counters",
             "customers", "credit_transactions")


@pytest.fixture(scope="module")
def j(client):
    ega = _dokon(client, name="QA chop etish do'koni")
    H = ega["h"]
    a1, a2 = _filial(client, H, "PJ A1"), _filial(client, H, "PJ A2")
    x = {"ega": ega,
         "kassir@A1": _xodim(client, H, "kassir", filial=a1),
         "kassir2@A1": _xodim(client, H, "kassir", filial=a1),
         "kassir@A2": _xodim(client, H, "kassir", filial=a2),
         "kassir@A1-sotuvlar.view": _xodim(client, H, "kassir", filial=a1,
                                           override={"sotuvlar.view": False}),
         "menejer": _xodim(client, H, "menejer"),
         "omborchi": _xodim(client, H, "omborchi")}
    x["begona-ega"] = _dokon(client, plan="start", name="Begona chop do'koni")
    pid = _product(client, H)
    _qoldiq(pid, a1, 100)
    sale = _karta_sotuv(client, x["kassir@A1"]["h"], pid, qty=3)
    sale2 = _karta_sotuv(client, x["kassir@A1"]["h"], pid, qty=1)
    ret = _qaytar(client, x["kassir@A1"]["h"], sale["id"], pid)
    assert ret.status_code == 200, ret.text
    return {"x": x, "sale": sale["id"], "sale2": sale2["id"], "ret": ret.json()["id"]}


def _post(client, h, doc_id, copy="ORIGINAL", doc_type="SALE", jid=None, **kw):
    return client.post(URL, headers=h, json={"id": jid or str(uuid.uuid4()), "doc_type": doc_type,
                                             "doc_id": doc_id, "copy": copy, **kw})


def _patch(client, h, jid, **kw):
    return client.patch(f"{URL}/{jid}", headers=h, json=kw)


# ══ 1 · HAYOT SIKLI ══════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def asl(client, j):
    """`sale` ning ASL cheki (PENDING) — keyingi sinovlar shunga tayanadi."""
    jid = str(uuid.uuid4())
    r = _post(client, j["x"]["kassir@A1"]["h"], j["sale"], jid=jid)
    assert r.status_code == 201, r.text
    b = r.json()
    assert set(b) == KEYS | {"duplicate"}
    assert (b["id"], b["doc_id"], b["copy"], b["copy_no"], b["status"], b["attempts"],
            b["printed_at"], b["duplicate"]) == (jid, j["sale"], "ORIGINAL", 0, "PENDING", 0, None, False)
    return jid


def test_ASL_chek_HAYOT_SIKLI(client, j, asl):
    h = j["x"]["kassir@A1"]["h"]
    jid = asl
    d = _post(client, h, j["sale"], jid=jid)
    assert d.status_code == 200 and d.json()["duplicate"] is True and d.json()["id"] == jid
    r = _patch(client, h, jid, status="FAILED", error="Printer offline\x1b\x70\x00", attempts=1)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["error"], r.json()["attempts"]) == (
        "FAILED", "Printer offlinep", 1)
    r = _patch(client, h, jid, status="PENDING", attempts=0)            # eskirgan hisobot
    assert (r.json()["status"], r.json()["attempts"]) == ("PENDING", 1)
    r = _patch(client, h, jid, status="PRINTED", attempts=2, printer="XP-80C",
               transport="escpos_lan")
    b = r.json()
    assert (b["status"], b["attempts"], b["error"], b["printer"], b["transport"]) == (
        "PRINTED", 2, None, "XP-80C", "escpos_lan")
    assert b["printed_at"] is not None
    # PRINTED → PRINTED — hech narsa o'zgarmaydi (attempts ham, printed_at ham).
    r2 = _patch(client, h, jid, status="PRINTED", attempts=9, printer="boshqa")
    assert r2.status_code == 200 and r2.json() == b
    assert _patch(client, h, jid).json() == b
    for st in ("FAILED", "PENDING"):
        r = _patch(client, h, jid, status=st)
        assert r.status_code == 409 and r.json() == {"detail": E.PRINT_JOB_FINAL}, st
        assert r.headers.get("X-Error-Code") == "PRINT_JOB_FINAL"
    # Eskirgan takror POST (PENDING) ham yakuniy holatni buzmaydi.
    r = _post(client, h, j["sale"], jid=jid)
    assert r.status_code == 409 and r.headers.get("X-Error-Code") == "PRINT_JOB_FINAL"


def test_IKKINCHI_ASL_chek_409_nusxa_raqamlari_1_2_3(client, j, asl):
    h = j["x"]["kassir@A1"]["h"]
    before = iz(["print_jobs"])
    r = _post(client, h, j["sale"])
    assert r.status_code == 409 and r.json() == {"detail": E.PRINT_ORIGINAL_EXISTS}, r.text
    assert r.headers.get("X-Error-Code") == "PRINT_ORIGINAL_EXISTS"
    assert iz(["print_jobs"]) == before
    ids = [str(uuid.uuid4()) for _ in range(3)]
    got = [_post(client, h, j["sale"], copy="REPRINT", jid=i, status="PRINTED") for i in ids]
    assert [g.status_code for g in got] == [201] * 3
    assert [g.json()["copy_no"] for g in got] == [1, 2, 3]
    assert all(g.json()["printed_at"] for g in got)
    # Takror — ayni raqam.
    again = _post(client, h, j["sale"], copy="REPRINT", jid=ids[1], status="PRINTED")
    assert again.status_code == 200 and again.json()["copy_no"] == 2
    lst = client.get(URL, headers=h, params={"doc_type": "SALE", "doc_id": j["sale"]})
    assert lst.status_code == 200
    assert [(x["copy"], x["copy_no"]) for x in lst.json()] == [
        ("ORIGINAL", 0), ("REPRINT", 1), ("REPRINT", 2), ("REPRINT", 3)]
    assert all(set(x) == KEYS for x in lst.json())
    # Boshqa hujjat — o'z asl cheki (noyoblik hujjat bo'yicha).
    assert _post(client, h, j["sale2"]).status_code == 201


def test_QAYTARISH_hujjati_va_ruxsat(client, j):
    x = j["x"]
    r = _post(client, x["kassir@A1"]["h"], j["ret"], doc_type="RETURN")
    assert r.status_code == 201 and r.json()["doc_type"] == "RETURN", r.text
    # Boshqa kassir (faqat qaytarishlar.create) — BOSHQANING qaytarishi 404.
    r = _post(client, x["kassir2@A1"]["h"], j["ret"], doc_type="RETURN", copy="REPRINT")
    assert r.status_code == 404 and r.json() == {"detail": "Qaytarish topilmadi"}
    r = _post(client, x["menejer"]["h"], j["ret"], doc_type="RETURN", copy="REPRINT")
    assert r.status_code == 201 and r.json()["copy_no"] == 1
    lst = client.get(URL, headers=x["kassir2@A1"]["h"], params={"doc_type": "RETURN", "doc_id": j["ret"]})
    assert lst.status_code == 404


@pytest.mark.parametrize("rol,kod,detail", [
    ("kassir@A2", 404, "Chek topilmadi"),
    ("kassir@A1-sotuvlar.view", 404, "Chek topilmadi"),
    ("begona-ega", 404, "Chek topilmadi"),
    ("omborchi", 403, "Ruxsat yo'q: kassa.sell / sotuvlar.view / qaytarishlar.create / qaytarishlar.view"),
])
def test_HUJJATNI_oqiy_olmaydigan_xodim(client, j, rol, kod, detail):
    h = j["x"][rol]["h"]
    before = iz(["print_jobs"])
    r = _post(client, h, j["sale"], copy="REPRINT")
    assert r.status_code == kod and r.json() == {"detail": detail}, r.text
    r = client.get(URL, headers=h, params={"doc_type": "SALE", "doc_id": j["sale"]})
    assert r.status_code == kod and r.json() == {"detail": detail}
    assert iz(["print_jobs"]) == before


def test_BEGONA_dokon_mavjud_id_bilan_404_hech_narsa_ochilmaydi(client, j, asl):
    jid = asl
    bh = j["x"]["begona-ega"]["h"]
    r = _post(client, bh, j["sale"], jid=jid)
    assert r.status_code == 404 and r.json() == INVALID
    r = _patch(client, bh, jid, status="FAILED")
    assert r.status_code == 404 and r.json() == INVALID
    # Mavjud bo'lmagan id bilan AYNI javob — oracle yo'q.
    assert _patch(client, bh, str(uuid.uuid4()), status="FAILED").content == r.content
    assert _patch(client, j["x"]["ega"]["h"], "buzuq", status="FAILED").json() == INVALID
    # Ayni id, BOSHQA hujjat — mijoz xatosi (400).
    r = _post(client, j["x"]["kassir@A1"]["h"], j["sale2"], jid=jid)
    assert r.status_code == 400 and r.json() == INVALID


NOTOGRI = [
    None, [], {},
    {"doc_type": "TEST"}, {"doc_type": "sale"}, {"copy": "COPY"}, {"id": "x"}, {"doc_id": "x"},
    {"id": None}, {"status": "DONE"}, {"status": None}, {"attempts": -1}, {"attempts": "2"},
    {"attempts": True}, {"attempts": 1001}, {"transport": "bo'sh joy"}, {"transport": "x" * 25},
    {"error": 5}, {"printer": ["x"]},
]


@pytest.mark.parametrize("tuzat", NOTOGRI, ids=[repr(t)[:30] for t in NOTOGRI])
def test_NOTOGRI_tana_400_kod(client, j, tuzat):
    h = j["x"]["kassir@A1"]["h"]
    if isinstance(tuzat, dict):
        body = {"id": str(uuid.uuid4()), "doc_type": "SALE", "doc_id": j["sale2"], "copy": "REPRINT"}
        body.update(tuzat)
        if tuzat == {}:
            body = {}
    else:
        body = tuzat
    r = client.post(URL, headers=h, json=body)
    assert r.status_code == 400 and r.json() == INVALID, r.text
    assert r.headers.get("X-Error-Code") == "PRINT_JOB_INVALID"


def test_PATCH_notogri_tana_va_GET_parametrlar(client, j, asl):
    h = j["x"]["kassir@A1"]["h"]
    for body in ([], {"status": "X"}, {"attempts": -5}, {"transport": "a b"}):
        r = client.patch(f"{URL}/{asl}", headers=h, json=body)
        assert r.status_code == 400 and r.headers.get("X-Error-Code") == "PRINT_JOB_INVALID", body
    for params in ({}, {"doc_type": "TEST", "doc_id": j["sale"]}, {"doc_type": "SALE", "doc_id": "x"}):
        r = client.get(URL, headers=h, params=params)
        assert r.status_code == 400 and r.json() == INVALID, params
    r = client.get(URL, headers=h, params={"doc_type": "SALE", "doc_id": str(uuid.uuid4())})
    assert r.status_code == 404 and r.json() == {"detail": "Chek topilmadi"}


def test_JURNAL_sotuv_qoldiq_kassa_jadvallariga_TEGMAYDI(client, j):
    h = j["x"]["kassir@A1"]["h"]
    oldin = iz(_TEGILMAS)
    jid = str(uuid.uuid4())
    assert _post(client, h, j["sale2"], copy="REPRINT", jid=jid).status_code == 201
    assert _patch(client, h, jid, status="FAILED", error="qog'oz tugadi", attempts=1).status_code == 200
    assert _patch(client, h, jid, status="PRINTED", attempts=2).status_code == 200
    assert _post(client, h, j["ret"], doc_type="RETURN", copy="REPRINT").status_code == 201
    assert _farq(oldin, iz(_TEGILMAS)) == {}
