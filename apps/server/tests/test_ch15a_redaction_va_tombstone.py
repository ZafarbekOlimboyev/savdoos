# -*- coding: utf-8 -*-
"""CH-15A — 422 REDAKSIYASI va O'CHIRILGAN XODIM TOMBSTONE'i.

IKKI QOIDA (ikkisi ham XULQNI o'lchaydi, matnni emas):

  1. Validatsiya xatosi (422) javobida hisob-faktura surati (`image_b64`) va AI o'qigan
     xom qatorlar (`ai_raw`) QAYTARILMAYDI. Pydantic v2 har xato yozuviga `input` —
     YUBORILGAN QIYMATNI — qo'shadi; "Field required" xatosining `input` i esa BUTUN
     TANA bo'ladi, ya'ni yonidagi surat ham javobga tushardi. Surat kredensial emas,
     lekin: (a) galereyadan tanlangan rasm o'zining EXIF/{GPS} koordinatasini olib
     keladi, (b) ~11 MB gacha bo'lishi mumkin. Javob tanasi proxy loglariga va
     xato-kuzatuv tizimlariga tushadi — ularda bu ma'lumot turmasligi kerak.

  2. YUMSHOQ O'CHIRILGAN (`deleted_at IS NOT NULL`) xodim to'rtta yo'lning HECH BIRIDAN
     ham o'qilmaydi va o'zgartirilmaydi: `GET /employees/{id}`, `GET /employees/{id}/stats`,
     `PATCH /employees/{id}`, `PATCH /employees/{id}/permissions`. Hammasi AYNI 404
     ("Xodim topilmadi") — yo'q xodim, begona tenant xodimi va tombstone farqlanmaydi,
     aks holda bu oracle bo'lardi.

     O'LCHANGAN HOLAT (tuzatishdan oldin, manfiy nazorat): `GET /employees/{id}` 200 bilan
     o'chirilgan xodimning TELEFONINI qaytarardi; `PATCH /employees/{id}` ga `phone`,
     `password`, `status`, `full_name` ning HAR BIRI alohida 200 bilan YOZILARDI;
     `PATCH .../permissions` tombstone'ga ruxsat qayta berardi.
     ⚠️  Bu LOGIN teshigi EMAS — `auth.py:368`/`:151`/`:253` va `core/deps.py:25`
         `deleted_at` ni MUSTAQIL filtrlaydi, ya'ni tombstone kira olmaydi. Zarar
         ma'lumot qatlamida: o'chirilgan xodim PII'si o'qiladi va tombstone
         o'zgartiriladi (audit izi buziladi).

MANFIY NAZORAT: FAOL xodim uchun ayni to'rtta yo'l ISHLASHDA QOLADI (`test_FAOL_...`) —
aks holda tuzatish funksiyani o'chirgan bo'lardi.

DOIRA: `DELETE /employees/{id}` ning o'zini-o'chirish va oxirgi-rahbar gardlari
TEGILMAGAN va bu paket ularni o'lchamaydi.
"""
from __future__ import annotations

import uuid

from tests.test_mobile_parity import _db, _shop, _staff

# Javobda IZLANADIGAN sintetik belgilar — haqiqiy surat YOQ, haqiqiy tarmoq chaqiruvi YOQ.
RASM_BELGISI = "QUJDRkFLRS1DSDE1QS1SQVNNLUJFTEdJU0k"      # qisqa, base64-ko'rinish
AI_BELGISI = "CH15A-AI-XOM-QATOR-BELGISI"


# ══ QOIDA 1 — 422 javobida surat va AI xom qatorlari YO'Q ════════════════════

def test_422_RASM_va_AI_XOM_qatorlari_JAVOBDA_YOQ(client):
    """`items` MAJBURIY — uni tashlab yuborsak "Field required" chiqadi va Pydantic
    `input` ga BUTUN TANANI qo'yadi. Aynan shu yo'l bilan surat javobga tushardi."""
    d = _shop()
    tana = {
        # `items` ATAYLAB yo'q -> missing xatosi -> input = butun tana
        "image_b64": RASM_BELGISI,
        "ai_raw": [{"name": AI_BELGISI, "qty": 1}],
        "source": "ai",
        "payment": "cash",
    }
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json=tana)

    assert r.status_code == 422, (r.status_code, r.text)
    assert RASM_BELGISI not in r.text, f"SURAT 422 javobida qaytdi: {r.text[:400]!r}"
    assert AI_BELGISI not in r.text, f"AI xom qatori 422 javobida qaytdi: {r.text[:400]!r}"
    # Diagnostika YO'QOLMAGANI: xato hamon `items` ni ko'rsatadi.
    assert "items" in r.text, r.text


def test_422_SURAT_MAYDONINING_OZI_xato_bersa_ham_QAYTMAYDI(client):
    """`loc` surat maydonini ko'rsatganda `input` butunlay olib tashlanadi
    (`_sensitive` yo'li). 15 MB chegarasi ATAYLAB sinovdan tashqarida — bu yerda
    tur xatosi (ro'yxat berilgan, satr kutilgan) bilan ayni yo'l tekshiriladi."""
    d = _shop()
    tana = {"items": [], "image_b64": [RASM_BELGISI], "source": "ai"}
    r = client.post("/api/v1/receiving/commit", headers=d["H"], json=tana)

    assert r.status_code == 422, (r.status_code, r.text)
    assert RASM_BELGISI not in r.text, f"SURAT 422 javobida qaytdi: {r.text[:400]!r}"


def test_422_ODDIY_maydon_DIAGNOSTIKASI_SAQLANADI(client):
    """Redaksiya faqat belgilangan maydonlarga tegadi: oddiy maydonning yuborilgan
    qiymati diagnostika uchun JOYIDA qoladi (aks holda tuzatish xato topishni o'chirardi)."""
    d = _shop()
    r = client.post("/api/v1/receiving/commit", headers=d["H"],
                    json={"items": [], "source": "BUNDAY-MANBA-YOQ-" + "x" * 40})

    assert r.status_code == 422, (r.status_code, r.text)
    assert "source" in r.text, r.text


# ══ QOIDA 2 — o'chirilgan xodim to'rtta yo'ldan ham 404 ══════════════════════

def _ochirilgan_kassir(d: dict, client) -> uuid.UUID:
    """Kassir yaratib, uni EGA sifatida HAQIQIY `DELETE` yo'li bilan o'chiradi."""
    _, kid = _staff(d, "kassir")
    r = client.delete(f"/api/v1/employees/{kid}", headers=d["H"])
    assert r.status_code == 200, (r.status_code, r.text)
    with _db() as db:
        from app.models.auth import Employee
        assert db.get(Employee, kid).deleted_at is not None, "yumshoq o'chirish bajarilmadi"
    return kid


def test_OCHIRILGAN_xodim_TORT_YOLDAN_ham_404(client):
    d = _shop()
    kid = _ochirilgan_kassir(d, client)

    javoblar = {
        "GET /employees/{id}": client.get(f"/api/v1/employees/{kid}", headers=d["H"]),
        "GET /employees/{id}/stats": client.get(f"/api/v1/employees/{kid}/stats", headers=d["H"]),
        "PATCH /employees/{id}": client.patch(f"/api/v1/employees/{kid}", headers=d["H"],
                                              json={"full_name": "Tirilgan"}),
        "PATCH /employees/{id}/permissions": client.patch(
            f"/api/v1/employees/{kid}/permissions", headers=d["H"],
            json={"overrides": {"kassa.sell": True}}),
    }
    for yol, r in javoblar.items():
        assert r.status_code == 404, f"{yol} -> {r.status_code} (404 kutilgan): {r.text[:200]}"


def test_OCHIRILGAN_xodim_TELEFON_va_PAROL_TIRILMAYDI(client):
    """Eng muhim band: `PATCH` tombstone'ga kredensial qaytarib yozmasin."""
    d = _shop()
    kid = _ochirilgan_kassir(d, client)
    with _db() as db:
        from app.models.auth import Employee
        e = db.get(Employee, kid)
        oldin = (e.full_name, e.phone, e.password_hash, e.pin_hash, e.role_id, e.status)

    yangi_tel = f"+9987{uuid.uuid4().int % 10**7:07d}"
    r = client.patch(f"/api/v1/employees/{kid}", headers=d["H"],
                     json={"phone": yangi_tel, "password": "YangiParol123",
                          "pin": "4321", "status": "active", "full_name": "Tirilgan"})
    assert r.status_code == 404, (r.status_code, r.text)

    with _db() as db:
        from app.models.auth import Employee
        e = db.get(Employee, kid)
        keyin = (e.full_name, e.phone, e.password_hash, e.pin_hash, e.role_id, e.status)
        assert e.deleted_at is not None, "tombstone tiklandi"
        assert keyin == oldin, f"tombstone O'ZGARDI: {oldin!r} -> {keyin!r}"
        assert e.phone != yangi_tel, "telefon tombstone'ga yozildi"


def test_OCHIRILGAN_xodim_ROYXATDA_ham_YOQ(client):
    """Mavjud xulq (regressiya nazorati): ro'yxat allaqachon filtrlaydi."""
    d = _shop()
    kid = _ochirilgan_kassir(d, client)
    r = client.get("/api/v1/employees", headers=d["H"])
    assert r.status_code == 200, r.text
    assert str(kid) not in r.text, r.text


# ══ MANFIY NAZORAT — FAOL xodim oqimlari O'ZGARMAGAN ════════════════════════

def test_FAOL_xodim_TORT_YOLDA_ham_ISHLAYDI(client):
    d = _shop()
    _, kid = _staff(d, "kassir")

    r = client.get(f"/api/v1/employees/{kid}", headers=d["H"])
    assert r.status_code == 200, (r.status_code, r.text)
    assert str(kid) in r.text, r.text

    r = client.get(f"/api/v1/employees/{kid}/stats", headers=d["H"])
    assert r.status_code == 200, (r.status_code, r.text)
    for kalit in ("month_sales", "tx", "chart"):
        assert kalit in r.text, r.text

    r = client.patch(f"/api/v1/employees/{kid}", headers=d["H"],
                     json={"full_name": "Faol Kassir"})
    assert r.status_code == 200, (r.status_code, r.text)

    r = client.patch(f"/api/v1/employees/{kid}/permissions", headers=d["H"],
                     json={"overrides": {"kassa.sell": True}})
    assert r.status_code == 200, (r.status_code, r.text)

    with _db() as db:
        from app.models.auth import Employee
        e = db.get(Employee, kid)
        assert e.full_name == "Faol Kassir", e.full_name
        assert e.deleted_at is None
