# -*- coding: utf-8 -*-
"""Xavfsizlik 1-bosqich — HTTP darajasidagi adversarial testlar.

Uch bloker yopildi:
  P0-1  do'kon bo'ylab PIN lockout (autentifikatsiyasiz DoS)
  P0-2  imtiyozli xodim 4 raqamli PIN bilan kirishi
  P1-4  `fleet.heartbeat` orqali boshqa do'kon qurilmasini o'zlashtirish
va yo'l-yo'lakay 422 javobida kredensial qaytarilishi.

Testlar SERVIS funksiyalarini emas, HTTP yuzasini bosadi — himoya aynan shu
chegarada bo'lishi kerak.
"""
import uuid

_VK = {"X-Vendor-Key": "test-vendor-key"}


# ── yordamchi: har test uchun MUSTAQIL do'kon ────────────────────────────
def _tenant(client, *, owner_pin: str | None = None):
    """Yangi do'kon: kod, egа (telefon+parol) va ixtiyoriy egа PIN'i."""
    phone = f"+99893{uuid.uuid4().int % 10000000:07d}"
    code = f"co{uuid.uuid4().hex[:8]}"
    body = {
        "company_name": "QA Do'kon", "company_code": code,
        "owner_name": "QA Ega", "owner_phone": phone,
        "owner_password": "Toshkent-Bahor-2026", "plan": "start",
    }
    if owner_pin:
        body["owner_pin"] = owner_pin
    r = client.post("/api/v1/admin/companies", headers=_VK, json=body)
    assert r.status_code == 200, r.text
    lg = client.post("/api/v1/auth/login/password",
                     json={"phone": phone, "password": "Toshkent-Bahor-2026"}).json()
    return {
        "company_id": r.json()["company_id"], "code": code, "phone": phone,
        # PIN login endi AYNIQSA bitta xodimga qaratiladi, shuning uchun testlarга
        # nishon kerak. Egа standart nishon: kassir yaratilsa `_cashier` uni almashtiradi.
        "owner_id": lg["employee"]["id"], "cashier_id": None,
        "headers": {"Authorization": f"Bearer {lg['access_token']}"},
    }


def _cashier(client, t, pin: str, role_code: str = "kassir"):
    r = client.post("/api/v1/employees", headers=t["headers"], json={
        "full_name": "QA Kassir", "role_code": role_code, "pin": pin})
    assert r.status_code == 200, r.text
    t["cashier_id"] = r.json()["id"]        # standart PIN-nishon
    return r.json()


def _target(t):
    return t["cashier_id"] or t["owner_id"]


def _pin_login(client, t, pin: str, emp_id=None):
    """PIN login — endi NISHON xodim ham yuboriladi.

    ⚠️  `employee_id` MAJBURIY bo'ldi: server ilgari PIN'ni do'kondagi HAR BIR
        xodim bilan qiyoslardi (N x bcrypt = autentifikatsiyasiz DoS). Testlar shu
        bois nishonni aniq ko'rsatadi — bu haqiqiy POS oqimining o'zi."""
    return client.post("/api/v1/auth/login", json={
        "company_code": t["code"] if isinstance(t, dict) else t,
        "employee_id": emp_id or _target(t),
        "pin": pin})


def _attempts_db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _clear_ip_tier():
    """IP hisoblagichini tozalaydi — hujumchining IP almashtirishini taqlid qiladi.

    Hisoblagichlar endi JARAYON XOTIRASIDA emas, BAZADA: ular deploy'dan omon
    qoladi va instanslar o'rtasida bo'linadi."""
    from app.models.security import AuthAttempt
    db = _attempts_db()
    try:
        db.query(AuthAttempt).filter(AuthAttempt.dimension == "ip").delete()
        db.commit()
    finally:
        db.close()


def _clear_all_attempts():
    from app.models.security import AuthAttempt
    db = _attempts_db()
    try:
        db.query(AuthAttempt).delete()
        db.commit()
    finally:
        db.close()


def _store_count(company_id) -> int:
    from app.models.security import AuthAttempt
    db = _attempts_db()
    try:
        return (db.query(AuthAttempt)
                .filter(AuthAttempt.dimension == "store",
                        AuthAttempt.bucket == str(company_id)).count())
    finally:
        db.close()


def _flood(client, t, n: int, start: int = 9000, rotate_ip: bool = True, emp_id=None):
    """`n` ta HAR XIL noto'g'ri PIN yuboradi (PIN fazosini supurish taqlidi).

    ⚠️  `rotate_ip` STANDART BO'YICHA YOQIQ va bu MUHIM. IP qatlami 10 xatodan keyin
        429 qaytaradi, ya'ni bitta manbadan yuborilgan toshqin DO'KON qatlamiga
        umuman yetib bormaydi. Aynan shu sabab bu testning birinchi tahriri eski
        qattiq lockout bilan ham "yashil" bo'lgan edi — u tekshirmoqchi bo'lgan
        kod yo'liga yetmasdi. Haqiqiy tahdid — IP almashtirib turuvchi tarqoq
        hujum; do'kon qatlami aynan shuning uchun bor."""
    out = []
    for i in range(n):
        if rotate_ip:
            _clear_ip_tier()
        out.append(_pin_login(client, t, f"{start + i:04d}", emp_id).status_code)
    return out


# ═══ P0-1 · DO'KON BO'YLAB LOCKOUT ══════════════════════════════════════

def test_p01_wrong_pin_flood_does_not_lock_out_a_real_cashier(client):
    """⚠️  ASOSIY REGRESSIYA. Noto'g'ri PIN toshqini HAQIQIY kassirni bloklamasligi kerak.

    Ilgari do'kon qatlami 25 xatodan keyin 429 qaytarardi va muvaffaqiyatli kirish uni
    ATAYLAB tozalamasdi. Ya'ni `company_code` ni bilgan (u sir emas — butun smena
    biladi) istalgan kishi 25 ta soxta PIN yuborib BUTUN DO'KONNI 15 daqiqaga kassadan
    uzardi va buni cheksiz takrorlardi."""
    t = _tenant(client)
    nishon = _cashier(client, t, "4242")      # hujum nishoni
    boshqa = _cashier(client, t, "4244")      # yonidagi kassir — ishlayverishi SHART

    _clear_all_attempts()
    codes = _flood(client, t, 30, emp_id=nishon["id"])   # eski chegaradan (25) OSHIB ketamiz
    assert all(c in (401, 429) for c in codes), codes

    # IP qatlami bu bitta manba uchun ishlagan bo'lishi mumkin — uni tozalaymiz, chunki
    # tekshirilayotgan narsa DO'KON qatlami: tarqoq hujumda hujumchi IP almashtiradi,
    # kassir esa o'z do'konidan kiradi.
    _clear_ip_tier()

    r = _pin_login(client, t, "4244", boshqa["id"])
    assert r.status_code == 200, f"yonidagi kassir bloklandi: {r.status_code} {r.text}"


def test_p01_same_ip_flood_is_still_rate_limited(client):
    """Bitta IP'dan uzluksiz hujum HAMON to'siladi (himoya olib tashlanmagan)."""
    t = _tenant(client)
    _cashier(client, t, "5959")
    _clear_all_attempts()
    codes = _flood(client, t, 15, rotate_ip=False)
    assert 429 in codes, codes
    assert codes.index(429) <= 11, codes


def test_p01_repeating_one_pin_is_throttled_but_a_valid_pin_never_is(client):
    """AYNI qiymatni bolg'alash to'siladi; BOSHQA haqiqiy PIN esa bloklanmaydi.

    Nomzod qatlami faqat NOTO'G'RI qiymatlarni sanaydi: boshqa PIN mos kelsa login
    muvaffaqiyatli bo'ladi va u qiymat xatolar ro'yxatiga umuman tushmaydi. Shu sabab
    bu qatlam butun do'konni rad etish quroliga aylana olmaydi.

    ⚠️  TO'SILISH 429 EMAS, 401. Ilgari bu qatlam `HTTPException(429)` otardi va
        aynan o'sha 429 "bu employee_id haqiqiy" degan oracle bo'lib xizmat qilardi
        (qatlam faqat HAQIQIY xodim uchun ishlardi). Endi chegara oshsa javob
        noto'g'ri PIN bilan BIR XIL bo'ladi — lekin bloklash kuchida qoladi va buni
        quyida AYNAN o'sha qiymatga ega ikkinchi kassir isbotlaydi."""
    t = _tenant(client)
    a = _cashier(client, t, "4343")
    b = _cashier(client, t, "0000")            # PIN'i aynan bolg'alanadigan qiymat

    _clear_all_attempts()
    codes = []
    for _ in range(8):
        codes.append(_pin_login(client, t, "0000", a["id"]).status_code)
        _clear_ip_tier()                       # IP qatlamini chetga surib turamiz
    assert all(c == 401 for c in codes), codes     # 429 chiqmaydi — oracle yo'q

    # Qatlam HAQIQATAN to'sadi: "0000" endi TO'G'RI PIN bo'lgan kassir uchun ham o'tmaydi.
    assert _pin_login(client, t, "0000", b["id"]).status_code == 401
    _clear_ip_tier()

    r = _pin_login(client, t, "4343", a["id"])     # boshqa qiymat — bloklanmagan
    assert r.status_code == 200, r.text


def test_p01_one_tenant_flood_does_not_affect_another(client):
    """Bir do'kondagi xatolar BOSHQA do'kon kassiriga ta'sir qilmaydi."""
    a, b = _tenant(client), _tenant(client)
    _cashier(client, a, "5050")     # A dagi nishon — xatolar A ga yozilsin
    _cashier(client, b, "5151")

    _clear_all_attempts()
    _flood(client, a, 30)
    _clear_ip_tier()

    assert _pin_login(client, b, "5151").status_code == 200


def test_p01_success_does_not_reset_the_store_counter(client):
    """Muvaffaqiyat do'kon hisoblagichini tozalamaydi — insider sikli yopiq.

    Aks holda insider "bir necha xato + o'z PIN'i bilan kirish" sikli bilan
    hisoblagichni nolga tushirib, hamkasb PIN'ini cheksiz taxmin qilardi."""
    t = _tenant(client)
    _cashier(client, t, "6161")

    _clear_all_attempts()
    _flood(client, t, 5)
    before = _store_count(t["company_id"])
    assert before == 5, before

    _clear_ip_tier()
    assert _pin_login(client, t, "6161").status_code == 200
    assert _store_count(t["company_id"]) == before, "do'kon hisoblagichi tozalandi"


# ═══ P0-2 · PIN FAQAT KASSIR UCHUN ══════════════════════════════════════

def test_p02_cashier_pin_succeeds(client):
    t = _tenant(client)
    _cashier(client, t, "7171")
    assert _pin_login(client, t, "7171").status_code == 200


def test_p02_cashier_wrong_pin_fails(client):
    t = _tenant(client)
    _cashier(client, t, "7272")
    assert _pin_login(client, t, "7373").status_code == 401


def test_p02_owner_pin_is_rejected(client):
    """⚠️  Egа 4 raqamli PIN bilan KIRA OLMAYDI — butun biznes 4 raqam ortida qolmasin."""
    t = _tenant(client, owner_pin="8181")
    assert _pin_login(client, t, "8181").status_code == 401


def test_p02_admin_pin_is_rejected(client):
    """Administrator ham PIN bilan kira olmaydi (ruxsat bo'yicha aniqlanadi, rol nomi bo'yicha emas)."""
    t = _tenant(client)
    _cashier(client, t, "8282", role_code="administrator")
    assert _pin_login(client, t, "8282").status_code == 401


def test_p02_privileged_password_login_still_works(client):
    """Rad etilgan narsa — PIN YO'LI, hisobning O'ZI emas."""
    t = _tenant(client, owner_pin="8383")
    r = client.post("/api/v1/auth/login/password",
                    json={"phone": t["phone"], "password": "Toshkent-Bahor-2026"})
    assert r.status_code == 200, r.text


def test_p02_rejection_is_indistinguishable_from_a_wrong_pin(client):
    """Javob imtiyozli PIN ekanini OSHKOR QILMASLIGI kerak.

    Aks holda hujumchi "bu qiymat egaga tegishli" degan ma'lumotni olib, hujumini
    aynan shu qiymatga qaratardi."""
    t = _tenant(client, owner_pin="8484")
    priv = _pin_login(client, t, "8484")
    wrong = _pin_login(client, t, "8485")
    assert priv.status_code == wrong.status_code == 401
    assert priv.json() == wrong.json(), (priv.json(), wrong.json())


def test_p02_promoting_a_cashier_disables_pin_login(client):
    """Kassir imtiyozli rolga ko'tarilsa — PIN yo'li DARHOL yopiladi."""
    t = _tenant(client)
    e = _cashier(client, t, "8585")
    assert _pin_login(client, t, "8585").status_code == 200

    r = client.patch(f"/api/v1/employees/{e['id']}", headers=t["headers"],
                     json={"role_code": "administrator"})
    assert r.status_code == 200, r.text
    assert _pin_login(client, t, "8585").status_code == 401


def test_p02_permission_override_alone_disables_pin_login(client):
    """Rol nomi emas, RUXSAT hal qiladi: kassirga `xodimlar.edit` berilsa — PIN yopiladi."""
    t = _tenant(client)
    e = _cashier(client, t, "8686")
    assert _pin_login(client, t, "8686").status_code == 200

    r = client.patch(f"/api/v1/employees/{e['id']}/permissions", headers=t["headers"],
                     json={"overrides": {"xodimlar.edit": True}})
    assert r.status_code == 200, r.text
    assert _pin_login(client, t, "8686").status_code == 401


def test_p02_tenant_isolation_holds_for_pin_login(client):
    """A do'konidagi PIN B do'konida ishlamaydi."""
    a, b = _tenant(client), _tenant(client)
    ea = _cashier(client, a, "9191")
    assert _pin_login(client, a, "9191").status_code == 200
    # A ning xodim ID'si B ning do'kon kodi bilan — rad etilishi SHART.
    assert _pin_login(client, b, "9191", ea["id"]).status_code == 401


# ═══ P1-4 · FLEET QURILMA TENANT DOIRASI ════════════════════════════════

def _heartbeat(client, t, device_uuid, **extra):
    body = {"device_uuid": device_uuid, "app": "pos", "version": "1.0.0"}
    body.update(extra)
    return client.post("/api/v1/fleet/heartbeat", headers=t["headers"], json=body)


def _fleet(client, t):
    r = client.get("/api/v1/fleet/devices", headers=t["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def test_p14_foreign_device_uuid_cannot_be_taken_over(client):
    """⚠️  ASOSIY REGRESSIYA. B do'koni A ning qurilmasini O'ZLASHTIRA OLMAYDI.

    Ilgari qidiruv FAQAT `device_uuid` bo'yicha edi, so'ng `dev.company_id` chaqiruvchining
    do'koniga yozib qo'yilardi: qurilma jabrlanuvchining ro'yxatidan yo'qolar, telemetriyasi
    esa hujumchiga oqardi."""
    a, b = _tenant(client), _tenant(client)
    du = str(uuid.uuid4())

    assert _heartbeat(client, a, du).status_code == 200
    a_before = _fleet(client, a)
    assert any(d["device_uuid"] == du for d in a_before["devices"]), a_before

    r = _heartbeat(client, b, du)                  # o'zlashtirishga urinish
    assert r.status_code == 404, f"begona qurilma qabul qilindi: {r.status_code} {r.text}"

    # A ning yozuvi O'ZGARMAGAN va hamon A da
    a_after = _fleet(client, a)
    assert [d["device_uuid"] for d in a_after["devices"]] == \
           [d["device_uuid"] for d in a_before["devices"]]
    # B da bu qurilma UMUMAN ko'rinmaydi
    assert all(d["device_uuid"] != du for d in _fleet(client, b)["devices"])


def test_p14_victim_row_keeps_its_owner_in_the_database(client):
    """Bazada `company_id` KO'CHMAGANINI to'g'ridan-to'g'ri tasdiqlaymiz."""
    from app.db.session import SessionLocal
    from app.models.sync import SyncDevice

    a, b = _tenant(client), _tenant(client)
    du = str(uuid.uuid4())
    assert _heartbeat(client, a, du).status_code == 200
    _heartbeat(client, b, du)

    db = SessionLocal()
    try:
        rows = db.query(SyncDevice).filter(SyncDevice.device_uuid == du).all()
        assert len(rows) == 1, f"UUID takrorlandi: {len(rows)}"
        assert str(rows[0].company_id) == str(a["company_id"]), "egalik KO'CHDI"
    finally:
        db.close()


def test_p14_each_tenant_registers_its_own_device_normally(client):
    """Tuzatish oddiy ishni buzmagan: har do'kon o'z qurilmasini ro'yxatdan o'tkazadi."""
    a, b = _tenant(client), _tenant(client)
    da, dbb = str(uuid.uuid4()), str(uuid.uuid4())
    assert _heartbeat(client, a, da).status_code == 200
    assert _heartbeat(client, b, dbb).status_code == 200
    assert any(d["device_uuid"] == da for d in _fleet(client, a)["devices"])
    assert any(d["device_uuid"] == dbb for d in _fleet(client, b)["devices"])
    assert all(d["device_uuid"] != dbb for d in _fleet(client, a)["devices"])


def test_p14_repeat_heartbeat_from_the_owner_still_works(client):
    """O'z qurilmasidan takroriy heartbeat — idempotent, yangi qator yaratmaydi."""
    a = _tenant(client)
    du = str(uuid.uuid4())
    for _ in range(3):
        assert _heartbeat(client, a, du).status_code == 200
    devs = [d for d in _fleet(client, a)["devices"] if d["device_uuid"] == du]
    assert len(devs) == 1, devs


def test_p14_foreign_branch_id_is_not_accepted(client):
    """So'rovdagi `branch_id` boshqa do'konnikи bo'lsa — qabul qilinmaydi."""
    from app.db.session import SessionLocal
    from app.models.org import Branch
    from app.models.sync import SyncDevice

    a, b = _tenant(client), _tenant(client)
    db = SessionLocal()
    try:
        b_branch = db.query(Branch).filter(
            Branch.company_id == uuid.UUID(b["company_id"])).first()
        assert b_branch is not None
        foreign_branch_id = str(b_branch.id)
    finally:
        db.close()

    du = str(uuid.uuid4())
    assert _heartbeat(client, a, du, branch_id=foreign_branch_id).status_code == 200

    db = SessionLocal()
    try:
        dev = db.query(SyncDevice).filter(SyncDevice.device_uuid == du).first()
        assert dev is not None
        assert str(dev.company_id) == str(a["company_id"])
        assert dev.branch_id is None or str(dev.branch_id) != foreign_branch_id
    finally:
        db.close()


# ═══ 422 · KREDENSIAL JAVOBDA QAYTARILMAYDI ═════════════════════════════

def test_422_does_not_echo_the_submitted_pin(client):
    """Validatsiya xatosi yuborilgan PIN'ni QAYTARMASLIGI kerak.

    Pydantic v2 har xato yozuviga `input` — yuborilgan qiymatni — qo'shadi. U javob
    tanasi bilan birga proxy loglariga va xato-kuzatuv tizimlariga tushishi mumkin."""
    secret = "135792468013579"          # 15 belgi — `pin` uchun max_length=12 dan oshadi
    r = client.post("/api/v1/auth/login", json={"company_code": "x", "pin": secret})
    assert r.status_code == 422, r.status_code
    assert secret not in r.text, r.text


def test_422_does_not_echo_the_submitted_password(client):
    secret = "s3cr3t-parol-qaytmasin"
    # `password` satr bo'lishi kerak — ro'yxat yuborsak TUR xatosi bo'ladi va Pydantic
    # yuborilgan qiymatni `input` ga qo'yadi. Aynan shu qiymat qaytmasligi kerak.
    r = client.post("/api/v1/auth/login/password",
                    json={"phone": "+998900000001", "password": [secret]})
    assert r.status_code == 422, r.status_code
    assert secret not in r.text, r.text


def test_422_still_reports_the_field_and_reason(client):
    """Tozalash xato xabarini foydasiz qilib qo'ymagan — maydon va sabab ko'rinadi."""
    r = client.post("/api/v1/auth/login", json={"company_code": "x", "pin": "1"})
    assert r.status_code == 422
    body = r.json()
    assert "detail" in body and body["detail"], body
    assert any("pin" in str(e.get("loc", "")) for e in body["detail"]), body
