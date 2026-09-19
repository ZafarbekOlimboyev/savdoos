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
    endpointlari bilan AYNI (`access.readable_*`) — mavjud yozuvni PATCH va ayni id bilan
    takror POST ham shu qoidadan o'tadi; tarixsiz (`kassa.sell`) kassir — faqat O'Z sotuvi;
  · jurnal sotuv/qaytarish/qoldiq/kassa/smena jadvallariga TEGMAYDI;
  · ASL chek BANDI (`claim_token`): boshqa tokenning tirik bandi ustiga PENDING/FAILED/
    boshqa o'zgarish — 409 `PRINT_JOB_BUSY`, PRINTED — har kimdan; FAILED, tokensiz PENDING,
    ayni token va `LEASE_SECONDS` dan eski band — olinadi; tokensiz so'rov — eski xatti-harakat;
    javobda `claimed_at` bor, token YO'Q.
"""
import uuid

import pytest

from app.services.receipt import errors as E
from tests.test_lot_fefo_sale import _product
from tests.test_receipt_no_writes import _farq, iz
from tests.test_receipt_settings import _dokon
from tests.test_sales_read_permissions import _db, _filial, _karta_sotuv, _qaytar, _qoldiq, _xodim

URL = "/api/v1/print-jobs"
INVALID = {"detail": E.PRINT_JOB_INVALID}
KEYS = {"id", "doc_type", "doc_id", "copy", "copy_no", "status", "attempts", "error", "printer",
        "transport", "created_at", "updated_at", "printed_at", "claimed_at"}
BUSY = {"detail": E.PRINT_JOB_BUSY}
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
    return {"x": x, "sale": sale["id"], "sale2": sale2["id"], "ret": ret.json()["id"], "pid": pid}


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


def test_TARIXSIZ_kassir_OZ_sotuvi_jurnali_ISHLAYDI_boshqaniki_404(client, j):
    """`sotuvlar.view` o'chirilgan kassir (faqat `kassa.sell`) — O'Z sotuvi uchun jurnal
    (POST/PATCH/GET) ishlaydi; boshqa kassir sotuvi va uning yozuvi — 404."""
    x = j["x"]
    h = x["kassir@A1-sotuvlar.view"]["h"]
    own = _karta_sotuv(client, h, j["pid"], qty=1)["id"]
    jid = str(uuid.uuid4())
    r = _post(client, h, own, jid=jid)
    assert r.status_code == 201 and r.json()["copy_no"] == 0, r.text
    r = _patch(client, h, jid, status="PRINTED", attempts=1)
    assert r.status_code == 200 and r.json()["status"] == "PRINTED", r.text
    assert _post(client, h, own, copy="REPRINT").json()["copy_no"] == 1
    lst = client.get(URL, headers=h, params={"doc_type": "SALE", "doc_id": own})
    assert lst.status_code == 200 and [it["copy"] for it in lst.json()] == ["ORIGINAL", "REPRINT"]
    # Boshqa kassirning sotuvi (va uning jurnal yozuvi) — 404.
    other = str(uuid.uuid4())
    r = _post(client, x["kassir@A1"]["h"], j["sale2"], copy="REPRINT", jid=other)
    assert r.status_code == 201, r.text
    before = iz(["print_jobs"])
    for resp in (_post(client, h, j["sale2"], copy="REPRINT"),
                 _post(client, h, j["sale2"], copy="REPRINT", jid=other),
                 _patch(client, h, other, status="FAILED"),
                 client.get(URL, headers=h, params={"doc_type": "SALE", "doc_id": j["sale2"]})):
        assert resp.status_code == 404 and resp.json() == {"detail": "Chek topilmadi"}, resp.text
    assert iz(["print_jobs"]) == before


def _oqib_bolmaydi(client, h, jid, doc_id, doc_type, detail, egasi_h):
    """PATCH va ayni id bilan takror POST — 404, jurnal O'ZGARMAYDI (egasi ham ko'radi)."""
    before = iz(["print_jobs"])
    ko = client.get(URL, headers=egasi_h, params={"doc_type": doc_type, "doc_id": doc_id}).json()
    for resp in (_patch(client, h, jid, status="FAILED", error="buzildi", printer="X", attempts=7),
                 _patch(client, h, jid, status="PRINTED"),
                 _post(client, h, doc_id, copy="REPRINT", doc_type=doc_type, jid=jid,
                       status="PRINTED")):
        assert resp.status_code == 404 and resp.json() == {"detail": detail}, resp.text
    assert iz(["print_jobs"]) == before
    assert client.get(URL, headers=egasi_h,
                      params={"doc_type": doc_type, "doc_id": doc_id}).json() == ko


def test_OQIY_OLMAYDIGAN_xodim_mavjud_yozuvni_PATCH_va_TAKROR_POST_qila_olmaydi(client, j):
    """Hujjatni o'qish qoidasi jurnal yozuvining O'ZGARISHIDA ham (PATCH, ayni id POST):
    boshqa filial kassiri, tarixsiz kassir va boshqa kassirning qaytarishi — 404."""
    x = j["x"]
    k1 = x["kassir@A1"]["h"]
    sjid = str(uuid.uuid4())
    r = _post(client, k1, j["sale2"], copy="REPRINT", jid=sjid)
    assert r.status_code == 201 and r.json()["status"] == "PENDING", r.text
    for rol in ("kassir@A2", "kassir@A1-sotuvlar.view"):
        _oqib_bolmaydi(client, x[rol]["h"], sjid, j["sale2"], "SALE", "Chek topilmadi", k1)
    rjid = str(uuid.uuid4())
    r = _post(client, k1, j["ret"], copy="REPRINT", doc_type="RETURN", jid=rjid)
    assert r.status_code == 201, r.text
    _oqib_bolmaydi(client, x["kassir2@A1"]["h"], rjid, j["ret"], "RETURN", "Qaytarish topilmadi",
                   k1)
    # Egasi uchun hamon PENDING va o'zgartirilmagan.
    b = _patch(client, k1, sjid).json()
    assert (b["status"], b["printer"], b["attempts"], b["error"]) == ("PENDING", None, 0, None)


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
    {"transport": "escpos_lan\n"},
    {"error": 5}, {"printer": ["x"]},
    {"claim_token": None}, {"claim_token": ""}, {"claim_token": "x" * 65}, {"claim_token": "a b"},
    {"claim_token": "tok\n"}, {"claim_token": "tok.1"}, {"claim_token": 7}, {"claim_token": ["t"]},
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
    for body in ([], {"status": "X"}, {"attempts": -5}, {"transport": "a b"},
                 {"status": "PENDING", "claim_token": "tok\n"}, {"claim_token": None},
                 {"status": "PENDING", "claim_token": "y" * 65}):
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


# ══ 2 · ASL CHEK BANDI (claim_token, lease) ═══════════════════════════════════
def _yangi_sotuv(client, j):
    """Band sinovlari uchun ALOHIDA sotuv: hujjatga bitta asl chek, sinovlar bir-birini buzmasin."""
    return _karta_sotuv(client, j["x"]["kassir@A1"]["h"], j["pid"], qty=1)["id"]


def _eskirt(jid, sekund):
    """Vaqtni muzlatish o'rniga: bandni `sekund` oldin olingan qilib qo'yadi."""
    from datetime import datetime, timedelta, timezone

    from app.models.receipt import PrintJob
    with _db() as db:
        job = db.get(PrintJob, uuid.UUID(jid))
        job.claimed_at = datetime.now(timezone.utc) - timedelta(seconds=sekund)
        db.commit()


def _band(jid):
    from app.models.receipt import PrintJob
    with _db() as db:
        job = db.get(PrintJob, uuid.UUID(jid))
        return job.status, job.claim_token


def _t(iso):
    from datetime import datetime
    return datetime.fromisoformat(iso)


def _busy(r):
    assert r.status_code == 409 and r.json() == BUSY, r.text
    assert r.headers.get("X-Error-Code") == "PRINT_JOB_BUSY"


def test_BAND_boshqa_qurilma_PENDING_FAILED_bilan_BUZOLMAYDI_PRINTED_har_kimdan(client, j):
    """R0: Manager FAILED asl chekni oldi (band), uning PRINTED hisoboti yo'qoldi — POS
    «Qayta urinish» ayni id'ni band qilolmaydi (409 BUSY → NUSXA), qator o'zgarmaydi."""
    kassa, men = j["x"]["kassir@A1"]["h"], j["x"]["menejer"]["h"]
    sid, jid = _yangi_sotuv(client, j), str(uuid.uuid4())
    r = _post(client, kassa, sid, jid=jid, claim_token="pos-1")                 # POS avto-chop
    assert r.status_code == 201 and r.json()["claimed_at"] is not None, r.text
    assert _patch(client, kassa, jid, status="FAILED", error="PAPER_OUT", attempts=1,
                  claim_token="pos-1").status_code == 200
    r = _patch(client, men, jid, status="PENDING", attempts=1, claim_token="mgr-1")  # Manager oladi
    assert r.status_code == 200 and r.json()["status"] == "PENDING", r.text
    band = r.json()["claimed_at"]
    # Manager chop etmoqda / PRINTED hisoboti yo'qoldi — POS ning hech bir yozuvi o'tmaydi.
    before = iz(["print_jobs"])
    for resp in (_patch(client, kassa, jid, status="PENDING", attempts=2, claim_token="pos-1"),
                 _post(client, kassa, sid, jid=jid, claim_token="pos-1"),
                 _patch(client, kassa, jid, status="FAILED", error="x", claim_token="pos-1"),
                 _patch(client, kassa, jid, attempts=5, printer="POS", claim_token="pos-1")):
        _busy(resp)
    assert iz(["print_jobs"]) == before and _band(jid) == ("PENDING", "mgr-1")
    # Ayni token — o'z bandini yangilaydi (muddat qayta boshlanadi).
    r = _patch(client, men, jid, status="PENDING", claim_token="mgr-1")
    assert r.status_code == 200 and _t(r.json()["claimed_at"]) >= _t(band), r.text
    # PRINTED — har kimdan (qog'oz chiqdi); keyin hamma narsa yakuniy.
    r = _patch(client, kassa, jid, status="PRINTED", attempts=2, claim_token="pos-1")
    assert r.status_code == 200 and r.json()["status"] == "PRINTED", r.text
    assert _patch(client, men, jid, status="PRINTED", claim_token="mgr-1").json() == r.json()
    for tok in ("mgr-1", "pos-1", "yangi"):
        f = _patch(client, men, jid, status="PENDING", claim_token=tok)
        assert f.status_code == 409 and f.headers.get("X-Error-Code") == "PRINT_JOB_FINAL", tok


def test_BAND_OLINADI_FAILED_tokensiz_PENDING_va_ayni_token(client, j):
    kassa, men = j["x"]["kassir@A1"]["h"], j["x"]["menejer"]["h"]
    # Tokensiz (eski mijoz) PENDING — band yo'q: token bilan olinadi.
    sid, jid = _yangi_sotuv(client, j), str(uuid.uuid4())
    r = _post(client, kassa, sid, jid=jid)
    assert r.status_code == 201 and r.json()["claimed_at"] is None, r.text
    r = _patch(client, men, jid, status="PENDING", claim_token="mgr-2")
    assert r.status_code == 200 and r.json()["claimed_at"] is not None, r.text
    assert _band(jid) == ("PENDING", "mgr-2")
    # Egasi FAILED dedi — endi boshqasi oladi, eski egasi esa tirik band ustiga kira olmaydi.
    assert _patch(client, men, jid, status="FAILED", claim_token="mgr-2").status_code == 200
    assert _patch(client, kassa, jid, status="PENDING", claim_token="pos-2").status_code == 200
    assert _band(jid) == ("PENDING", "pos-2")
    _busy(_patch(client, men, jid, status="PENDING", claim_token="mgr-2"))
    # Yaratishdagi band: ayni id'ni boshqa token bilan takror POST — BUSY; PRINTED yaratish band emas.
    sid2, jid2 = _yangi_sotuv(client, j), str(uuid.uuid4())
    assert _post(client, kassa, sid2, jid=jid2, claim_token="pos-3").status_code == 201
    _busy(_post(client, men, sid2, jid=jid2, claim_token="mgr-3"))
    assert _post(client, kassa, sid2, jid=jid2, claim_token="pos-3").json()["duplicate"] is True
    r = _post(client, kassa, sid2, copy="REPRINT", status="PRINTED", claim_token="pos-3")
    assert r.status_code == 201 and r.json()["claimed_at"] is None, r.text


def test_BAND_MUDDATI_LEASE_SECONDS_dan_keyin_boshqa_qurilma_oladi(client, j):
    from app.services.receipt import jobs as RJ
    kassa, men = j["x"]["kassir@A1"]["h"], j["x"]["menejer"]["h"]
    sid, jid = _yangi_sotuv(client, j), str(uuid.uuid4())
    assert _post(client, kassa, sid, jid=jid, claim_token="pos-4").status_code == 201
    # Muddat ichida (chegaradan 10 s oldin) — hali tirik.
    _eskirt(jid, RJ.LEASE_SECONDS - 10)
    _busy(_patch(client, men, jid, status="PENDING", claim_token="mgr-4"))
    _busy(_patch(client, men, jid, status="FAILED", claim_token="mgr-4"))
    # Muddat o'tdi — egasi o'lgan/uzilgan: boshqa qurilma FAILED ham, band ham qila oladi.
    _eskirt(jid, RJ.LEASE_SECONDS + 1)
    assert _patch(client, men, jid, status="FAILED", claim_token="mgr-4").json()["status"] == "FAILED"
    assert _patch(client, kassa, jid, status="PENDING", claim_token="pos-4").status_code == 200
    _eskirt(jid, RJ.LEASE_SECONDS + 1)
    r = _patch(client, men, jid, status="PENDING", claim_token="mgr-4")
    assert r.status_code == 200, r.text
    assert _band(jid) == ("PENDING", "mgr-4")
    _busy(_patch(client, kassa, jid, status="PENDING", claim_token="pos-4"))   # yangi band tirik


def test_BAND_TOKENSIZ_sorov_ESKI_xatti_harakat_bandga_tegmaydi(client, j):
    """Tokensiz so'rov tekshirilmaydi va bandni o'zgartirmaydi (orqaga moslik)."""
    kassa, men = j["x"]["kassir@A1"]["h"], j["x"]["menejer"]["h"]
    sid, jid = _yangi_sotuv(client, j), str(uuid.uuid4())
    b0 = _post(client, kassa, sid, jid=jid, claim_token="pos-5").json()
    r = _patch(client, men, jid, status="PENDING", attempts=3)
    assert r.status_code == 200 and r.json()["claimed_at"] == b0["claimed_at"], r.text
    assert _band(jid) == ("PENDING", "pos-5")
    r = _patch(client, men, jid, status="FAILED", error="eski mijoz")
    assert r.status_code == 200 and r.json()["status"] == "FAILED", r.text
    assert _post(client, men, sid, jid=jid).json()["status"] == "PENDING"


def test_BAND_javobda_claimed_at_bor_TOKEN_hech_qayerda_yoq(client, j):
    kassa = j["x"]["kassir@A1"]["h"]
    sid, jid = _yangi_sotuv(client, j), str(uuid.uuid4())
    tok = "maxfiy-token-" + uuid.uuid4().hex
    resps = [_post(client, kassa, sid, jid=jid, claim_token=tok),
             _patch(client, kassa, jid, status="PENDING", claim_token=tok),
             client.get(URL, headers=kassa, params={"doc_type": "SALE", "doc_id": sid})]
    for r in resps:
        assert r.status_code in (200, 201) and tok not in r.text and "claim_token" not in r.text, r.text
    lst = resps[2].json()
    assert [set(x) for x in lst] == [KEYS] and lst[0]["claimed_at"] is not None
    assert _t(resps[0].json()["claimed_at"]) <= _t(resps[1].json()["claimed_at"])
    assert resps[1].json()["claimed_at"] == lst[0]["claimed_at"]
