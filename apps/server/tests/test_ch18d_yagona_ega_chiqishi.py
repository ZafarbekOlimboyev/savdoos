# -*- coding: utf-8 -*-
"""CH-18D/A — YAGONA EGANING TO'LIQ CHIQISHI, boshidan oxirigacha.

⚠️  QULFLANIB QOLISHNING OXIRGI SHAKLI. Yopish `Company.deleted_at` ni
    o'rnatadi, autentifikatsiya esa yopilgan ijarachini RAD etadi
    (`core/deps.py` -> 401) — EGA uchun ham. Ya'ni «avval yopaman, keyin
    o'zimni o'chiraman» ketma-ketligi IMKONSIZ: ikkinchi qadamda ega
    ichkariga kira olmaydi. Shu bois ikkisi BITTA so'rovda, BITTA
    tranzaksiyada bajarilishi KERAK (`delete_my_account`).

    Bu fayl AYNAN shuni qadaydi — va teskarisini ham: yopgandan keyin
    qaytib kelishning imkoni YO'Q (manfiy nazorat). Agar kelajakda kimdir
    «yopilgandan keyin ham o'chirish yo'lini qo'shaylik» desa, u yopilgan
    ijarachi autentifikatsiyasini UMUMAN chetlab o'tmasligi kerak — shuning
    uchun bu yerda 401 KUTILADI, u xato emas, SHARTNOMA.

⚠️  YOPISH ≠ TENANT PURGE. Savdo/kassa/ombor daftarlari TEGILMAYDI va
    BOSHQA IJARACHILAR butunlay tegilmaydi — ikkisi ham quyida o'lchanadi.

HAJM HAQIDA: bu fayl 800 satrlik yumshoq chegaradan oshadi. Sabab — u BITTA
qabul hodisasining beshta bo'limi: A (atomik chiqish), B (so'rov ro'yxati),
C (qoldiq PII inventarizatsiyasi), D (bo'shatilgan ≠ o'chirilgan), E (vendor
yopishi). Bo'limlar AYNI urug' va yordamchilarni (`_daftar_barmoq_izi`,
`_pinli_telefonsiz`, `_pii_li_soni`) ulashadi; ularni fayllarga bo'lish
yordamchilarni ko'chirishga yoki yana bir umumiy modulga olib kelardi —
ikkisi ham qamrovni emas, faqat yo'lni o'zgartiradi. Repo qoidasi test
fayllariga bu istisnoni ATAYLAB beradi.
"""
from __future__ import annotations

import json
import uuid

from tests.test_ch18b_ochirish_yakuni import (
    PAROL, TASDIQ, _close, _db, _del_other, _del_self, _marker,
    _qator_matni, _shop, _token, _xodim, _yolgiz_ega,
)
from tests.test_ch18c_qattiqlashtirish import _ism, _pinli, _soralgan

PIN = "4721"


def _kompaniya(cid):
    from app.models.org import Company
    with _db() as db:
        c = db.get(Company, cid)
        return {"deleted_at": c.deleted_at, "status": c.status, "name": c.name}


def _sec_epoch(eid) -> int:
    from app.models.auth import Employee
    with _db() as db:
        return int(db.get(Employee, uuid.UUID(str(eid))).sec_epoch or 0)


def _push_qoshamiz(cid, eid) -> str:
    """Xodimga push qurilma tokeni beradi (yetkazish granti)."""
    from app.models.devices import DeviceToken
    belgi = f"CH18D-PUSH-{uuid.uuid4().hex}"
    with _db() as db:
        db.add(DeviceToken(company_id=cid, employee_id=uuid.UUID(str(eid)),
                           token=belgi, platform="ios"))
        db.commit()
    return belgi


def _push_soni(eid) -> int:
    from app.models.devices import DeviceToken
    with _db() as db:
        return (db.query(DeviceToken)
                .filter(DeviceToken.employee_id == uuid.UUID(str(eid))).count())


def _daftar_barmoq_izi(cid) -> str:
    """Moliyaviy/ombor daftarlarining O'ZGARMASLIGI uchun barmoq izi.

    ⚠️  Faqat SON emas, QIYMATLAR ham: yozuv soni o'zgarmasdan summalar
        qayta yozilsa, sanoq bunи ko'rmasdi."""
    from app.models.inventory import Inventory, StockBatch, StockMovement
    from app.models.sales import Sale, SaleItem
    izi: dict = {}
    with _db() as db:
        sotuvlar = db.query(Sale).filter(Sale.company_id == cid).order_by(Sale.id).all()
        izi["sales"] = [(str(s.id), str(s.total), str(s.cashier_id),
                         s.cashier_name_snapshot) for s in sotuvlar]
        sids = [s.id for s in sotuvlar]
        izi["sale_items"] = ([(str(i.id), str(i.qty), str(i.unit_price), str(i.unit_cost))
                              for i in db.query(SaleItem)
                              .filter(SaleItem.sale_id.in_(sids))
                              .order_by(SaleItem.id).all()] if sids else [])
        izi["batches"] = [(str(b.id), str(b.remaining_qty), str(b.unit_cost))
                          for b in db.query(StockBatch)
                          .filter(StockBatch.company_id == cid)
                          .order_by(StockBatch.id).all()]
        #  ⚠️  `StockMovement` va `Inventory` da `company_id` YO'Q — ular
        #      FILIAL orqali bog'langan, shu bois filial id'lari bo'yicha
        #      olinadi (taxmin qilib `company_id` yozsam, test jim bo'sh
        #      ro'yxatni qiyoslab «o'zgarmadi» deb YOLG'ON yashil berardi).
        from app.models.org import Branch
        bids = [b.id for b in db.query(Branch).filter(Branch.company_id == cid).all()]
        izi["movements"] = ([(str(m.id), str(m.qty), m.type, str(m.balance_after))
                             for m in db.query(StockMovement)
                             .filter(StockMovement.branch_id.in_(bids))
                             .order_by(StockMovement.id).all()] if bids else [])
        izi["inventory"] = ([(str(i.product_id), str(i.branch_id), str(i.qty))
                             for i in db.query(Inventory)
                             .filter(Inventory.branch_id.in_(bids))
                             .order_by(Inventory.product_id).all()] if bids else [])
    return json.dumps(izi, sort_keys=True)


def _sotuv_qilamiz(client, d):
    """Haqiqiy sotuv — API yo'li bilan, daftar yozuvlari paydo bo'lsin."""
    from tests.test_mobile_parity import _product, _staff
    kh, kid = _staff(d, "kassir")
    mahsulot = _product(d, qty=50)
    r = client.post("/api/v1/sales", headers=kh, json={
        "items": [{"product_id": str(mahsulot["id"]), "qty": 3}],
        "payment_method": "cash", "given_amount": 100000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code in (200, 201), (r.status_code, r.text[:300])
    return kid, r.json()["id"]


# ══ A1. ATOMIK CHIQISH — YOPISH + O'ZINI O'CHIRISH BITTA SO'ROVDA ═══════════

def test_A_YAGONA_EGA_BITTA_SOROVDA_yopadi_va_OZINI_ochiradi(client):
    """Spec A1-A6: vorisi yo'q yagona ega chiqadi; sessiya/push bekor bo'ladi;
    keraksiz PII anonimlashtiriladi; daftarlar BUTUN qoladi."""
    d = _shop()
    kid, sid = _sotuv_qilamiz(client, d)
    ega_id, nom = _yolgiz_ega(d)          # kassir ham `terminated` bo'ladi
    eh = _token(ega_id, "ega", d["cid"])
    _push_qoshamiz(d["cid"], ega_id)
    se_oldin = _sec_epoch(ega_id)
    daftar_oldin = _daftar_barmoq_izi(d["cid"])

    #  A1: holat YOPISH yo'lini ochiq ko'rsatadi (vorisi yo'q)
    st = client.get("/api/v1/auth/account-deletion", headers=eh).json()
    assert st["can_delete"] is False and st["store_closure_available"] is True, st
    assert st["transfer_candidates"] == [], st

    #  A2+A3: BITTA so'rov — oraliqda autentifikatsiya YO'QOLMAYDI
    r = _close(client, eh, delete_self=True)

    assert r.status_code == 200, (r.status_code, r.text[:300])
    j = r.json()
    assert j["closed"] is True and j["anonymized_employees"] == 1, j
    #  A5: eganing PII si yo'q
    assert nom not in _qator_matni(ega_id), "ega PII si QOLDI"
    #  A4: sessiya bekor (sec_epoch) + push tokeni yo'q
    assert _sec_epoch(ega_id) == se_oldin + 1, "sessiya bekor qilinmadi"
    assert _push_soni(ega_id) == 0, "push tokeni QOLDI"
    #  Do'kon yopilgan
    from app.models.enums import CompanyStatus
    comp = _kompaniya(d["cid"])
    assert comp["deleted_at"] is not None, comp
    assert comp["status"] == CompanyStatus.CLOSED.value, comp
    #  A6: daftarlar BAYT-BA-BAYT o'zgarmagan
    assert _daftar_barmoq_izi(d["cid"]) == daftar_oldin, "daftar O'ZGARDI"
    #  ... va chekdagi kassir ismi ATAYLAB joyida (CH-18C inventarizatsiyasi)
    assert kid is not None


def test_A_PAROL_NOTOGRI_bolsa_HECH_BIR_QADAM_bajarilmaydi(client):
    """Atomiklikning ikkinchi yuzi: rad etilgan so'rov YARIM holat qoldirmaydi."""
    d = _shop()
    ega_id, nom = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh, password="butunlay-boshqa-parol", delete_self=True)

    assert r.status_code == 403, (r.status_code, r.text[:200])
    assert _kompaniya(d["cid"])["deleted_at"] is None, "do'kon YOPILDI"
    assert nom in _qator_matni(ega_id), "PII o'chirildi"


def test_A_TASDIQ_SOZI_notogri_bolsa_HECH_NARSA_bolmaydi(client):
    d = _shop()
    ega_id, nom = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh, confirm="o'chirish", delete_self=True)

    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert _kompaniya(d["cid"])["deleted_at"] is None
    assert nom in _qator_matni(ega_id)


# ══ A2. MANFIY NAZORAT — YOPGANDAN KEYIN QAYTIB KELISH YO'Q ═════════════════

def test_A_YOPGANDAN_KEYIN_EGA_HECH_QAYERGA_KIRA_OLMAYDI(client):
    """⚠️  BU SHARTNOMA, XATO EMAS. Yopilgan ijarachi autentifikatsiyasi
    HAMMA uchun 401 — ega uchun ham. Shuning uchun `delete_my_account`
    yopish so'rovining O'ZIDA bo'lishi shart.

    Agar kimdir keyinchalik «yopilgandan keyin ham o'chirish» yo'lini
    qo'shsa, bu test QIZIL bo'ladi va u yopilgan ijarachi darvozasini
    chetlab o'tmaganini ALOHIDA isbotlash kerak bo'ladi."""
    d = _shop()
    ega_id, nom = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])
    assert _close(client, eh).status_code == 200          # SAYLOVSIZ yopdi

    #  PII hamon joyida — ega saylovni belgilamagan
    assert nom in _qator_matni(ega_id)
    #  ... va endi HECH QAYERGA kira olmaydi
    for metod, yol in (("get", "/api/v1/auth/account-deletion"),
                       ("post", "/api/v1/auth/account-deletion"),
                       ("post", "/api/v1/auth/account-deletion/request"),
                       ("get", "/api/v1/auth/store-closure"),
                       ("post", "/api/v1/auth/store-closure"),
                       ("get", "/api/v1/employees/deletion-requests")):
        r = (client.get(yol, headers=eh) if metod == "get"
             else client.post(yol, headers=eh,
                              json={"password": PAROL, "confirm": TASDIQ}))
        assert r.status_code == 401, (metod, yol, r.status_code)


def test_A_YOPILGAN_dokonda_PAROL_bilan_ham_KIRISH_YOQ(client):
    """Yangi token olish yo'li ham yopiq — ya'ni «qayta kiramanda» ishlamaydi."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])
    telefon = _telefon(ega_id)
    assert _close(client, eh).status_code == 200

    r = client.post("/api/v1/auth/login/password",
                    json={"phone": telefon, "password": PAROL})

    assert r.status_code in (401, 403), (r.status_code, r.text[:200])


def _telefon(eid) -> str:
    from app.models.auth import Employee
    with _db() as db:
        return db.get(Employee, uuid.UUID(str(eid))).phone


# ══ A3. BOSHQA IJARACHILAR TEGILMAYDI ═══════════════════════════════════════

def test_A_BOSHQA_IJAROCHI_va_uning_XODIMLARI_TEGILMAYDI(client):
    """Spec A7. Yopish faqat O'Z ijarachisiga tegadi."""
    begona = _shop()
    b_kid, _b_sid = _sotuv_qilamiz(client, begona)
    b_ega, b_nom = _xodim(begona, "ega")
    b_pin, _bph = _pinli(begona)
    b_pin_nom = _ism(b_pin)
    b_push = _push_qoshamiz(begona["cid"], b_pin)
    b_daftar = _daftar_barmoq_izi(begona["cid"])
    b_comp = _kompaniya(begona["cid"])

    meni = _shop()
    m_ega, _ = _yolgiz_ega(meni)
    mh = _token(m_ega, "ega", meni["cid"])
    assert _close(client, mh, delete_self=True).status_code == 200

    #  Begona ijarachi: kompaniya, PII, push va daftar — hammasi JOYIDA
    assert _kompaniya(begona["cid"]) == b_comp, "begona kompaniya o'zgardi"
    assert b_nom in _qator_matni(b_ega), "begona ega PII si o'chdi"
    assert b_pin_nom in _qator_matni(b_pin), "begona xodim PII si o'chdi"
    assert _push_soni(b_pin) == 1, f"begona push tokeni o'chdi ({b_push})"
    assert _daftar_barmoq_izi(begona["cid"]) == b_daftar, "begona daftar o'zgardi"
    #  ... va u hamon ishlaydi
    bh = _token(b_ega, "ega", begona["cid"])
    assert client.get("/api/v1/auth/account-deletion", headers=bh).status_code == 200
    assert b_kid is not None


# ══ A4. ROZILIK BERGANLAR + EGA BIR VAQTDA ══════════════════════════════════

def test_A_YOPISHDA_ROZILIK_berganlar_va_EGA_BIRGA_ochiriladi(client):
    """Ega saylovni belgilaydi VA kutayotgan so'rovlar bor — hammasi BITTA
    tranzaksiyada bajariladi, push tokenlari ham ketadi."""
    d = _shop()
    ega_id, ega_nom = _yolgiz_ega(d)  # CH-23: YAGONA rahbar (sherik Ega/Administrator bo'lsa yopish 409)
    eh = _token(ega_id, "ega", d["cid"])
    a_id, ah = _pinli(d)
    b_id, bh = _pinli(d)
    jim_id, _jh = _pinli(d)
    jim_nom = _ism(jim_id)
    for h in (ah, bh):
        assert _soralgan(client, h).status_code == 200
    for eid in (ega_id, a_id, b_id, jim_id):
        _push_qoshamiz(d["cid"], eid)

    pv = client.get("/api/v1/auth/store-closure", headers=eh).json()
    r = _close(client, eh, delete_self=True)

    assert r.status_code == 200, (r.status_code, r.text[:300])
    j = r.json()
    #  2 so'rov + eganing O'ZI = 3
    assert j["anonymized_employees"] == pv["pending_requests"] + 1 == 3, (pv, j)
    for eid in (ega_id, a_id, b_id):
        assert _push_soni(eid) == 0, f"{eid} push tokeni qoldi"
    assert ega_nom not in _qator_matni(ega_id)
    #  So'ramagan xodim: PII va push JOYIDA — hech kim uni o'chirishni so'ramagan
    assert jim_nom in _qator_matni(jim_id), "so'ramagan xodim anonimlashtirildi"
    assert _push_soni(jim_id) == 1, "so'ramagan xodim push tokeni o'chdi"
    assert j["pii_retained_employees"] >= 1, j
    #  Osilib qolgan so'rov YO'Q
    from app.services import account_deletion as _AD
    with _db() as db:
        assert _AD.list_requests(db, d["cid"]) == []


# ══ A5. SAYLOV STANDART O'CHIQ ══════════════════════════════════════════════

def test_A_SAYLOV_STANDART_OCHIQ_mijoz_yubormasa_ham(client):
    """Eski mijoz `delete_my_account` ni UMUMAN yubormasa — ega PII si QOLADI.
    Jim o'chirish tasdiqlanmagan qaytarilmas amal bo'lardi."""
    d = _shop()
    ega_id, nom = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])

    #  Maydon YO'Q — eski mijoz shunday yuboradi
    r = client.post("/api/v1/auth/store-closure", headers=eh,
                    json={"password": PAROL, "confirm": TASDIQ})

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.json()["anonymized_employees"] == 0, r.json()
    assert nom in _qator_matni(ega_id), "saylovsiz PII o'chirildi"


def test_A_SAYLOV_FAQAT_EGANING_OZIGA_tegadi(client):
    """`delete_my_account` boshqa hisobni o'chirish vositasiga aylanmaydi."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)  # CH-23: YAGONA rahbar (sherik Ega/Administrator bo'lsa yopish 409)
    eh = _token(ega_id, "ega", d["cid"])
    boshqa_id, _ = _xodim(d, "menejer")
    boshqa_nom = _ism(boshqa_id)

    assert _close(client, eh, delete_self=True).status_code == 200

    assert boshqa_nom in _qator_matni(boshqa_id), "begona hisob o'chirildi"


# ══ B. SO'ROV RO'YXATI — AYNI TRANZAKSIYADA KO'P YOZISH ═════════════════════

def test_B_AYNI_TRANZAKSIYADA_IKKI_sorov_OLIB_TASHLANADI(client):
    """⚠️  `_requests_row(lock=True)` dagi `db.flush()` ni QADAYDI.

    `populate_existing()` obyektni bazadan QAYTA YUKLAYDI. Flush bo'lmasa,
    ayni tranzaksiyadagi ikkinchi `clear_request` birinchisining hali
    yozilmagan natijasini JIM BOSIB TASHLAYDI va BITTA so'rov ro'yxatda
    qolib ketadi. Yopish yo'li endi bitta yozuv qiladi, ya'ni bu holatga
    tushmaydi — lekin `clear_request` OMMAVIY API va marshrutlar uni
    chaqiradi, shu bois xulq SHU YERDA qadalgan."""
    from app.services import account_deletion as _AD

    d = _shop()
    a_id, ah = _pinli(d)
    b_id, bh = _pinli(d)
    for h in (ah, bh):
        assert _soralgan(client, h).status_code == 200
    with _db() as db:
        assert len(_AD.list_requests(db, d["cid"])) == 2, "nazorat: ikkita bo'lishi kerak"

    with _db() as db:
        _AD.clear_request(db, d["cid"], a_id)
        _AD.clear_request(db, d["cid"], b_id)      # AYNI tranzaksiya
        db.commit()

    with _db() as db:
        assert _AD.list_requests(db, d["cid"]) == [], \
            "ikkinchi chaqiruv birinchisini bosib ketdi"


def test_B_SOROV_qatori_YOQ_bolsa_clear_request_QATOR_YARATMAYDI(client):
    """Bo'sh qator keraksiz yozuv bo'lardi — o'chiradigan narsa yo'q."""
    from app.models.settings import Setting
    from app.services import account_deletion as _AD

    d = _shop()
    xodim_id, _ = _xodim(d, "kassir")

    with _db() as db:
        _AD.clear_request(db, d["cid"], xodim_id)
        db.commit()

    with _db() as db:
        assert db.query(Setting).filter(
            Setting.company_id == d["cid"],
            Setting.key == _AD.REQUESTS_KEY).count() == 0, "keraksiz qator yaratildi"


def test_B_SOROV_ROYXATI_umumiy_PUT_settings_orqali_YOZILMAYDI(client):
    """Ro'yxat umumiy sozlama yo'lidan SOXTALASHTIRILMAYDI (CH-18B qoidasi
    CH-18D da ham kuchda — qulf qo'shilgandan keyin ham)."""
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    boshqa_id, _ = _xodim(d, "kassir")

    r = client.put("/api/v1/settings", headers=eh, json={
        "key": "account_deletion_requests",
        "value": {"items": [{"employee_id": str(boshqa_id), "at": "2026-01-01T00:00:00Z"}]}})

    assert r.status_code in (400, 403, 422), (r.status_code, r.text[:200])
    from app.services import account_deletion as _AD
    with _db() as db:
        assert _AD.list_requests(db, d["cid"]) == [], "soxta so'rov yozildi"


# ══ C. QOLDIQ SHAXSIY MA'LUMOT — BAJARILADIGAN INVENTARIZATSIYA ═════════════
#
#  ⚠️  HUJJAT EMAS, TEST. CH-18C da qoldiq PII `QOLDIQ-PII-INVENTARIZATSIYASI.md`
#      da YOZILGAN edi — matn esa kod bilan birga qarimaydi. Bu yerda ayni
#      ro'yxat BAJARILADIGAN shaklda: ism o'chirishdan keyin AYNAN qaysi
#      (jadval, ustun) juftlarida qolishi KUTILADI. Yangi joyda paydo bo'lsa
#      ham, kutilgan joydan yo'qolsa ham — test QIZIL bo'ladi va hujjatni
#      yangilash MAJBUR qiladi.

#: O'chirishdan KEYIN ism QOLADIGAN joylar. Har biri ATAYLAB va ASOSI bilan.
KUTILGAN_QOLDIQ = {
    #  `SALE_AUDIT_IDENTITY.md` §Snapshots: chek qayta ishlab chiqarilishi
    #  uchun muzlatilgan satr. `sales` append-only FISKAL yozuv.
    ("sales", "cashier_name_snapshot"),
}


def test_C_OCHIRISHDAN_KEYIN_ISM_AYNAN_KUTILGAN_JOYLARDA_qoladi(client):
    """REALISTIK xodim: sotgan, qabul qilgan, qurilma ro'yxatdan o'tkazgan,
    audit izi qoldirgan. O'chirilgandan keyin butun baza bo'ylab sweep."""
    from tests.test_ch18b_ochirish_yakuni import _baza_sweep

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    nom = _marker("QOLDIQ-NOM")

    #  Kassir ismini markerga almashtiramiz, so'ng u SOTADI
    from tests.test_mobile_parity import _product, _staff
    kh, kid = _staff(d, "kassir")
    with _db() as db:
        from app.models.auth import Employee
        db.get(Employee, kid).full_name = nom
        db.commit()
    mahsulot = _product(d, qty=50)
    r = client.post("/api/v1/sales", headers=kh, json={
        "items": [{"product_id": str(mahsulot["id"]), "qty": 2}],
        "payment_method": "cash", "given_amount": 100000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code in (200, 201), (r.status_code, r.text[:300])
    #  Audit izi: ega uni tahrirlaydi (nom audit yuklamasiga tushadi)
    client.patch(f"/api/v1/employees/{kid}", headers=eh, json={"full_name": nom})
    _push_qoshamiz(d["cid"], kid)

    oldin = {(t, c) for t, c, _ in _baza_sweep(nom)}
    assert oldin, "POZITIV NAZORAT YIQILDI — sweep hech narsa ko'rmaydi"
    assert ("employees", "full_name") in oldin, oldin
    assert ("sales", "cashier_name_snapshot") in oldin, oldin

    assert _del_other(client, eh, str(kid)).status_code == 200

    keyin = {(t, c) for t, c, _ in _baza_sweep(nom)}
    assert keyin == KUTILGAN_QOLDIQ, (
        f"qoldiq PII ro'yxati O'ZGARDI — hujjatni ham yangilang.\n"
        f"  kutilgan: {sorted(KUTILGAN_QOLDIQ)}\n"
        f"  topilgan: {sorted(keyin)}\n"
        f"  (yangi joy paydo bo'lsa — yo tozalash kerak, yo ATAYLABLIGINI "
        f"asoslab KUTILGAN_QOLDIQ ga qo'shish kerak)")


def test_C_QABUL_HUJJATI_va_LEGACY_RASM_TEGILMAYDI(client):
    """`receivings` — BIZNES HUJJATI: o'chirish unga tegmaydi.

    ⚠️  SHUNI OCHIQ AYTAMIZ: `image_b64` va `ai_raw` — LEGACY ustunlar
        (yangi qatorlarda yozilmaydi), lekin MAVJUD qatorlarda hisob-faktura
        RASMI turadi va rasmda CHOP ETILGAN ismlar bo'lishi mumkin. Hisob
        o'chirish ularni tozalamaydi va repoda tozalash vositasi YO'Q —
        bu CH-15B Faza C, ega tasdiqlaydigan alohida amal.

    ⚠️  `receivings.employee_id` — NOT NULL, ya'ni bog'lanish SAQLANADI.
        Buni uzish FK ni buzardi va «kim qabul qildi» javobgarligini
        yo'qotardi."""
    from app.models.receiving import Receiving

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    kid, _ = _xodim(d, "omborchi")
    rasm = "data:image/jpeg;base64,/9j/" + "A" * 64
    from app.models.org import Branch
    with _db() as db:
        bid = db.query(Branch).filter(Branch.company_id == d["cid"]).first().id
        rec = Receiving(id=uuid.uuid4(), company_id=d["cid"], branch_id=bid,
                        employee_id=uuid.UUID(kid), source="ai",
                        image_b64=rasm, ai_raw=[{"name": "LEGACY XOM"}],
                        final_items=[], total_types=0, total_qty=0)
        db.add(rec)
        db.commit()
        rid = rec.id

    assert _del_other(client, eh, kid).status_code == 200

    with _db() as db:
        rec = db.get(Receiving, rid)
        assert rec is not None, "qabul hujjati O'CHIRILDI"
        assert rec.image_b64 == rasm, "legacy rasm o'zgartirildi"
        assert rec.ai_raw == [{"name": "LEGACY XOM"}], "legacy AI o'qishi o'zgartirildi"
        assert str(rec.employee_id) == str(kid), "employee_id uzildi"


def test_C_AUDIT_AKTYOR_bogi_SAQLANADI_PII_esa_YOQ(client):
    """Audit javobgarligi: `actor_id` QOLADI (kim qildi), ism/telefon esa YO'Q."""
    from app.models.sync import AuditLog

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    nom = _marker("AKTYOR")
    kid, _ = _xodim(d, "menejer", nom=nom)
    client.patch(f"/api/v1/employees/{kid}", headers=eh, json={"full_name": nom})

    assert _del_other(client, eh, kid).status_code == 200

    with _db() as db:
        izlar = db.query(AuditLog).filter(
            AuditLog.entity_id == uuid.UUID(kid)).all()
        assert izlar, "audit izi butunlay o'chirildi — javobgarlik yo'qoldi"
        for a in izlar:
            matn = json.dumps([a.before, a.after], ensure_ascii=False)
            assert nom not in matn, f"audit yuklamasida ism QOLDI: {matn[:200]}"
        #  Aktyor bog'lanishi — o'chirilgan odam BAJARGAN amallar uchun
        aktyor = db.query(AuditLog).filter(
            AuditLog.actor_id == uuid.UUID(ega_id)).count()
        assert aktyor >= 1, "actor_id bog'lanishi yo'qoldi"


def test_B_UCH_KUTAYOTGAN_sorov_BITTALAB_bajariladi(client):
    """Ega uchta so'rovni MARSHRUT orqali bittalab bajaradi — har bajarish
    FAQAT o'zini ro'yxatdan oladi, qolganlariga TEGMAYDI."""
    from app.services import account_deletion as _AD

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    xodimlar = [_pinli(d) for _ in range(3)]
    for _eid, h in xodimlar:
        assert _soralgan(client, h).status_code == 200
    qolgan = {eid for eid, _h in xodimlar}

    for eid, _h in xodimlar:
        lst = client.get("/api/v1/employees/deletion-requests", headers=eh)
        assert lst.status_code == 200
        assert {x["employee_id"] for x in lst.json()} == qolgan, (eid, lst.json())

        assert _del_other(client, eh, eid).status_code == 200

        qolgan.discard(eid)
        with _db() as db:
            assert {str(it["employee_id"]) for it in _AD.list_requests(db, d["cid"])} \
                == qolgan, f"{eid} bajarilgach ro'yxat buzildi"

    assert client.get("/api/v1/employees/deletion-requests", headers=eh).json() == []


def test_B_EGA_JAVOB_BERMASA_holat_KUTILMOQDA_va_ESKALATSIYA_YOQ(client):
    """⚠️  OCHIQ AYTILADIGAN BO'SHLIQ. Ega umuman javob bermasa, xodim
    muddatsiz «kutilmoqda» holatida qoladi: serverda avtomatik bajarish,
    muddat yoki vendor eskalatsiyasi YO'Q va men ularni O'YLAB TOPMAYMAN
    (ega qarori). Bu test shu holatni QADAYDI — kelajakda eskalatsiya
    qo'shilsa, u shu yerda ko'rinadi va qasddan bo'ladi."""
    d = _shop()
    _xodim(d, "ega")
    pid, ph = _pinli(d)
    assert _soralgan(client, ph).status_code == 200

    #  Vaqt o'tishi hech narsani o'zgartirmaydi: server tomonda taymer yo'q
    st = client.get("/api/v1/auth/account-deletion", headers=ph).json()

    assert st["request"]["pending"] is True, st
    assert st["request"]["requested_at"], st
    #  Hisob HAMON ishlaydi — jim o'chirilmaydi
    assert client.get("/api/v1/auth/account-deletion", headers=ph).status_code == 200
    #  ... va PII joyida
    assert _ism(pid), "ism bo'sh — jim o'chirilgan"


# ══ D. «ISHDAN BO'SHATILGAN» ≠ «O'CHIRILGAN» ════════════════════════════════
#
#  ⚠️  ILDIZ SABAB. `DELETE /employees/{id}` (ishdan bo'shatish) `deleted_at`
#      ni o'rnatadi, lekin PII ga TEGMAYDI — bu ataylab. Lekin `is_deleted()`
#      «o'chirilgan» ni UCHTA shart bilan aniqlardi:
#          deleted_at bor  VA  parol yo'q  VA  telefon yo'q
#      PIN'li xodimning telefoni NULL bo'lishi MUMKIN (telefon faqat PAROLLI
#      xodim uchun majburiy — `api/v1/employees.py:335`). Shunda ishdan
#      bo'shatilgan PIN'li xodim uchta shartni ham QONDIRADI va:
#        · `POST /employees/{id}/account-deletion` «repeated: true» deb
#          QAYTADI — anonimlashtirish BAJARILMAYDI, ism va PIN hash QOLADI;
#        · `close_store` uni `deleted_at IS NULL` filtri bilan CHETLAB o'tadi;
#        · yopish preview'i uni PII hisobiga QO'SHMAYDI.
#      Natija: API «o'chirildi» deydi, ma'lumot esa QOLADI. Bu YOLG'ON
#      JAVOB — Apple 5.1.1(v) nuqtai nazaridan ham eng yomon holat.

def _pii_li_soni(cid) -> int:
    """Bazada HAMON shaxsiy ma'lumot turgan qatorlar soni — haqiqat manbai."""
    from app.models.auth import Employee
    from app.services import account_deletion as _AD
    with _db() as db:
        return sum(1 for e in db.query(Employee)
                   .filter(Employee.company_id == cid).all() if _AD.pii_retained(e))


def _pinli_telefonsiz(d, *, nom=None):
    """PIN'li, TELEFONI YO'Q xodim — repoda ruxsat etilgan holat."""
    from app.core.security import hash_password
    from app.models.auth import Employee, Role
    from app.models.enums import EmployeeStatus
    with _db() as db:
        r = db.query(Role).filter(Role.code == "kassir").one()
        e = Employee(id=uuid.uuid4(), company_id=d["cid"], role_id=r.id,
                     full_name=nom or _marker("TELEFONSIZ"),
                     phone=None, password_hash=None,
                     pin_hash=hash_password(PIN),
                     status=EmployeeStatus.active, sec_epoch=0)
        db.add(e)
        db.commit()
        return str(e.id), e.full_name


def test_D_BOSHATILGAN_PINLI_xodim_HAQIQATAN_ochiriladi(client):
    """Ishdan bo'shatilgandan KEYIN ham o'chirish ISHLASHI kerak."""
    from app.models.devices import DeviceToken

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    pid, nom = _pinli_telefonsiz(d)
    _push_qoshamiz(d["cid"], pid)
    se_oldin = _sec_epoch(pid)

    #  1) Ishdan bo'shatish — PII ga TEGMAYDI va buni ochiq aytadi
    r1 = client.delete(f"/api/v1/employees/{pid}", headers=eh)
    assert r1.status_code == 200, (r1.status_code, r1.text[:200])
    assert r1.json()["pii_retained"] is True, r1.json()
    assert nom in _qator_matni(pid)

    #  2) Javobda ko'rsatilgan yo'l ROSTDAN ishlashi kerak
    yol = r1.json()["account_deletion_path"]
    r2 = client.post(f"/api/v1{yol}", headers=eh,
                     json={"password": PAROL, "confirm": TASDIQ})

    assert r2.status_code == 200, (r2.status_code, r2.text[:200])
    assert r2.json()["repeated"] is False, (
        "«repeated» deb qaytdi — anonimlashtirish BAJARILMADI, "
        f"javob YOLG'ON: {r2.json()}")
    assert nom not in _qator_matni(pid), "ism QOLDI"
    with _db() as db:
        from app.models.auth import Employee
        e = db.get(Employee, uuid.UUID(pid))
        assert e.pin_hash is None, "PIN hash QOLDI"
        assert db.query(DeviceToken).filter(
            DeviceToken.employee_id == uuid.UUID(pid)).count() == 0, "push tokeni QOLDI"
    assert _sec_epoch(pid) == se_oldin + 1, "sessiya bekor qilinmadi"


def test_D_BOSHATILGAN_xodim_YOPISHDA_ham_hisobga_olinadi(client):
    """Ishdan bo'shatilgan, lekin PII si turgan xodim yopish preview'ida
    KO'RINISHI kerak — ega ko'rgan son bazadagi haqiqatga mos bo'lsin."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)  # CH-23: YAGONA rahbar (sherik Ega/Administrator bo'lsa yopish 409)
    eh = _token(ega_id, "ega", d["cid"])
    bosh_id, bosh_nom = _pinli_telefonsiz(d)
    assert client.delete(f"/api/v1/employees/{bosh_id}", headers=eh).status_code == 200
    assert bosh_nom in _qator_matni(bosh_id), "nazorat: PII turishi kerak"

    #  ⚠️  Kutilgan sonni QATTIQ yozmaymiz — BAZADAN hisoblaymiz. Qattiq
    #      yozilganda test tasodifan o'tib ketgan edi (`_shop()` o'zi ham
    #      xodim yaratadi), ya'ni u NOTO'G'RI SABABDAN yashil edi.
    kutilgan = _pii_li_soni(d["cid"])

    pv = client.get("/api/v1/auth/store-closure", headers=eh).json()

    assert kutilgan >= 2, f"nazorat: kamida ega + bo'shatilgan bo'lishi kerak ({kutilgan})"
    assert pv["employees_with_pii"] == kutilgan, (
        f"ega ko'rgan son bazadagidan FARQ qiladi: preview={pv} baza={kutilgan}")
    assert pv["pii_retained_after_closure"] == kutilgan, pv
    r = _close(client, eh)
    assert r.status_code == 200
    assert r.json()["pii_retained_employees"] == kutilgan, r.json()


def test_D_BOSHATILGAN_xodim_SOROVI_YOPISHDA_BAJARILADI(client):
    """⚠️  So'rov yuborgan, keyin ishdan bo'shatilgan xodim UNUTILMAYDI.
    Ilgari uning so'rovi ega ro'yxatidan ko'rinmas bo'lib qolardi va
    yopishda ham bajarilmasdi — ya'ni u abadiy «kutilmoqda» va PII si
    bazada qolardi."""
    from app.services import account_deletion as _AD

    d = _shop()
    ega_id, _ = _yolgiz_ega(d)  # CH-23: YAGONA rahbar (sherik Ega/Administrator bo'lsa yopish 409)
    eh = _token(ega_id, "ega", d["cid"])
    pid, nom = _pinli_telefonsiz(d)
    ph = _token(pid, "kassir", d["cid"])
    assert _soralgan(client, ph).status_code == 200
    assert client.delete(f"/api/v1/employees/{pid}", headers=eh).status_code == 200

    r = _close(client, eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert nom not in _qator_matni(pid), (
        "rozilik bergan, keyin bo'shatilgan xodim PII si QOLDI")
    with _db() as db:
        assert _AD.list_requests(db, d["cid"]) == [], "osilib qolgan so'rov"


def test_D_is_deleted_FAQAT_anonimlashtirish_belgisiga_qaraydi(client):
    """Birlik darajasida: hisob o'chirilganmi — ANONIMLASHTIRISH BELGISI
    bo'yicha aniqlanadi, parol/telefon YO'QLIGI bo'yicha EMAS."""
    from app.models.auth import Employee
    from app.services import account_deletion as _AD

    d = _shop()
    pid, _ = _pinli_telefonsiz(d)
    with _db() as db:
        e = db.get(Employee, uuid.UUID(pid))
        assert _AD.is_deleted(e) is False, "faol xodim o'chirilgan deb topildi"
        #  Ishdan bo'shatish: `deleted_at` bor, PII JOYIDA
        from datetime import datetime, timezone
        e.deleted_at = datetime.now(timezone.utc)
        db.commit()
        e = db.get(Employee, uuid.UUID(pid))

        assert _AD.is_deleted(e) is False, (
            "ishdan bo'shatilgan xodim «o'chirilgan» deb topildi — "
            "o'chirish jim o'tkazib yuborilardi")

    #  Haqiqiy anonimlashtirishdan KEYIN — True
    with _db() as db:
        e = db.get(Employee, uuid.UUID(pid))
        _AD.anonymize(db, e)
        db.commit()
    with _db() as db:
        assert _AD.is_deleted(db.get(Employee, uuid.UUID(pid))) is True


def test_D_BOSHATILGAN_xodim_SOROVI_EGA_ROYXATIDA_KORINADI(client):
    """So'rov yuborgan, keyin ishdan bo'shatilgan xodim ega ro'yxatidan
    G'OYIB BO'LMAYDI — aks holda ega uni bajara olmaydi va xodim abadiy
    «kutilmoqda» holatida qolardi."""
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    pid, nom = _pinli_telefonsiz(d)
    ph = _token(pid, "kassir", d["cid"])
    assert _soralgan(client, ph).status_code == 200
    assert client.delete(f"/api/v1/employees/{pid}", headers=eh).status_code == 200

    lst = client.get("/api/v1/employees/deletion-requests", headers=eh)

    assert lst.status_code == 200, (lst.status_code, lst.text[:200])
    assert [x["employee_id"] for x in lst.json()] == [pid], (
        f"bo'shatilgan xodimning so'rovi ro'yxatdan G'OYIB bo'ldi: {lst.json()}")
    assert lst.json()[0]["full_name"] == nom, lst.json()

    #  ... va ega uni BAJARA oladi
    assert _del_other(client, eh, pid).status_code == 200
    assert nom not in _qator_matni(pid)
    #  Bajarilgach ro'yxatdan chiqadi
    assert client.get("/api/v1/employees/deletion-requests", headers=eh).json() == []


def test_D_HAQIQATAN_ochirilgan_xodim_ROYXATDA_KORINMAYDI(client):
    """Teskari tomoni: anonimlashtirilgan hisob ro'yxatda qolmaydi —
    bajarish kerak bo'lgan ish yo'q."""
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    pid, ph = _pinli(d)
    assert _soralgan(client, ph).status_code == 200
    assert _del_other(client, eh, pid).status_code == 200

    assert client.get("/api/v1/employees/deletion-requests", headers=eh).json() == []


# ══ E. VENDOR IJARACHINI YOPSA — EGA QARORI KUTILADI ════════════════════════
#
#  ⚠️  BU TEST HOZIRGI XULQNI QADAYDI, UNI TUZATMAYDI. `DELETE
#      /admin/companies/{id}` (`api/v1/admin.py:1013`) `Company.deleted_at`
#      ni o'rnatadi va xodimlarga TEGMAYDI. Shundan keyin ijarachining HAR
#      BIR yo'li 401 bo'ladi: xodim so'rovini ko'rmaydi, ega ro'yxatni
#      ochmaydi va `POST /auth/store-closure` — hujjatlashtirilgan yagona
#      chiqish yo'li — O'ZI ham 401. Kutayotgan so'rov va PII bazada qoladi.
#
#      Men buni O'Z QARORIM bilan tuzatmayman: uchta yo'ldan har biri
#      QAYTARILMAS anonimlashtirishni KIM boshlashi mumkinligini
#      o'zgartiradi (vendor avtomatik bajarsinmi? vendorga alohida yo'l
#      berilsinmi? kutayotgan so'rov bo'lsa vendor yo'li to'silsinmi?) —
#      bu biznes/huquqiy qaror, texnik tanlov emas. Hisobotda AYNIQ shunday
#      yozilgan.
#
#      Test hozirgi holatni qadaydi, ya'ni xulq o'zgarsa (yaxshi tomonga
#      ham) bu yerda KO'RINADI va qasddan bo'ladi.

_VENDOR = {"X-Vendor-Key": "test-vendor-key"}


def test_E_VENDOR_YOPISHI_kutayotgan_SOROVNI_YETIM_QOLDIRADI(client):
    """HOZIRGI xulq: vendor yopishi so'rovni bajarmaydi va keyin hech kim
    unga yeta olmaydi. EGA QARORI kutilmoqda (hisobotga qara)."""
    from app.services import account_deletion as _AD

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    pid, nom = _pinli_telefonsiz(d)
    ph = _token(pid, "kassir", d["cid"])
    assert _soralgan(client, ph).status_code == 200

    r = client.delete(f"/api/v1/admin/companies/{d['cid']}", headers=_VENDOR)
    assert r.status_code == 200, (r.status_code, r.text[:200])

    #  Ijarachining HAMMA yo'li yopiq
    assert client.get("/api/v1/auth/account-deletion", headers=ph).status_code == 401
    assert client.get("/api/v1/employees/deletion-requests", headers=eh).status_code == 401
    assert _close(client, eh).status_code == 401
    #  So'rov ham, PII ham QOLADI — bu hujjatlashtirilgan bo'shliq
    assert nom in _qator_matni(pid), "PII (kutilmaganda) o'chirilgan"
    with _db() as db:
        qolgan = [str(it.get("employee_id")) for it in _AD.list_requests(db, d["cid"])]
    assert qolgan == [pid], f"so'rov holati o'zgardi: {qolgan}"


def test_E_VENDOR_YOPISHI_BOSHQA_ijarachiga_TEGMAYDI(client):
    """Vendor yopishi ham ijarachi doirasida qoladi."""
    begona = _shop()
    b_ega, b_nom = _xodim(begona, "ega")
    bh = _token(b_ega, "ega", begona["cid"])
    meni = _shop()
    _xodim(meni, "ega")

    assert client.delete(f"/api/v1/admin/companies/{meni['cid']}",
                         headers=_VENDOR).status_code == 200

    assert client.get("/api/v1/auth/account-deletion", headers=bh).status_code == 200
    assert b_nom in _qator_matni(b_ega)


def test_D_HOLAT_va_MARSHRUT_bir_xil_narsani_aytadi(client):
    """⚠️  API O'ZIGA ZID javob BERMAYDI. Ilgari holat PIN'li xodim uchun
    `can_delete: true` deb qaytarardi, marshrut esa 400 bilan rad etardi —
    «mumkin» deb aytib, keyin rad etish."""
    d = _shop()
    _xodim(d, "ega")
    pid, ph = _pinli(d)

    st = client.get("/api/v1/auth/account-deletion", headers=ph).json()
    r = client.post("/api/v1/auth/account-deletion", headers=ph,
                    json={"password": "nima-bo'lsa", "confirm": TASDIQ})

    assert st["needs_password"] is False, st
    assert st["can_delete"] is False, (
        f"holat «mumkin» deydi, marshrut esa {r.status_code} beradi: {st}")
    assert "no_password" in st["blockers"], st
    assert r.status_code == 400, (r.status_code, r.text[:200])
    #  To'g'ri yo'l OCHIQ ko'rsatilgan
    assert _soralgan(client, ph).status_code == 200


def test_D_PAROLLI_xodim_holati_can_delete_TRUE_bolib_qoladi(client):
    """Teskari nazorat: yangi blok parolli xodimga TEGMAYDI."""
    d = _shop()
    _xodim(d, "ega")
    eid, _ = _xodim(d, "menejer")          # parolli
    h = _token(eid, "menejer", d["cid"])

    st = client.get("/api/v1/auth/account-deletion", headers=h).json()

    assert st["needs_password"] is True and st["can_delete"] is True, st
    assert st["blockers"] == [], st
    assert _del_self(client, h).status_code == 200

# ══ E. CH-23 — YOPISHNING IKKI SHARTI ═══════════════════════════════════════
#
# Ega qarori: do'konni FAQAT OXIRGI rahbar yopadi. Ochiq smena to'sig'i
# 2026-10-17 da OLIB TASHLANDI (ega qarori) — pastdagi
# `test_E_OCHIQ_SMENA_TOSMAYDI_...` shuni qadaydi. Sabab: yopish
# `Company.deleted_at` yozadi, undan keyin
# `core/deps.py:37-39` do'kondagi HAR BIR xodimga HAR BIR marshrutda 401
# beradi, va butun repoda `Company.deleted_at` NULL ga QAYTARILMAYDI —
# ya'ni bitta ega sheriklarini qaytarib bo'lmaydigan tarzda chiqarib
# yuborardi.


def _ochiq_smena(d, kassir_id, *, bid=None):
    """Do'konning filialida OCHIQ smena yaratadi va uning id sini qaytaradi."""
    from datetime import datetime, timezone
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    with _db() as db:
        sh = Shift(id=uuid.uuid4(), branch_id=bid or d["bids"][0],
                   cashier_id=uuid.UUID(str(kassir_id)),
                   opened_at=datetime.now(timezone.utc),
                   opening_cash=0, status=ShiftStatus.open)
        db.add(sh)
        db.commit()
        return sh.id


def test_E_SHERIK_EGA_bolsa_YOPISH_409_va_dokon_OCHIQ_qoladi(client):
    """Sherik EGA bor — yopish RAD etiladi va do'kon holati TEGILMAYDI."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    _xodim(d, "ega")                      # ikkinchi, FAOL ega
    eh = _token(ega_id, "ega", d["cid"])
    oldin = _kompaniya(d["cid"])

    r = _close(client, eh)

    assert r.status_code == 409, (r.status_code, r.text[:200])
    #  Holat BIR BAYTGA ham o'zgarmadi — bu 409 ning asosiy ma'nosi.
    assert _kompaniya(d["cid"]) == oldin, (oldin, _kompaniya(d["cid"]))


def test_E_SHERIK_ADMINISTRATOR_bolsa_ham_YOPISH_409(client):
    """Administrator ham rahbar: u ham kirishdan mahrum bo'lardi."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    _xodim(d, "administrator")
    eh = _token(ega_id, "ega", d["cid"])
    oldin = _kompaniya(d["cid"])

    r = _close(client, eh)

    assert r.status_code == 409, (r.status_code, r.text[:200])
    assert _kompaniya(d["cid"]) == oldin


def test_E_BOSHATILGAN_sherik_TOSMAYDI(client):
    """⚠️  To'siq FAOL rahbarlar uchun. Ishdan bo'shatilgan ega kira olmaydi,
    ya'ni undan mahrum bo'ladigan kirish YO'Q — u yopishni to'smaydi.
    (Predikat `_active_peers` bilan AYNI: `status == active`.)"""
    from app.models.auth import Employee
    from app.models.enums import EmployeeStatus
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    sherik_id, _ = _xodim(d, "ega")
    with _db() as db:
        db.get(Employee, uuid.UUID(str(sherik_id))).status = EmployeeStatus.terminated
        db.commit()
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert _kompaniya(d["cid"])["deleted_at"] is not None


def test_E_KASSIR_va_MENEJER_TOSMAYDI(client):
    """To'siq FAQAT `ega`/`administrator` uchun — boshqa rollar yopishni
    to'smaydi (aks holda xodimi bor do'kon umuman yopilmasdi)."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    _xodim(d, "kassir")
    _xodim(d, "menejer")
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])


def test_E_OCHIQ_SMENA_TOSMAYDI_va_smena_QATORI_TEGILMAYDI(client):
    """Ega qarori (2026-10-17): ochiq smena do'konni yopishni TO'SMAYDI.

    ⚠️  Ilgari bu test 409 kutardi. Sabab o'rinli edi (smenani yopish
        kassirning O'ZINI talab qiladi, do'kon yopilgach u kira olmaydi), lekin
        oqibati og'irroq edi: YAGONA ega o'z hisobini o'chirmoqchi bo'lsa
        do'konni yopish SHART, va ochiq smena uni butunlay qulflab qo'yardi.
    ⚠️  SMENA AVTOMATIK YOPILMAYDI va O'CHIRILMAYDI — qator tegilmagan qoladi,
        ya'ni moliyaviy tarix va naqd qoldiq hisobi saqlanadi.
    """
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    kassir_id, _ = _xodim(d, "kassir")
    sid = _ochiq_smena(d, kassir_id)
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert _kompaniya(d["cid"])["deleted_at"] is not None
    with _db() as db:
        sh = db.get(Shift, sid)
        assert sh is not None, "smena qatori o'chirilgan"
        assert sh.status == ShiftStatus.open, sh.status
        assert sh.deleted_at is None


def test_E_YOPILGAN_SMENA_TOSMAYDI(client):
    """Yopilgan smena ham to'smaydi (ochiq smena ham to'smaydi — yuqoridagi test)."""
    from app.models.enums import ShiftStatus
    from app.models.shifts import Shift
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    kassir_id, _ = _xodim(d, "kassir")
    sid = _ochiq_smena(d, kassir_id)
    with _db() as db:
        db.get(Shift, sid).status = ShiftStatus.closed
        db.commit()
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])


def test_E_BOSHQA_DOKONDAGI_sherik_va_smena_TOSMAYDI(client):
    """TENANT IZOLYATSIYASI. Boshqa do'konda sherik ega ham, ochiq smena ham
    bo'lsa — bu do'konning yagona egasi baribir yopa oladi. Doira
    `Branch.company_id` orqali (`Shift` da `company_id` YO'Q)."""
    begona = _shop()
    begona_kassir, _ = _xodim(begona, "kassir")
    _xodim(begona, "ega")                       # begona sherik
    _ochiq_smena(begona, begona_kassir)         # begona ochiq smena

    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert _kompaniya(d["cid"])["deleted_at"] is not None
    #  Begona do'kon TEGILMAGAN
    assert _kompaniya(begona["cid"])["deleted_at"] is None


def test_E_409_matni_SABABNI_aytadi_YOPILGAN_demaydi(client):
    """⚠️  Ilgari `except ValueError` HAR QANDAY sababni «Do'kon allaqachon
    yopilgan» deb ko'rsatardi. Ikki yangi sabab qo'shilgach o'sha matn egani
    CHALG'ITARDI: do'kon aslida OCHIQ. Har sabab O'Z jumlasini beradi.
    (2026-10-17: `open_shift` sababi olib tashlandi, `peers_present` qoldi.)"""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    _xodim(d, "administrator")
    eh = _token(ega_id, "ega", d["cid"])

    matn = _close(client, eh).json()["detail"]

    assert "allaqachon yopilgan" not in matn, matn
    assert "Administrator" in matn or "Ega" in matn, matn


def test_E_YAGONA_EGA_smenasiz_YOPADI_va_oqim_OZGARMADI(client):
    """POZITIV: sherik ham, ochiq smena ham bo'lmasa — mavjud parol + tasdiq
    oqimi AVVALGIDEK ishlaydi (CH-23 faqat to'siq qo'shdi, oqimni emas)."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])

    #  Noto'g'ri parol — AVVALGIDEK 403, to'siqlar bu xulqni o'zgartirmadi
    assert _close(client, eh, password="XATO-PAROL").status_code == 403
    #  Noto'g'ri tasdiq so'zi — AVVALGIDEK 400
    assert _close(client, eh, confirm="boshqa").status_code == 400
    assert _kompaniya(d["cid"])["deleted_at"] is None

    r = _close(client, eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert _kompaniya(d["cid"])["deleted_at"] is not None
