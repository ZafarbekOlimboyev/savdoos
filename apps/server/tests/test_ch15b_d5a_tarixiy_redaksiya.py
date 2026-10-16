# -*- coding: utf-8 -*-
"""CH-15B FAZA A.2 (D5-a) — TARIXIY MAXFIY YUK `GET /receiving/{id}` DAN QAYTMAYDI.

QOIDA. CH-15B Faza A faqat YANGI qatorlarni to'xtatdi. Faza A dan OLDIN yozilgan
qatorlarda uchta maxfiy qiymat diskda QOLGAN va bu yo'l ularning YAGONA API
chiqishi edi:
  · `image_b64`              — to'liq base64 nakladnoy surati (EXIF/GPS bilan)
  · `ai_raw`                 — AI ning xom javobi
  · `final_items[].ai_name`  — AI ning qatorni SO'ZMA-SO'Z o'qishi

Endi javobda ularning qiymati YO'Q, lekin KALITLAR va TURLAR saqlanadi.

⚠️  MA'LUMOT O'CHIRILMAYDI. Bu — CHIQISHNI yopish, tozalash EMAS. Har test
    GET dan KEYIN diskdagi qatorni qayta o'qib, maxfiy qiymat JOYIDA ekanini
    tasdiqlaydi (`test_BAZADAGI_qiymat_OZGARMAYDI`). Legacy purge — Faza C,
    alohida ega ruxsati bilan.

⚠️  ORM OBYEKTI O'ZGARTIRILMAYDI. `r.final_items` — identity-map'dagi AYNAN o'sha
    ro'yxat. `JSONB` bu yerda `Mutable` tur EMAS (`db/types.py`), ya'ni joyida
    tahrir flush qilinmasdan xotira bilan diskni AJRATARDI, va ayni sessiyadagi
    keyingi o'quvchi (`lot_correction`) tozalangan ro'yxatni ko'rardi.
    `test_YORDAMCHI_kirishni_OZGARTIRMAYDI` buni to'g'ridan-to'g'ri o'lchaydi.

USUL: tarixiy qator ORM bilan TO'G'RIDAN yoziladi (Faza A dan oldingi shaklni
AYNAN takrorlash uchun — hozirgi `/commit` endi bu maydonlarni yozmaydi) va har
test o'z UNIKAL markerini qidiradi. Marker qiymat bo'yicha izlanadi, kalit nomi
bo'yicha emas: refaktoring kalitni ko'chirsa ham sinov tirik qoladi.

DOIRA: tarixiy `unit` qiymatlari va `CommitIn.source` TEGILMAYDI (ega ko'rsatmasi).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from tests.test_mobile_parity import _db, _product, _shop


def _marker(nima: str) -> str:
    return f"D5A-{nima}-{uuid.uuid4().hex}"


def _tarixiy_qabul(d, pid, *, img, ai_raw, ai_name, unit="dona"):
    """FAZA A DAN OLDINGI qator — ORM bilan to'g'ridan yoziladi.

    Hozirgi `POST /receiving/commit` bu maydonlarni ATAYLAB yozmaydi (Faza A),
    shuning uchun tarixiy holatni API orqali yaratish MUMKIN EMAS."""
    from app.models.receiving import Receiving
    with _db() as db:
        r = Receiving(
            company_id=d["cid"], branch_id=d["bids"][0], employee_id=d["eid"],
            source="ai", image_b64=img, ai_raw=ai_raw,
            final_items=[{"product_id": str(pid), "name": "Tarixiy mahsulot",
                          "qty": 3.0, "unit_cost": 1500.0,
                          "ai_name": ai_name, "unit": unit}],
            total_types=1, total_qty=3, committed_at=datetime.now(timezone.utc),
            client_uuid=uuid.uuid4(),
        )
        db.add(r)
        db.commit()
        return str(r.id)


def _diskdan(rid):
    """Diskdagi qator — YANGI sessiyada (identity-map ta'siridan xoli)."""
    from app.models.receiving import Receiving
    with _db() as db:
        r = db.get(Receiving, uuid.UUID(str(rid)))
        assert r is not None
        return {"image_b64": r.image_b64, "ai_raw": r.ai_raw,
                "final_items": json.loads(json.dumps(r.final_items, default=str))}


# ══ QOIDA — uchta maxfiy qiymat JAVOBDA YO'Q ═════════════════════════════════

def test_TARIXIY_surat_AI_XOM_va_AI_NOMI_JAVOBDA_YOQ(client):
    d = _shop()
    p = _product(d, name="D5A mahsulot", qty=0)
    m_img, m_ai, m_name = _marker("IMG"), _marker("AIRAW"), _marker("AINAME")
    rid = _tarixiy_qabul(d, p["id"], img=m_img, ai_raw=[{"name": m_ai}], ai_name=m_name)

    r = client.get(f"/api/v1/receiving/{rid}", headers=d["H"])

    assert r.status_code == 200, (r.status_code, r.text[:300])
    for marker, nima in ((m_img, "surat"), (m_ai, "AI xom javobi"), (m_name, "AI nomi")):
        assert marker not in r.text, f"{nima} javobda QAYTDI: {r.text[:400]!r}"


def test_KALITLAR_va_TURLAR_saqlanadi(client):
    """Eski mijozlar shartnomasi: kalitlar joyida, turlar mos (`None` / `[]` / `None`)."""
    d = _shop()
    p = _product(d, name="D5A mahsulot", qty=0)
    rid = _tarixiy_qabul(d, p["id"], img=_marker("IMG"),
                         ai_raw=[{"name": _marker("AIRAW")}], ai_name=_marker("AINAME"))

    j = client.get(f"/api/v1/receiving/{rid}", headers=d["H"]).json()

    assert "image_b64" in j and j["image_b64"] is None, j.get("image_b64")
    assert "ai_raw" in j and j["ai_raw"] == [], j.get("ai_raw")
    assert isinstance(j["items"], list) and len(j["items"]) == 1
    qator = j["items"][0]
    assert "ai_name" in qator, f"`ai_name` KALITI o'chib ketdi: {sorted(qator)}"
    assert qator["ai_name"] is None, qator["ai_name"]


def test_TASDIQLANGAN_biznes_maydonlari_TEGILMAGAN(client):
    """Operator tasdiqlagan maydonlar va hujjat sarlavhasi AYNAN o'z joyida."""
    d = _shop()
    p = _product(d, name="D5A mahsulot", qty=0)
    rid = _tarixiy_qabul(d, p["id"], img=_marker("IMG"), ai_raw=[], ai_name=_marker("AINAME"),
                         unit="kg")

    j = client.get(f"/api/v1/receiving/{rid}", headers=d["H"]).json()

    qator = j["items"][0]
    assert qator["product_id"] == str(p["id"])
    assert qator["name"] == "Tarixiy mahsulot"
    assert float(qator["qty"]) == 3.0
    assert float(qator["unit_cost"]) == 1500.0
    assert qator["unit"] == "kg", "tarixiy `unit` D5-a doirasidan TASHQARIDA — tegilmasligi kerak"
    assert j["total_types"] == 1 and float(j["total_qty"]) == 3.0
    assert j["source"] == "ai"
    assert j["id"] == rid and j["at"] is not None


# ══ MA'LUMOT O'CHIRILMAYDI ═══════════════════════════════════════════════════

def test_BAZADAGI_qiymat_OZGARMAYDI(client):
    """⚠️  ENG MUHIM BAND: bu chiqishni yopish, tozalash EMAS."""
    d = _shop()
    p = _product(d, name="D5A mahsulot", qty=0)
    m_img, m_ai, m_name = _marker("IMG"), _marker("AIRAW"), _marker("AINAME")
    rid = _tarixiy_qabul(d, p["id"], img=m_img, ai_raw=[{"name": m_ai}], ai_name=m_name)
    oldin = _diskdan(rid)

    assert client.get(f"/api/v1/receiving/{rid}", headers=d["H"]).status_code == 200
    client.get(f"/api/v1/receiving/{rid}", headers=d["H"])      # ikkinchi o'qish ham

    keyin = _diskdan(rid)
    assert keyin == oldin, f"GET diskdagi qatorni O'ZGARTIRDI:\n{oldin!r}\n{keyin!r}"
    assert keyin["image_b64"] == m_img, "surat diskdan yo'qoldi"
    assert keyin["ai_raw"] == [{"name": m_ai}], "ai_raw diskdan yo'qoldi"
    assert keyin["final_items"][0]["ai_name"] == m_name, "ai_name diskdan yo'qoldi"


def test_YORDAMCHI_kirishni_OZGARTIRMAYDI(client):
    """Tozalagich KIRISH obyektini o'zgartirmasligini TO'G'RIDAN o'lchaydi
    (identity-map himoyasi: ORM ro'yxati aynan shu obyekt bo'ladi)."""
    from app.api.v1.receiving import _tarixiy_qatorlarni_tozalash as toza

    m = _marker("AINAME")
    kirish = [{"product_id": "p1", "name": "N", "qty": 1.0, "unit_cost": 2.0,
               "ai_name": m, "unit": "dona"}]
    surat = json.dumps(kirish, sort_keys=True)

    chiqish = toza(kirish)

    assert json.dumps(kirish, sort_keys=True) == surat, f"KIRISH o'zgardi: {kirish!r}"
    assert kirish[0]["ai_name"] == m, "kirish qatori joyida tahrirlandi"
    assert chiqish[0]["ai_name"] is None, chiqish[0]
    assert chiqish is not kirish, "ayni ro'yxat qaytdi"
    assert chiqish[0] is not kirish[0], "ayni dict qaytdi — sayoz nusxa yo'q"


def test_YORDAMCHI_chetki_holatlar(client):
    """Bo'sh/None/kutilmagan shakl — yiqilmaydi, ma'lumot yo'qotmaydi."""
    from app.api.v1.receiving import _tarixiy_qatorlarni_tozalash as toza

    assert toza(None) == []
    assert toza([]) == []
    # `ai_name` kaliti YO'Q (Faza A dan keyingi qator) -> SHAKL O'ZGARMAYDI
    yangi = [{"product_id": "p", "name": "N", "qty": 1.0, "unit_cost": 2.0, "unit": "dona"}]
    assert toza(yangi) == yangi
    assert "ai_name" not in toza(yangi)[0], "yangi qatorga `ai_name` QO'SHILDI"
    # dict bo'lmagan element — tegilmaydi
    assert toza(["xom", 7, None]) == ["xom", 7, None]


# ══ AVTORIZATSIYA VA TENANT IZOLYATSIYASI O'ZGARMAGAN ════════════════════════

def test_TENANT_izolyatsiyasi_va_AVTORIZATSIYA_saqlanadi(client):
    """Redaksiya 404/401 xulqini buzmaydi — begona do'kon va tokensiz so'rov."""
    A, B = _shop(), _shop()
    pa = _product(A, name="A mahsulot", qty=0)
    m = _marker("IMG")
    rid = _tarixiy_qabul(A, pa["id"], img=m, ai_raw=[], ai_name=_marker("AINAME"))

    # Begona do'kon -> 404 (mavjudligi ham oshkor bo'lmaydi)
    rb = client.get(f"/api/v1/receiving/{rid}", headers=B["H"])
    assert rb.status_code == 404, (rb.status_code, rb.text[:200])
    assert m not in rb.text

    # Tokensiz -> 200 EMAS
    rn = client.get(f"/api/v1/receiving/{rid}")
    assert rn.status_code in (401, 403), rn.status_code
    assert m not in rn.text

    # Yo'q qabul -> 404
    assert client.get(f"/api/v1/receiving/{uuid.uuid4()}", headers=A["H"]).status_code == 404

    # O'z do'koni -> 200
    assert client.get(f"/api/v1/receiving/{rid}", headers=A["H"]).status_code == 200


# ══ YANGI QATORLAR REGRESSIYASI ══════════════════════════════════════════════

def test_YANGI_qator_shakli_OZGARMAYDI(client):
    """Faza A dan keyingi qator `/commit` orqali: `ai_name` kaliti QO'SHILMAYDI."""
    d = _shop()
    p = _product(d, name="Yangi mahsulot", qty=0)
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json={
        "items": [{"product_id": str(p["id"]), "qty": 2, "unit_cost": 100, "unit": "dona"}],
        "payment": "cash", "source": "ai", "client_uuid": str(uuid.uuid4())})
    assert r.status_code == 200, r.text

    j = client.get(f"/api/v1/receiving/{r.json()['receiving_id']}", headers=d["H"]).json()

    assert set(j["items"][0]) == {"product_id", "name", "qty", "unit_cost", "unit"}, \
        f"yangi qator shakli o'zgardi: {sorted(j['items'][0])}"
    assert j["image_b64"] is None and j["ai_raw"] == []
