# -*- coding: utf-8 -*-
"""PHASE 5F — CHEK O'QISH ENDPOINTLARI BAZAGA HECH NARSA YOZMAYDI.

`GET /receipt/sample` (4 tur), `/receipt/profile`, `/receipt/settings`, `/receipt/logos/{id}`,
`/sales/{id}/receipt`, `/returns/{id}/receipt`, `/print-jobs` — oldin/keyin BARCHA jadvallar
izi (qatorlar soni + mazmun xeshi) AYNAN bir xil.

⚠️  SALBIY NAZORAT: bitta haqiqiy yozuv (`PUT /receipt/settings`) izni O'ZGARTIRADI — ya'ni
    iz yozuvni haqiqatan sezadi, «hammasi teng» bo'sh o'lchov emas.
"""
import hashlib
import uuid

import pytest
from sqlalchemy import inspect, text

from tests.test_lot_fefo_sale import _product
from tests.test_receipt_settings import _dokon, _put
from tests.test_sales_read_permissions import _filial, _karta_sotuv, _qaytar, _qoldiq, _xodim


def iz(tables=None) -> dict:
    """{jadval: (qatorlar soni, mazmun sha256)} — barcha (yoki berilgan) jadvallar."""
    from app.db.session import engine
    names = sorted(tables or inspect(engine).get_table_names())
    out = {}
    with engine.connect() as con:
        for t in names:
            rows = con.execute(text(f'SELECT * FROM "{t}"')).fetchall()
            h = hashlib.sha256()
            for r in sorted(repr(tuple(r)) for r in rows):
                h.update(r.encode("utf-8", "surrogatepass"))
            out[t] = (len(rows), h.hexdigest())
    return out


def _farq(a: dict, b: dict) -> dict:
    return {t: (a.get(t), b.get(t)) for t in set(a) | set(b) if a.get(t) != b.get(t)}


@pytest.fixture(scope="module")
def w(client):
    ega = _dokon(client, name="QA yozmaslik do'koni")
    H = ega["h"]
    a1 = _filial(client, H, "NW A1")
    kassir = _xodim(client, H, "kassir", filial=a1)
    menejer = _xodim(client, H, "menejer")
    pid = _product(client, H)
    _qoldiq(pid, a1, 100)
    sale = _karta_sotuv(client, kassir["h"], pid, qty=2)
    ret = _qaytar(client, kassir["h"], sale["id"], pid)
    assert ret.status_code == 200, ret.text
    import base64
    import io

    from PIL import Image
    b = io.BytesIO()
    Image.new("L", (64, 32), 0).save(b, "PNG")
    lg = client.post("/api/v1/receipt/logos", headers=H,
                     json={"branch_id": None, "data_b64": base64.b64encode(b.getvalue()).decode()})
    assert lg.status_code == 201, lg.text
    assert _put(client, H, {"logo_id": lg.json()["id"], "show_barcode": True, "qr_mode": "receipt_id",
                            "show_customer": True}).status_code == 200
    job = client.post("/api/v1/print-jobs", headers=kassir["h"], json={
        "id": str(uuid.uuid4()), "doc_type": "SALE", "doc_id": sale["id"], "copy": "ORIGINAL"})
    assert job.status_code == 201, job.text
    return {"H": H, "kassir": kassir, "menejer": menejer, "a1": a1, "sale": sale,
            "ret": ret.json(), "logo": lg.json()["id"]}


def _oqishlar(client, w):
    k, H, mh = w["kassir"]["h"], w["H"], w["menejer"]["h"]
    reqs = [(H, "/api/v1/receipt/sample", {"kind": kind}) for kind in ("sale", "mixed", "return", "long")]
    reqs += [(k, "/api/v1/receipt/sample", {"kind": "long"}),
             (k, "/api/v1/receipt/profile", None), (H, "/api/v1/receipt/profile", {"branch_id": w["a1"]}),
             (H, "/api/v1/receipt/settings", None), (mh, "/api/v1/receipt/settings", {"branch_id": w["a1"]}),
             (H, f"/api/v1/receipt/logos/{w['logo']}", None),
             (k, f"/api/v1/sales/{w['sale']['id']}/receipt", None),
             (H, f"/api/v1/returns/{w['ret']['id']}/receipt", None),
             (k, "/api/v1/print-jobs", {"doc_type": "SALE", "doc_id": w["sale"]["id"]}),
             (k, f"/api/v1/sales/{uuid.uuid4()}/receipt", None)]
    for h, path, params in reqs:
        r = client.get(path, headers=h, params=params)
        assert r.status_code in (200, 404), (path, r.text)


def test_OQISH_endpointlari_HECH_BIR_jadvalga_yozmaydi(client, w):
    oldin = iz()
    assert "print_jobs" in oldin and "receipt_logos" in oldin and "settings" in oldin
    _oqishlar(client, w)
    keyin = iz()
    assert _farq(oldin, keyin) == {}


def test_NAMUNA_toliq_DTO_va_iz_ozgarmaydi(client, w):
    oldin = iz()
    for kind in ("sale", "mixed", "return", "long"):
        dto = client.get("/api/v1/receipt/sample", headers=w["H"], params={"kind": kind}).json()
        assert dto["test"] is True and dto["logo"]["id"] == w["logo"]
        if kind != "return":
            assert dto["barcode"]["payload"] == "TEST000000" and dto["qr"]["kind"] == "receipt_id"
            assert dto["customer"] == {"name": "TEST"}
    assert _farq(oldin, iz()) == {}


def test_SALBIY_nazorat_haqiqiy_yozuv_IZNI_ozgartiradi(client, w):
    oldin = iz()
    assert _put(client, w["H"], {"footer": f"iz {uuid.uuid4().hex[:6]}"}).status_code == 200
    farq = _farq(oldin, iz())
    assert "settings" in farq and "audit_log" in farq, farq
