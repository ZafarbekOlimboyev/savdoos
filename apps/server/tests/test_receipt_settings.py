# -*- coding: utf-8 -*-
"""PHASE 5F — CHEK SHABLONI SOZLAMASI (`/receipt/settings`, eski `PUT /settings` key=receipt).

Isbotlanadi:
  · meros `filial → kompaniya → BUILTIN` maydonma-maydon; `None` = merosga qaytish;
  · YAGONA validator ikkala yo'lda: noma'lum maydon (eski matn), tip/oraliq/naqsh,
    boshqaruv/bidi belgilari tozalanadi, uzun matn qisqartiriladi, URL qisqartirilMAYDI;
  · doira: kompaniya shabloni — faqat filial cheklovisiz xodim (403 + barqaror kod);
    filial ustamasi — faqat ko'rinadigan filial (begona/ko'rinmas/o'chirilgan — bir xil 404);
  · `GET /settings` FAQAT kompaniya qatorlarini qaytaradi (filial ustamasi aralashmaydi);
  · kassa profili (`/receipt/profile`) va etag;
  · bazadagi buzuq qiymat chekni to'xtatmaydi (tashlanadi, meros ishlaydi).

⚠️  ALOHIDA DO'KONLAR (business tarif): seed do'koni boshqa fayllar bilan bo'lingan.
"""
import uuid

import pytest

from app.services.receipt import errors as E
from app.services.receipt import settings as RS
from tests.test_sales_read_permissions import _filial, _xodim

_VK = {"X-Vendor-Key": "test-vendor-key"}
URL = "/api/v1/receipt/settings"
PROFILE = "/api/v1/receipt/profile"
YOQ = {"detail": "Filial topilmadi"}


def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _dokon(client, plan="business", name="QA chek do'koni"):
    """Yangi do'kon (ega paroli bilan) — {id, cid, name, h}."""
    from app.models.auth import Employee
    phone = f"+99893{uuid.uuid4().int % 10000000:07d}"
    code = f"rc{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/admin/companies", headers=_VK, json={
        "company_name": name, "company_code": code, "owner_name": "QA Chek Ega",
        "owner_phone": phone, "owner_password": "Toshkent-Bahor-2026", "plan": plan})
    assert r.status_code == 200, r.text
    lg = client.post("/api/v1/auth/login/password",
                     json={"phone": phone, "password": "Toshkent-Bahor-2026"})
    assert lg.status_code == 200, lg.text
    eid = lg.json()["employee"]["id"]
    with _db() as db:
        cid = db.get(Employee, uuid.UUID(eid)).company_id
    return {"id": eid, "cid": str(cid), "name": name,
            "h": {"Authorization": f"Bearer {lg.json()['access_token']}"}}


def _asosiy(client, h):
    """Do'konning birinchi (seed) filiali id'si."""
    r = client.get("/api/v1/branches", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["branches"][0]["id"]


def _put(client, h, value, branch_id=None):
    return client.put(URL, headers=h, json={"branch_id": branch_id, "value": value})


def _db_row(cid, branch_id=None):
    from app.models.settings import Setting
    with _db() as db:
        q = db.query(Setting).filter(Setting.company_id == uuid.UUID(cid), Setting.key == "receipt")
        q = (q.filter(Setting.branch_id.is_(None)) if branch_id is None
             else q.filter(Setting.branch_id == uuid.UUID(branch_id)))
        rows = q.all()
        return [(dict(r.value or {}), r.row_version) for r in rows]


@pytest.fixture(scope="module")
def m(client):
    ega = _dokon(client)
    H = ega["h"]
    a0 = _asosiy(client, H)
    a1, a2 = _filial(client, H, "Chek A1"), _filial(client, H, "Chek A2")
    x = {"ega": ega,
         "administrator": _xodim(client, H, "administrator"),
         "administrator@A1": _xodim(client, H, "administrator", filial=a1),
         "menejer": _xodim(client, H, "menejer"),
         "menejer@A1": _xodim(client, H, "menejer", filial=a1),
         "omborchi": _xodim(client, H, "omborchi"),
         "kassir@A1": _xodim(client, H, "kassir", filial=a1)}
    begona = _dokon(client, plan="start", name="Begona chek do'koni")
    x["begona-ega"] = begona
    return {"x": x, "cid": ega["cid"], "a0": a0, "a1": a1, "a2": a2,
            "begona_branch": _asosiy(client, begona["h"])}


# ══ 1 · MEROS ════════════════════════════════════════════════════════════════
def test_BOSH_holat_BUILTIN_va_dokon_nomi(client, m):
    r = client.get(URL, headers=m["x"]["ega"]["h"])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["effective"] == RS.BUILTIN
    assert b["company"] == {} and b["branch"] is None and b["logo"] is None
    assert b["scope"] == {"branch_id": None, "company_editable": True, "branch_editable": False}
    assert {x["id"] for x in b["branches"]} == {m["a0"], m["a1"], m["a2"]}
    # Nom: shablon yo'q → store_info.name (tenant yaratishda = kompaniya nomi).
    assert b["store"]["name"] == "QA chek do'koni"
    assert b["store"]["stir"] is None and b["store"]["branch_name"] is None


def test_MEROS_filial_kompaniya_BUILTIN_maydonma_maydon_va_None_qaytaradi(client, m):
    H = m["x"]["ega"]["h"]
    r = _put(client, H, {"footer": "Xaridingiz uchun rahmat!", "width_mm": 58, "copies": 2})
    assert r.status_code == 200, r.text
    assert r.json()["effective"]["width_mm"] == 58
    r = _put(client, H, {"width_mm": 80, "show_customer": True}, m["a1"])
    assert r.status_code == 200, r.text
    e1 = r.json()["effective"]
    assert (e1["width_mm"], e1["show_customer"], e1["footer"], e1["copies"]) == (
        80, True, "Xaridingiz uchun rahmat!", 2)
    assert r.json()["branch"] == {"width_mm": 80, "show_customer": True}
    assert r.json()["scope"] == {"branch_id": m["a1"], "company_editable": True,
                                 "branch_editable": True}
    # A2 ustamasiz — kompaniyadan meros.
    e2 = client.get(URL, headers=H, params={"branch_id": m["a2"]}).json()["effective"]
    assert (e2["width_mm"], e2["show_customer"], e2["copies"]) == (58, False, 2)
    # Ustama maydonini `None` bilan o'chirish — kompaniyaga qaytadi, qator saqlanadi.
    r = _put(client, H, {"width_mm": None}, m["a1"])
    assert r.status_code == 200, r.text
    assert r.json()["effective"]["width_mm"] == 58
    assert r.json()["branch"] == {"show_customer": True}
    (val, ver), = _db_row(m["cid"], m["a1"])
    assert val == {"show_customer": True} and ver == 2
    # Kompaniya maydonini o'chirish — BUILTIN.
    r = _put(client, H, {"copies": None})
    assert r.status_code == 200 and r.json()["effective"]["copies"] == 1


def test_IKKI_yozuv_HAR_XIL_maydon_ikkalasi_SAQLANADI_row_version_OSADI(client, m):
    H = m["x"]["ega"]["h"]
    before = _db_row(m["cid"])[0][1]
    assert _put(client, H, {"header": "Yangi yil aksiyasi"}).status_code == 200
    assert _put(client, H, {"show_till": True}).status_code == 200
    (val, ver), = _db_row(m["cid"])
    assert val["header"] == "Yangi yil aksiyasi" and val["show_till"] is True
    assert val["footer"] == "Xaridingiz uchun rahmat!"            # avvalgi maydon joyida
    assert ver == before + 2


def test_AUDIT_yoziladi(client, m):
    from app.models.sync import AuditLog
    H = m["x"]["ega"]["h"]
    assert _put(client, H, {"show_stir": False}, m["a2"]).status_code == 200
    with _db() as db:
        a = (db.query(AuditLog).filter(AuditLog.entity == "receipt_settings",
                                       AuditLog.actor_id == uuid.UUID(m["x"]["ega"]["id"]))
             .order_by(AuditLog.created_at.desc()).first())
    assert a is not None and a.after["branch_id"] == m["a2"]
    assert a.after["value"] == {"show_stir": False}


# ══ 2 · VALIDATSIYA ══════════════════════════════════════════════════════════
NOTOGRI = [
    ("width_mm", 57), ("width_mm", "80"), ("width_mm", True), ("width_mm", 80.0),
    ("copies", 0), ("copies", 4), ("copies", 1.5), ("copies", "2"),
    ("lang", "en"), ("lang", 1), ("qr_mode", "url"), ("show_logo", "yes"), ("show_customer", 1),
    ("auto_print", "true"), ("header", 123), ("footer", ["x"]), ("store_display_name", 5),
    ("logo_id", "logo-emas"), ("logo_id", 7),
    ("qr_url", "javascript:alert(1)"), ("qr_url", "https://a b.uz"), ("qr_url", "ftp://x.uz"),
    ("qr_url", 'https://x.uz/"><script>'), ("qr_url", "https://x.uz/" + "a" * 290),
    ("qr_url", "https://x.uz/\x00"), ("qr_url", "https://x.uz/‮"), ("qr_url", "data:text/html,x"),
]


@pytest.mark.parametrize("maydon,qiymat", NOTOGRI, ids=[f"{f}={v!r}"[:40] for f, v in NOTOGRI])
def test_NOTOGRI_qiymat_400_aniq_matn_HECH_NARSA_yozilmaydi(client, m, maydon, qiymat):
    H = m["x"]["ega"]["h"]
    before = _db_row(m["cid"])
    r = _put(client, H, {maydon: qiymat})
    assert r.status_code == 400, r.text
    assert r.json() == {"detail": f"Chek sozlamasi noto'g'ri: {maydon}"}
    assert _db_row(m["cid"]) == before


def test_NOMALUM_maydon_ESKI_matn_ikkala_yolda(client, m):
    H = m["x"]["ega"]["h"]
    r = _put(client, H, {"footer": "ok", "font": "Arial"})
    assert r.status_code == 400 and r.json() == {"detail": "receipt: noma'lum maydon 'font'"}
    r = client.put("/api/v1/settings", headers=H, json={"key": "receipt", "value": {"font": "x"}})
    assert r.status_code == 400 and r.json() == {"detail": "receipt: noma'lum maydon 'font'"}


@pytest.mark.parametrize("tana", [None, [], {"value": []}, {"value": "x"}, {"branch_id": None}])
def test_TANA_shakli_notogri_400(client, m, tana):
    r = client.put(URL, headers=m["x"]["ega"]["h"], json=tana)
    assert r.status_code == 400 and r.json() == {"detail": "Chek sozlamasi noto'g'ri: value"}, r.text


def test_JUDA_KATTA_payload_400(client, m):
    r = _put(client, m["x"]["ega"]["h"], {"header": "x" * 64_100})
    assert r.status_code == 400 and r.json() == {"detail": "Chek sozlamasi noto'g'ri: value"}


def test_BOSHQARUV_va_BIDI_belgilar_TOZALANADI_uzun_matn_QISQARTIRILADI(client, m):
    H = m["x"]["ega"]["h"]
    r = _put(client, H, {
        "header": "\x1b\x70\x00Salom‮ABC⁦\r\nIkkinchi\tqator\x7f\x9b",
        "store_display_name": "  Do'kon\nNomi‏  ",
        "address": "\x1d\x56\x00Toshkent, Chilonzor 5",
        "phone": " ‎+998 90 123 45 67 ",
    }, m["a2"])
    assert r.status_code == 200, r.text
    b = r.json()["branch"]
    # ESC/GS/NUL/DEL/C1/bidi — yo'q; ko'p qatorli maydonda faqat \n qoladi (\r\n → \n, \t → bo'shliq).
    assert b["header"] == "pSalomABC\nIkkinchi qator"
    assert b["store_display_name"] == "Do'kon Nomi"
    assert b["address"] == "VToshkent, Chilonzor 5"
    assert b["phone"] == "+998 90 123 45 67"
    assert r.json()["store"]["name"] == "Do'kon Nomi"
    # Qisqartirish (eski `_as_str` semantikasi) — rad EMAS.
    r = _put(client, H, {"footer": "я" * 2500, "store_display_name": "N" * 200}, m["a2"])
    assert r.status_code == 200, r.text
    assert len(r.json()["branch"]["footer"]) == 2000
    assert r.json()["branch"]["store_display_name"] == "N" * 120
    # Bo'sh bir qatorli maydon = meros (filial/do'kon qiymati).
    r = _put(client, H, {"store_display_name": " \n\t "}, m["a2"])
    assert r.status_code == 200 and "store_display_name" not in r.json()["branch"]


def test_QR_store_url_URLsiz_400_URL_bilan_OK(client, m):
    H = m["x"]["ega"]["h"]
    r = _put(client, H, {"qr_mode": "store_url"}, m["a1"])
    assert r.status_code == 400 and r.json() == {"detail": "Chek sozlamasi noto'g'ri: qr_url"}
    r = _put(client, H, {"qr_mode": "store_url", "qr_url": "https://dokon.uz/fikr?x=1"}, m["a1"])
    assert r.status_code == 200, r.text
    assert r.json()["effective"]["qr_url"] == "https://dokon.uz/fikr?x=1"
    # URL'ni olib tashlash — rejim hamon store_url bo'lsa rad.
    r = _put(client, H, {"qr_url": None}, m["a1"])
    assert r.status_code == 400 and r.json() == {"detail": "Chek sozlamasi noto'g'ri: qr_url"}
    # Aloqasiz maydon QR tekshiruviga tushmaydi.
    assert _put(client, H, {"show_till": True}, m["a1"]).status_code == 200
    assert _put(client, H, {"qr_mode": "none", "qr_url": None}, m["a1"]).status_code == 200


# ══ 3 · DOIRA (filial izolyatsiyasi) ═════════════════════════════════════════
def test_FILIALGA_BOGLANGAN_admin_KOMPANIYA_shablonini_yoza_olmaydi_403_kod(client, m):
    h = m["x"]["administrator@A1"]["h"]
    before = _db_row(m["cid"])
    r = _put(client, h, {"footer": "boshqa filiallarga ham"})
    assert r.status_code == 403, r.text
    assert r.json() == {"detail": E.SCOPE_COMPANY_FORBIDDEN}
    assert r.headers.get("X-Error-Code") == "RECEIPT_SCOPE_COMPANY_FORBIDDEN"
    # Eski yo'l ham AYNI qoida.
    r = client.put("/api/v1/settings", headers=h, json={"key": "receipt", "value": {"footer": "x"}})
    assert r.status_code == 403 and r.headers.get("X-Error-Code") == "RECEIPT_SCOPE_COMPANY_FORBIDDEN"
    assert _db_row(m["cid"]) == before
    # O'z filiali — mumkin; boshqa filial — 404 (mavjudlik oshkor bo'lmaydi).
    assert _put(client, h, {"footer": "A1 rahmat"}, m["a1"]).status_code == 200
    for bid in (m["a2"], m["begona_branch"], str(uuid.uuid4()), "buzuq-id", ""):
        r = _put(client, h, {"footer": "x"}, bid)
        assert r.status_code == 404 and r.json() == YOQ, (bid, r.text)
    g = client.get(URL, headers=h, params={"branch_id": m["a1"]}).json()
    assert g["scope"] == {"branch_id": m["a1"], "company_editable": False, "branch_editable": True}
    assert [b["id"] for b in g["branches"]] == [m["a1"]]


def test_BIRIKTIRILMAGAN_admin_kompaniyani_yozadi_menejer_FAQAT_oqiydi(client, m):
    x = m["x"]
    assert _put(client, x["administrator"]["h"], {"show_branch": True}).status_code == 200
    r = _put(client, x["menejer"]["h"], {"show_branch": False})
    assert r.status_code == 403 and r.json() == {"detail": "Ruxsat yo'q: sozlamalar.edit"}
    g = client.get(URL, headers=x["menejer"]["h"])
    assert g.status_code == 200 and g.json()["scope"]["company_editable"] is False
    g = client.get(URL, headers=x["menejer@A1"]["h"], params={"branch_id": m["a1"]})
    assert g.status_code == 200 and g.json()["scope"]["branch_editable"] is False
    assert client.get(URL, headers=x["menejer@A1"]["h"],
                      params={"branch_id": m["a2"]}).status_code == 404
    for rol in ("kassir@A1", "omborchi"):
        assert client.get(URL, headers=x[rol]["h"]).status_code == 403, rol
    assert client.get(URL).status_code == 401


def test_BEGONA_dokon_filialiga_404_va_OCHIRILGAN_filial_404(client, m):
    x = m["x"]
    for bid in (m["a1"], m["a0"]):
        r = client.get(URL, headers=x["begona-ega"]["h"], params={"branch_id": bid})
        assert r.status_code == 404 and r.json() == YOQ
        r = _put(client, x["begona-ega"]["h"], {"footer": "x"}, bid)
        assert r.status_code == 404 and r.json() == YOQ
    H = x["ega"]["h"]
    tmp = _filial(client, H, "Chek vaqtinchalik")
    assert client.delete(f"/api/v1/branches/{tmp}", headers=H).status_code == 200
    assert client.get(URL, headers=H, params={"branch_id": tmp}).status_code == 404
    assert _put(client, H, {"footer": "x"}, tmp).status_code == 404


# ══ 4 · GET /settings — FAQAT kompaniya qatorlari ═══════════════════════════
def test_GET_settings_FILIAL_ustamasini_ARALASHTIRMAYDI(client, m):
    H = m["x"]["ega"]["h"]
    # Filial qatori row_version'i kompaniyanikidan KATTA bo'lsin (eski xato shunda ko'rinardi).
    for i in range(8):
        assert _put(client, H, {"footer": f"A2 ustama {i}"}, m["a2"]).status_code == 200
    comp_footer = _db_row(m["cid"])[0][0]["footer"]
    got = client.get("/api/v1/settings", headers=H).json()["receipt"]
    assert got["footer"] == comp_footer != "A2 ustama 7"
    # Kassir ham (UI kalitlari) — faqat kompaniya qiymati.
    got = client.get("/api/v1/settings", headers=m["x"]["kassir@A1"]["h"]).json()["receipt"]
    assert got["footer"] == comp_footer


def test_ESKI_PUT_settings_receipt_YANGI_maydonlar_va_TOZALASH(client, m):
    H = m["x"]["ega"]["h"]
    r = client.put("/api/v1/settings", headers=H, json={"key": "receipt", "value": {
        "footer": "Eski\x1b\x70 yo'l", "printer": "  XP-80C\n", "show_barcode": True, "width_mm": 80}})
    assert r.status_code == 200, r.text
    v = r.json()["receipt"]
    assert (v["footer"], v["printer"], v["show_barcode"], v["width_mm"]) == ("Eskip yo'l", "XP-80C", True, 80)
    r = client.put("/api/v1/settings", headers=H, json={"key": "receipt", "value": {"width_mm": 70}})
    assert r.status_code == 400 and r.json() == {"detail": "Chek sozlamasi noto'g'ri: width_mm"}
    r = client.put("/api/v1/settings", headers=H, json={"key": "receipt", "value": {"qr_mode": "store_url"}})
    assert r.status_code == 400 and r.json() == {"detail": "Chek sozlamasi noto'g'ri: qr_url"}


# ══ 5 · BAZADAGI BUZUQ QIYMAT ════════════════════════════════════════════════
def test_BAZADAGI_buzuq_maydonlar_TASHLANADI_meros_ISHLAYDI(client, m):
    from app.models.settings import Setting
    H = m["x"]["ega"]["h"]
    with _db() as db:
        db.add(Setting(company_id=uuid.UUID(m["cid"]), branch_id=uuid.UUID(m["a0"]), key="receipt",
                       value={"width_mm": "keng", "show_logo": "ha", "copies": 99, "evil": 1,
                              "header": "Yaxshi\x1bsarlavha", "lang": "ru", "qr_url": "javascript:x"}))
        db.commit()
    r = client.get(URL, headers=H, params={"branch_id": m["a0"]})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["branch"] == {"header": "Yaxshisarlavha", "lang": "ru"}
    e = b["effective"]
    comp = RS.effective(_db_row(m["cid"])[0][0])
    assert e["width_mm"] == comp["width_mm"] and e["copies"] == comp["copies"]
    assert e["show_logo"] is True and e["qr_url"] is None and e["lang"] == "ru"
    assert "evil" not in e


# ══ 6 · KASSA PROFILI ════════════════════════════════════════════════════════
def test_PROFIL_kassir_OZ_filiali_etag_va_unchanged(client, m):
    x = m["x"]
    h = x["kassir@A1"]["h"]
    r = client.get(PROFILE, headers=h)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["branch_id"] == m["a1"] and len(p["etag"]) == 64
    assert set(p) == {"etag", "branch_id", "effective", "store", "logo", "store_qr"}
    assert p["store"]["branch_name"] == "Chek A1"
    r2 = client.get(PROFILE, headers=h, params={"known_etag": p["etag"]})
    assert r2.json() == {"etag": p["etag"], "unchanged": True}
    assert client.get(PROFILE, headers=h, params={"known_etag": "x" * 64}).json()["etag"] == p["etag"]
    # Shablon o'zgarsa etag o'zgaradi.
    assert _put(client, x["ega"]["h"], {"footer": "Yangi rahmat"}, m["a1"]).status_code == 200
    p3 = client.get(PROFILE, headers=h, params={"known_etag": p["etag"]}).json()
    assert p3["etag"] != p["etag"] and p3["effective"]["footer"] == "Yangi rahmat"
    # Ko'rinmas filial — 404; ruxsatsiz rol — 403.
    assert client.get(PROFILE, headers=h, params={"branch_id": m["a2"]}).status_code == 404
    assert client.get(PROFILE, headers=x["omborchi"]["h"]).status_code == 403


def test_PROFIL_store_QR_matritsasi(client, m):
    H = m["x"]["ega"]["h"]
    assert _put(client, H, {"qr_mode": "store_url", "qr_url": "https://dokon.uz/"}, m["a2"]).status_code == 200
    p = client.get(PROFILE, headers=H, params={"branch_id": m["a2"]}).json()
    q = p["store_qr"]
    assert q["payload"] == "https://dokon.uz/" and q["size"] == len(q["matrix"]) == len(q["matrix"][0])
    assert set("".join(q["matrix"])) <= {"0", "1"}
    assert _put(client, H, {"qr_mode": "none"}, m["a2"]).status_code == 200
    assert client.get(PROFILE, headers=H, params={"branch_id": m["a2"]}).json()["store_qr"] is None


# ══ 7 · SOF VALIDATOR ════════════════════════════════════════════════════════
def test_validator_None_ochiradi_va_BUILTIN_kalitlari_toliq():
    assert RS.validate_receipt_patch({"footer": None, "copies": 3}) == {"footer": None, "copies": 3}
    assert set(RS.BUILTIN) == {
        "header", "footer", "printer", "show_barcode", "store_display_name", "address", "phone",
        "width_mm", "lang", "show_logo", "logo_id", "show_branch", "show_stir", "show_cashier",
        "show_till", "show_payment_breakdown", "show_discount", "show_customer", "qr_mode",
        "qr_url", "auto_cut", "copies", "auto_print"}
    t = RS.template_of(RS.BUILTIN)
    assert not {"printer", "logo_id", "qr_url"} & set(t) and len(t) == len(RS.BUILTIN) - 3
    lid = str(uuid.uuid4()).upper()
    assert RS.validate_receipt_patch({"logo_id": lid}) == {"logo_id": lid.lower()}
