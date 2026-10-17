# -*- coding: utf-8 -*-
"""CH-18C — o'chirishni QATTIQLASHTIRISH: PIN siklining OXIRIGACHA tekshirilishi
va Ega/Administrator RBAC matritsasining O'ZGARMAGANLIGI.

CH-18B «so'rov yuborildi → ega ko'rdi → ega bajardi» qismini allaqachon
qoplaydi. BU FAYL o'sha siklning QOLGAN, xavfliroq qirralarini o'lchaydi:

  C. NATIJA va QAYTA-O'YNATISH (replay).
     Xodim natijani QANDAY biladi: unga xabar YUBORILMAYDI (bizda ishonchli
     kanal yo'q — PIN'li xodimning telefoni tasdiqlanmagan), natija KIRISHNING
     YOPILISHIDAN ko'rinadi. Shuni AYNAN shunday sinaymiz, o'ylab topilgan
     bildirishnoma kanalini EMAS.
     Bajarilgan amal QAYTA bajarilmaydi: ikkinchi chaqiruv idempotent, yangi
     audit yozuvi va yangi `sec_epoch` sakrashi YO'Q.

  E. EGA YO'Q BO'LSA — KUTIB QOLMAYDI (spec: «Do not leave users permanently
     trapped in pending»). Uch yo'l tekshiriladi: (1) ega o'zini o'chiradi —
     so'rov QOLGAN egaga ko'rinadi; (2) yagona ega o'zini o'chira olmaydi, lekin
     YOPISH yo'li bor; (3) do'kon yopilsa kutayotgan so'rov BAJARILADI va
     ro'yxat BO'SHAYDI — osilib qolgan `pending` qolmaydi.

     ⚠️  BIZ QONUNIY MUDDAT O'YLAB TOPMAYMIZ. Hech qayerda «30 kun» kabi va'da
         berilmasligini ALOHIDA sinov qadaydi.

  F. RBAC MATRITSASI O'ZGARMAGAN. Yangi yo'llar MAVJUD ruxsat kodlaridan
     foydalanadi; `ega`/`administrator` huquqlari kengaymaydi va
     ADMINISTRATOR imtiyozi bilan CHETLAB O'TISH yo'li YO'Q.
"""
from __future__ import annotations

import uuid

from tests.test_ch18b_ochirish_yakuni import (
    PAROL, TASDIQ, _close, _db, _del_other, _del_self, _marker,
    _qator_matni, _shop, _token, _xodim, _yolgiz_ega,
)

PIN = "4721"


def _soralgan(client, ph):
    return client.post("/api/v1/auth/account-deletion/request", headers=ph)


def _pin_kirish(client, eid):
    return client.post("/api/v1/auth/login",
                       json={"employee_id": str(eid), "pin": PIN})


def _audit_soni(eid) -> int:
    from app.models.sync import AuditLog
    with _db() as db:
        return (db.query(AuditLog)
                .filter(AuditLog.entity == "employee_account",
                        AuditLog.entity_id == uuid.UUID(str(eid)))
                .count())


def _sec_epoch(eid) -> int:
    from app.models.auth import Employee
    with _db() as db:
        return int(db.get(Employee, uuid.UUID(str(eid))).sec_epoch or 0)


def _ism(eid) -> str:
    from app.models.auth import Employee
    with _db() as db:
        return db.get(Employee, uuid.UUID(str(eid))).full_name


def _summa(sale_id):
    from app.models.sales import Sale
    with _db() as db:
        return db.get(Sale, uuid.UUID(str(sale_id))).total


def _snapshot(sale_id) -> str | None:
    """Chekdagi muzlatilgan kassir ismi (`SALE_AUDIT_IDENTITY.md` §Snapshots)."""
    from app.models.sales import Sale
    with _db() as db:
        return db.get(Sale, uuid.UUID(str(sale_id))).cashier_name_snapshot


def _pinli(d, *, nom=None):
    """PIN'li (parolsiz) kassir + uning tokeni."""
    pid, _ = _xodim(d, "kassir", nom=nom or _marker("PINLI"), parol=None, pin=PIN)
    return pid, _token(pid, "kassir", d["cid"])


# ══ C. NATIJA va QAYTA-O'YNATISH ════════════════════════════════════════════

def test_C_NATIJA_KIRISHNING_YOPILISHIDAN_KORINADI(client):
    """Xodim natijani KIRA OLMASLIGIDAN biladi — bu kuzatiladigan yakun.

    ⚠️  Ataylab: biz bildirishnoma kanali O'YLAB TOPMAYMIZ. PIN'li xodimning
        telefoni tasdiqlanmagan, SMS yo'li yo'q; «xabar yubordik» deyish
        isbotlanmaydigan da'vo bo'lardi."""
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    pid, ph = _pinli(d)
    eh = _token(ega_id, "ega", d["cid"])

    #  O'chirishdan OLDIN PIN bilan kira oladi — nazorat nuqtasi
    assert _pin_kirish(client, pid).status_code == 200, "nazorat: PIN ishlashi kerak"
    assert _soralgan(client, ph).status_code == 200
    assert _del_other(client, eh, pid).status_code == 200

    r = _pin_kirish(client, pid)

    assert r.status_code == 401, (r.status_code, r.text[:200])


def test_C_BAJARILGACH_QAYTA_OYNATILMAYDI(client):
    """Ayni so'rovni ikkinchi marta «bajarish» hech narsani o'zgartirmaydi."""
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    pid, ph = _pinli(d)
    eh = _token(ega_id, "ega", d["cid"])
    assert _soralgan(client, ph).status_code == 200
    assert _del_other(client, eh, pid).status_code == 200
    qator1, audit1, se1 = _qator_matni(pid), _audit_soni(pid), _sec_epoch(pid)

    r = _del_other(client, eh, pid)

    assert r.status_code == 200 and r.json()["repeated"] is True, r.text[:200]
    assert _qator_matni(pid) == qator1, "qator QAYTA yozildi"
    assert _audit_soni(pid) == audit1, "ikkinchi audit yozuvi paydo bo'ldi"
    assert _sec_epoch(pid) == se1, "sec_epoch QAYTA sakradi"


def test_C_OCHIRILGACH_ESKI_TOKEN_YANGI_SOROV_YOZMAYDI(client):
    """O'chirilgan xodimning eski tokeni `sec_epoch` bilan KESILGAN, ya'ni u
    bajarilgan so'rovni qayta tiklay olmaydi."""
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    pid, ph = _pinli(d)
    eh = _token(ega_id, "ega", d["cid"])
    assert _soralgan(client, ph).status_code == 200
    assert _del_other(client, eh, pid).status_code == 200

    r = _soralgan(client, ph)          # AYNI eski token

    assert r.status_code == 401, (r.status_code, r.text[:200])
    assert client.get("/api/v1/employees/deletion-requests", headers=eh).json() == []


def test_C_HOLAT_QONUNIY_MUDDAT_VADA_QILMAYDI(client):
    """⚠️  Spec: «Do not invent a legal processing deadline». Javobda muddat,
    tugash sanasi yoki SLA ma'nosini beradigan maydon BO'LMASLIGI kerak."""
    d = _shop()
    _xodim(d, "ega")
    pid, ph = _pinli(d)
    assert _soralgan(client, ph).status_code == 200

    st = client.get("/api/v1/auth/account-deletion", headers=ph).json()

    matn = repr(st).lower()
    for taqiq in ("deadline", "due_at", "expires", "sla", "within_days",
                  "process_by", "guarantee"):
        assert taqiq not in matn, f"muddat va'dasi: {taqiq} -> {st}"
    #  Faqat FAKT qaytariladi: so'rov bor va qachon yuborilgan
    assert set(st["request"]) == {"pending", "requested_at"}, st["request"]


# ══ E. EGA YO'Q BO'LSA — KUTIB QOLMAYDI ═════════════════════════════════════

def test_E_EGA_OZINI_OCHIRSA_SOROV_QOLGAN_EGAGA_KORINADI(client):
    """Ega o'zini o'chirsa, kutayotgan so'rov YO'QOLMAYDI — ikkinchi ega
    ko'radi va BAJARADI."""
    d = _shop()
    a_id, _ = _xodim(d, "ega")
    b_id, _ = _xodim(d, "ega")
    pid, ph = _pinli(d)
    ah, bh = _token(a_id, "ega", d["cid"]), _token(b_id, "ega", d["cid"])
    assert _soralgan(client, ph).status_code == 200
    assert _del_self(client, ah).status_code == 200, "ikkinchi ega bor — ruxsat"

    lst = client.get("/api/v1/employees/deletion-requests", headers=bh)

    assert lst.status_code == 200 and [x["employee_id"] for x in lst.json()] == [pid]
    assert _del_other(client, bh, pid).status_code == 200
    assert client.get("/api/v1/employees/deletion-requests", headers=bh).json() == []


def test_E_YAGONA_EGA_ozini_OCHIRMAYDI_ammo_YOPISH_YOLI_BOR(client):
    """Yagona ega o'zini o'chira olmaydi (do'kon boshsiz qolardi), lekin
    QULFLANIB ham qolmaydi: holat YOPISH yo'lini OCHIQ ko'rsatadi."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])

    st = client.get("/api/v1/auth/account-deletion", headers=eh).json()

    assert st["store_closure_available"] is True, st
    assert st["can_delete"] is False and "sole_manager" in st["blockers"], st
    #  Vorisi YO'Q (hammasi `terminated`) -> yagona chiqish YOPISH
    assert st["transfer_candidates"] == [], st
    assert _del_self(client, eh).status_code == 409


def test_E_YOPILGANDA_KUTAYOTGAN_SOROV_OSILIB_QOLMAYDI(client):
    """Do'kon yopilganda rozilik bergan so'rov BAJARILADI va ro'yxat BO'SHAYDI
    — hech kim abadiy `pending` holatida qolmaydi."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)  # CH-23: YAGONA rahbar (sherik Ega/Administrator bo'lsa yopish 409)
    nom = _marker("KUTAYOTGAN")
    pid, ph = _pinli(d, nom=nom)
    eh = _token(ega_id, "ega", d["cid"])
    assert _soralgan(client, ph).status_code == 200

    r = _close(client, eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.json()["anonymized_employees"] >= 1, r.json()
    assert nom not in _qator_matni(pid), "rozilik bergan xodim PII si QOLDI"
    from app.services import account_deletion as _AD
    with _db() as db:
        assert _AD.list_requests(db, d["cid"]) == [], "osilib qolgan so'rov"


def test_E_YOPILGACH_YANGI_SOROV_TOPLANMAYDI(client):
    """Yopilgan do'konda yangi so'rov yig'ilmaydi — kirish 401, ya'ni hech kim
    javobsiz navbatga tushmaydi."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)  # CH-23: YAGONA rahbar (sherik Ega/Administrator bo'lsa yopish 409)
    pid, ph = _pinli(d)
    eh = _token(ega_id, "ega", d["cid"])
    assert _close(client, eh).status_code == 200

    r = _soralgan(client, ph)

    assert r.status_code == 401, (r.status_code, r.text[:200])


# ══ F. RBAC MATRITSASI O'ZGARMAGAN ══════════════════════════════════════════

def test_F_FULL_ACCESS_ROLES_ozgarmagan(client):
    """Ega/Administrator o'qi KENGAYMAGAN — ayni ikki rol, ayni tartib."""
    from app.core.deps import FULL_ACCESS_ROLES

    assert FULL_ACCESS_ROLES == ("ega", "administrator"), FULL_ACCESS_ROLES


def test_F_YANGI_YOLLAR_YANGI_RUXSAT_KODI_KIRITMAYDI(client):
    """CH-16/CH-18 yo'llari MAVJUD ruxsat kodlariga suyanadi: matritsaga yangi
    o'q qo'shilmagan, ya'ni rollarning huquq to'plami o'zgarmadi."""
    import json

    from app.models.auth import Permission
    from tests.test_mobile_permission_matrix import MATRIX

    matritsa = json.loads(MATRIX.read_text(encoding="utf-8"))
    with _db() as db:
        mavjud = {p.code for p in db.query(Permission).all()}
    assert mavjud, "nazorat: urug'da ruxsat kodlari bo'lishi kerak"

    kerak = {k for a in matritsa["actions"].values() for k in a.get("any_of", [])}

    assert kerak <= mavjud, f"matritsa YANGI ruxsat kodi talab qiladi: {kerak - mavjud}"


def test_F_ADMINISTRATOR_BOSHQA_HISOBNI_OCHIRMAYDI(client):
    """⚠️  `xodimlar.edit` administratorda BOR, ya'ni ruxsat darvozasidan
    o'tadi — qaytarilmas o'chirishni to'xtatadigan narsa EGALIK tekshiruvi.
    Imtiyoz bilan chetlab o'tish yo'li YO'Q."""
    d = _shop()
    _xodim(d, "ega")
    adm_id, _ = _xodim(d, "administrator")
    nom = _marker("MAQSAD")
    pid, _ = _pinli(d, nom=nom)
    ah = _token(adm_id, "administrator", d["cid"])
    from app.core.deps import effective_permissions
    from app.models.auth import Employee
    with _db() as db:
        assert "xodimlar.edit" in effective_permissions(
            db.get(Employee, uuid.UUID(adm_id)), db), "nazorat: ruxsat bo'lishi kerak"

    r = _del_other(client, ah, pid)

    assert r.status_code == 403, (r.status_code, r.text[:200])
    assert nom in _qator_matni(pid), "administrator PII ni o'chirdi"


def test_F_ADMINISTRATOR_YOPISHNI_ham_SOZ_ORQALI_OCHMAYDI(client):
    """Administrator do'konni yopa olmaydi — yopish faqat EGANING yo'li."""
    d = _shop()
    _xodim(d, "ega")
    adm_id, _ = _xodim(d, "administrator")
    ah = _token(adm_id, "administrator", d["cid"])

    assert _close(client, ah).status_code == 403
    assert client.get("/api/v1/auth/store-closure", headers=ah).status_code == 403


def test_F_ADMINISTRATOR_SOROVNI_KORADI_ammo_BAJARMAYDI(client):
    """Halol ajratish: administrator xodimlar ro'yxatini allaqachon ko'radi,
    shu bois so'rov ro'yxati unga YANGI ma'lumot BERMAYDI — lekin BAJARISH
    huquqi YO'Q (yuqoridagi 403)."""
    d = _shop()
    _xodim(d, "ega")
    adm_id, _ = _xodim(d, "administrator")
    pid, ph = _pinli(d)
    ah = _token(adm_id, "administrator", d["cid"])
    assert _soralgan(client, ph).status_code == 200

    lst = client.get("/api/v1/employees/deletion-requests", headers=ah)

    assert lst.status_code == 200, (lst.status_code, lst.text[:200])
    assert [x["employee_id"] for x in lst.json()] == [pid]
    assert _del_other(client, ah, pid).status_code == 403


# ══ G. QOLDIQ PII — REALISTIK MA'LUMOT USTIDA ═══════════════════════════════
#
#  ⚠️  CH-18B da men «butun bazada 0 joy» degandim. Bu DA'VO SHARTLI edi:
#      sinov xodimi HECH NARSA SOTMAGAN edi. Realistik ma'lumotda (sotgan
#      kassir) ism `sales.cashier_name_snapshot` da QOLADI — bu ataylab
#      qo'yilgan, hujjatlashtirilgan CHEK SNAPSHOT'i (`SALE_AUDIT_IDENTITY.md`
#      §Snapshots: «frozen strings keep old receipts reproducible after an
#      entity is renamed or deleted»).
#
#      Men uni O'Z QARORIM bilan tozalamayman: `sales` append-only fiskal
#      yozuv va spec «Do not purge historical ledgers» deydi. Shu bois bu
#      sinov HAQIQATNI qadaydi, va qoldiq EGA QARORI sifatida hisobotga
#      chiqadi. Sinov «o'chirildi» deb YOLG'ON yozmaydi.

def test_G_SOTGAN_kassir_ISMI_CHEK_SNAPSHOTIDA_QOLADI(client):
    """REALISTIK ma'lumot: kassir sotadi -> o'chiriladi -> `employees` qatori
    toza, lekin chek snapshot'ida ism QOLADI va DAFTAR BUTUN."""
    from tests.test_mobile_parity import _product, _staff

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    kh, kid = _staff(d, "kassir")
    nom = _ism(kid)
    mahsulot = _product(d, qty=50)

    r = client.post("/api/v1/sales", headers=kh, json={
        "items": [{"product_id": str(mahsulot["id"]), "qty": 2, "unit_price": 1000}],
        "payment_method": "cash", "given_amount": 5000,
        "client_uuid": str(uuid.uuid4())})
    assert r.status_code in (200, 201), (r.status_code, r.text[:300])
    sid = r.json()["id"]
    summa_oldin = _summa(sid)
    assert _snapshot(sid) == nom, "nazorat: snapshot sotuv vaqtida yozilishi kerak"

    assert _del_other(client, eh, str(kid)).status_code == 200

    #  `employees` qatori TOZA
    assert nom not in _qator_matni(kid)
    #  ... lekin CHEK snapshot'i QOLADI — buni yashirmaymiz
    assert _snapshot(sid) == nom, (
        "snapshot o'zgargan: bu testning MAQSADI qoldiqni HUJJATLASHTIRISH")
    #  DAFTAR BUTUN: sotuv yozuvi va summasi TEGILMAGAN
    from app.models.sales import Sale
    assert _summa(sid) == summa_oldin, "fiskal daftar summasi O'ZGARDI"
    with _db() as db:
        s = db.get(Sale, uuid.UUID(sid))
        assert s is not None, "chek yozuvi O'CHIRILDI"
        assert s.cashier_id == kid, "FK uzildi — audit javobgarligi yo'qoldi"


def test_G_FK_lar_UZILMAYDI_audit_javobgarligi_QOLADI(client):
    """O'chirish FK'larni NULL qilmaydi: «kim qildi» bog'lanishi saqlanadi,
    faqat KIMLIGI (ism/telefon) o'chadi. Aks holda audit ma'nosini yo'qotardi."""
    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    pid, ph = _pinli(d)
    assert _soralgan(client, ph).status_code == 200

    assert _del_other(client, eh, pid).status_code == 200

    from app.models.auth import Employee
    with _db() as db:
        e = db.get(Employee, uuid.UUID(pid))
        assert e is not None, "qator O'CHIRILDI — 22 ta FK uzilardi"
        assert e.company_id == d["cid"], "ijarachi bog'lanishi uzildi"
        assert e.deleted_at is not None and e.full_name != ""


# ══ H. KIRISH/YETKAZISH GRANTLARI — O'CHIRILADI ═════════════════════════════
#
#  ⚠️  `anonymize()` allaqachon `EmployeePermission` va `EmployeeBranch` ni
#      o'chiradi, izohi esa qoidani aytadi: «Kirish grantlari — biznes tarixi
#      EMAS». PUSH QURILMA TOKENI AYNI SHU TOIFA: u do'konga shu odamning
#      TELEFONIGA bildirishnoma yuborish imkonini beradi va fiskal yozuv
#      emas. Hisob o'chirilgach u QOLMASLIGI kerak.

def test_H_PUSH_QURILMA_TOKENI_ochiriladi(client):
    """O'chirilgan odamning telefoniga bildirishnoma yuborib bo'lmaydi."""
    from app.models.devices import DeviceToken

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    pid, ph = _pinli(d)
    belgi = f"CH18C-PUSH-{uuid.uuid4().hex}"
    with _db() as db:
        db.add(DeviceToken(company_id=d["cid"], employee_id=uuid.UUID(pid),
                           token=belgi, platform="ios"))
        db.commit()
    with _db() as db:
        assert db.query(DeviceToken).filter(DeviceToken.token == belgi).count() == 1, \
            "nazorat: token yozilishi kerak"

    assert _del_other(client, eh, pid).status_code == 200

    with _db() as db:
        qoldi = db.query(DeviceToken).filter(
            DeviceToken.employee_id == uuid.UUID(pid)).count()
    assert qoldi == 0, f"push tokeni QOLDI ({qoldi}) — o'chirilgan odamga xabar yuborish mumkin"


def test_H_BOSHQA_xodim_push_tokeni_TEGILMAYDI(client):
    """Faqat o'chirilayotgan odamning tokeni ketadi."""
    from app.models.devices import DeviceToken

    d = _shop()
    ega_id, _ = _xodim(d, "ega")
    eh = _token(ega_id, "ega", d["cid"])
    a, _ha = _pinli(d)
    b, _hb = _pinli(d)
    with _db() as db:
        for eid in (a, b):
            db.add(DeviceToken(company_id=d["cid"], employee_id=uuid.UUID(eid),
                               token=f"CH18C-{eid}", platform="android"))
        db.commit()

    assert _del_other(client, eh, a).status_code == 200

    with _db() as db:
        assert db.query(DeviceToken).filter(
            DeviceToken.employee_id == uuid.UUID(b)).count() == 1, \
            "begona xodimning tokeni o'chirildi"


# ══ I. PREVIEW ≡ HAQIQIY XULQ ═══════════════════════════════════════════════

def test_I_PREVIEW_RAQAMLARI_YOPISH_NATIJASIGA_AYNAN_MOS(client):
    """⚠️  Tasdiqlash ekrani ko'rsatgan raqam, yopish BAJARGANIDAN farq
    QILMASLIGI kerak. CH-18B preview'ni alohida, yopishni alohida qadagan;
    bu test IKKISINI BOG'LAYDI — endpoint matni server xulqidan ajralib
    ketsa, aynan shu yerda qizil bo'ladi."""
    d = _shop()
    ega_id, _ = _yolgiz_ega(d)  # CH-23: YAGONA rahbar (sherik Ega/Administrator bo'lsa yopish 409)
    eh = _token(ega_id, "ega", d["cid"])
    #  Uchta PIN'li xodim: ikkisi SO'RAYDI, biri YO'Q
    soragan = [_pinli(d) for _ in range(2)]
    jim_id, _jh = _pinli(d)
    for _pid, ph in soragan:
        assert _soralgan(client, ph).status_code == 200

    pv = client.get("/api/v1/auth/store-closure", headers=eh).json()
    r = _close(client, eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    j = r.json()
    assert j["anonymized_employees"] == pv["pending_requests"], (pv, j)
    assert j["pii_retained_employees"] == pv["pii_retained_after_closure"], (pv, j)
    assert pv["employees_with_pii"] == (pv["pending_requests"]
                                       + pv["pii_retained_after_closure"]), pv
    #  ... va bu RAQAMLAR emas, HAQIQAT: so'ramagan xodim PII si JOYIDA
    assert _ism(jim_id).startswith("CH18B-NOM") or "CH18B" in _qator_matni(jim_id), \
        "so'ramagan xodim anonimlashtirildi"
    for pid, _ph in soragan:
        assert "CH18B" not in _qator_matni(pid), "so'ragan xodim PII si QOLDI"


# ══ J. YOPISH ≠ SHAXSIY HISOBNI O'CHIRISH ═══════════════════════════════════
#
#  ⚠️  Spec item 1: operatsion yopish, shaxsiy hisobni o'chirish, majburiy
#      hisob-kitob saqlanishi va qaytarilmas anonimlashtirish — TO'RT BOSHQA
#      narsa. `delete_my_account` ALOHIDA bayroq va STANDART `False`: yopish
#      tugmasi eganing shaxsiy ma'lumotini JIM o'chirmaydi.

def test_J_YOPISH_OZI_EGANING_PII_siga_TEGMAYDI(client):
    """Standart yopish — OPERATSION amal: ega hisobi PII si JOYIDA qoladi."""
    d = _shop()
    ega_id, nom = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.json()["anonymized_employees"] == 0, r.json()
    assert nom in _qator_matni(ega_id), "yopish eganing PII sini JIM o'chirdi"


def test_J_EGA_AYNIQ_sorasa_OZINI_ham_ochiradi(client):
    """`delete_my_account=True` — ega BUNI AYNIQ so'raydi, shundagina o'chadi."""
    d = _shop()
    ega_id, nom = _yolgiz_ega(d)
    eh = _token(ega_id, "ega", d["cid"])

    r = _close(client, eh, delete_self=True)

    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert r.json()["anonymized_employees"] == 1, r.json()
    assert nom not in _qator_matni(ega_id), "ega so'radi, lekin PII QOLDI"
    #  ... lekin do'kon yopilishi O'ZI o'zgarmaydi: bu BIR amal, ikki oqibat
    assert r.json()["closed"] is True, r.json()
    #  ... va xodim QATORI o'chirilmaydi (FK butunligi)
    from app.models.auth import Employee
    with _db() as db:
        assert db.get(Employee, uuid.UUID(ega_id)) is not None
