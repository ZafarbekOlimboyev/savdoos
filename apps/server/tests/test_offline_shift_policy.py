# -*- coding: utf-8 -*-
"""P9 — OFFLINE SAVDO XAVFSIZLIGI: `GET /shifts/offline-sale-policy` va rad etish yo'li.

NIMA UCHUN BU FAYL BOR. `security.force_shift` yoqilgan do'konda server ochiq smenasiz
savdoni RAD etadi (`services/sales.py`). Kassa esa `security` kalitini KO'RMAYDI
(`api/v1/settings.py::_UI_KEYS`, QA SB-011) — shu bois offline chekni MAHALLIY yakunlab,
PULNI OLIB, mijozni jo'natib yuborardi. Tarmoq qaytganda `/sync/push` o'sha chekni 400
bilan rad etib dead-letter'ga tashlardi: pul olingan, serverda esa savdo ham, naqd
harakati ham, stok chiqimi ham YO'Q. Endi kassa qarorni SHU marshrutdan oladi va
pul olinishidan OLDIN to'sadi.

USHLANADIGAN NUQSONLAR SINFLARI
  1. FAIL-OPEN SURILISHI — siyosat yoqilgan va smena yo'q bo'lsa ham ALLOWED qaytishi.
  2. OSHKORLIK — javobga `security` obyektining boshqa maydonlari (`allow_oversell`,
     `auto_logout`) yoki `force_shift` ning O'ZI tushib qolishi.
  3. DOIRA — boshqa kassirning yoki boshqa do'konning ochiq smenasi «meniki» sanalishi.
  4. KOD YO'QOLISHI — `/sync/push` rad javobida `OPEN_SHIFT_REQUIRED` kodi bo'lmasligi
     (klient sababni mashina o'qiy olmay, dead-letter'da faqat matn qolardi).
  5. SOAT — qurilma soati chekni smena oynasidan chiqarib yuborsa ham ALLOWED berilishi.

⚠️  BU YERDA SQLite YETARLI: tekshirilayotgan narsa — MARSHRUT QARORI va `/sync/push`
    tasnifi (400 = doimiy). Pulning ledger'dagi oqibati va YOPILGAN smenaga replay
    (post-T0) esa BAZAGA bog'liq — u `test_offline_shift_policy_pg.py` da.
"""
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from tests.test_mobile_parity import _db, _hdr, _product, _shop, _staff, _token

POLICY = "/api/v1/shifts/offline-sale-policy"


# ══ YORDAMCHILAR ════════════════════════════════════════════════════════════

def _force_shift(cid, on: bool = True):
    """`security.force_shift` ni yozadi (do'kon sozlamasi)."""
    from app.models.settings import Setting
    with _db() as db:
        row = (db.query(Setting)
               .filter(Setting.company_id == cid, Setting.key == "security").first())
        if row is None:
            db.add(Setting(company_id=cid, branch_id=None, key="security",
                           value={"force_shift": on}))
        else:
            row.value = {**(row.value or {}), "force_shift": on}
        db.commit()


def _open_shift(client, H):
    r = client.post("/api/v1/shifts/open", headers=H, json={"opening_cash": 0})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _close_shift(client, H, sid):
    r = client.post(f"/api/v1/shifts/{sid}/close", headers=H, json={"counted_cash": 0})
    assert r.status_code == 200, r.text


def _policy(client, H, client_time: datetime | None = None):
    # `+00:00` dagi `+` query'da BO'SH JOY bo'lib dekodlanadi — kodlab yuboramiz.
    q = f"?client_time={quote(client_time.isoformat())}" if client_time else ""
    return client.get(POLICY + q, headers=H)


def _push(client, H, pid, *, qty=1, price=100, cu=None, sold_at=None):
    rec = {"client_uuid": str(cu or uuid.uuid4()), "payment_method": "cash",
           "items": [{"product_id": pid, "qty": qty, "unit_price": price}],
           "given_amount": price * qty}
    if sold_at:
        rec["sold_at"] = sold_at.isoformat()
    return client.post("/api/v1/sync/push", headers=H, json={"sales": [rec]})


def _kassir(d):
    """`kassa.sell` li kassir — POS yo'li AYNAN shu ruxsat bilan yuradi."""
    return _staff(d, "kassir", filiallar=(d["bids"][0],))


# ══ 1. SIYOSAT O'CHIQ — MAVJUD XULQ SAQLANADI ═══════════════════════════════

def test_1_siyosat_ochiq_smenasiz_ham_ALLOWED(client):
    """force_shift o'chiq: smenasiz savdo QONUNIY, offline navbat avvalgidek ishlaydi."""
    d = _shop()
    H, _ = _kassir(d)
    j = _policy(client, H).json()
    assert j == {"mode": "ALLOWED", "reason": None}, j


def test_1b_siyosat_ochiq_ochiq_smena_bilan_ham_ALLOWED(client):
    d = _shop()
    H, _ = _kassir(d)
    _open_shift(client, H)
    assert _policy(client, H).json()["mode"] == "ALLOWED"


# ══ 2. SIYOSAT YOQILGAN, SMENA YO'Q — TO'SILADI ═════════════════════════════

def test_2_siyosat_yoqilgan_smenasiz_BLOCKED(client):
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    j = _policy(client, H).json()
    assert j == {"mode": "BLOCKED", "reason": "OPEN_SHIFT_REQUIRED"}, j


def test_2b_javobda_security_sozlamasi_OSHKOR_QILINMAYDI(client):
    """Javob AYNAN ikki maydon: qaror va sabab. `security` ning o'zi ham, uning boshqa
    maydonlari ham (`allow_oversell`, `auto_logout`) HECH QACHON chiqmaydi."""
    from app.models.settings import Setting
    d = _shop()
    with _db() as db:
        db.add(Setting(company_id=d["cid"], branch_id=None, key="security",
                       value={"force_shift": True, "allow_oversell": True, "auto_logout": 15}))
        db.commit()
    H, _ = _kassir(d)
    j = _policy(client, H).json()
    assert set(j) == {"mode", "reason"}, j
    matn = str(j)
    for sir in ("allow_oversell", "auto_logout", "force_shift", "15"):
        assert sir not in matn, (sir, j)
    # Kassirga `GET /settings` ham `security` ni bermaydi (mavjud qoida BUZILMAGAN).
    s = client.get("/api/v1/settings", headers=H)
    assert s.status_code == 200 and "security" not in s.json(), s.text


# ══ 3. OCHIQ SMENA — RUXSAT ═════════════════════════════════════════════════

def test_3_siyosat_yoqilgan_ochiq_smena_ALLOWED(client):
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    _open_shift(client, H)
    assert _policy(client, H).json() == {"mode": "ALLOWED", "reason": None}


def test_3b_smena_yopilsa_QAYTA_BLOCKED(client):
    """Qaror HOLATGA qarab beriladi — bir marta ALLOWED olgan kassir abadiy ozod emas."""
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    sid = _open_shift(client, H)
    assert _policy(client, H).json()["mode"] == "ALLOWED"
    _close_shift(client, H, sid)
    assert _policy(client, H).json() == {"mode": "BLOCKED", "reason": "OPEN_SHIFT_REQUIRED"}


# ══ 4. DOIRA: KASSIR VA TENANT ══════════════════════════════════════════════

def test_4_boshqa_kassirning_smenasi_MENIKI_EMAS(client):
    """Smena xodimga tegishli (`ux_shifts_cashier_open`). A ning ochiq smenasi B ga
    ruxsat BERMAYDI — aks holda bitta smena butun do'konni ozod qilardi."""
    d = _shop()
    _force_shift(d["cid"])
    HA, _ = _kassir(d)
    HB, _ = _kassir(d)
    _open_shift(client, HA)
    assert _policy(client, HA).json()["mode"] == "ALLOWED"
    assert _policy(client, HB).json() == {"mode": "BLOCKED", "reason": "OPEN_SHIFT_REQUIRED"}


def test_4b_boshqa_dokonning_smenasi_va_sozlamasi_TASIR_QILMAYDI(client):
    """Tenant izolyatsiyasi: B do'konidagi ochiq smena A do'konidagi taqiqni ochmaydi."""
    a, b = _shop(), _shop()
    _force_shift(a["cid"])
    HA, _ = _kassir(a)
    HB, _ = _kassir(b)
    _open_shift(client, HB)                      # B da smena ochiq
    assert _policy(client, HA).json() == {"mode": "BLOCKED", "reason": "OPEN_SHIFT_REQUIRED"}
    assert _policy(client, HB).json()["mode"] == "ALLOWED"


def test_4c_kassa_sell_siz_xodim_403(client):
    """Darvoza savdo yo'li bilan AYNI: `kassa.sell`. Omborchi bu qarorni so'ray olmaydi."""
    d = _shop()
    H, _ = _staff(d, "omborchi", filiallar=(d["bids"][0],))
    r = _policy(client, H)
    assert r.status_code == 403, r.text


def test_4d_tokensiz_401(client):
    assert client.get(POLICY).status_code == 401


# ══ 5. QURILMA SOATI ════════════════════════════════════════════════════════

def test_5_soat_kelajakda_BLOCKED(client):
    """Soat >5 daqiqa oldinda: `sync.py::_clamp_sold_at` vaqtni tashlaydi va chek ONLAYN
    shoxiga tushib SINXRON PAYTIDA ochiq smena talab qiladi — kechikkan yo'qotish."""
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    _open_shift(client, H)
    kelajak = datetime.now(timezone.utc) + timedelta(minutes=30)
    j = _policy(client, H, kelajak).json()
    assert j == {"mode": "BLOCKED", "reason": "DEVICE_CLOCK_UNRELIABLE"}, j


def test_5b_soat_smena_ochilishidan_OLDIN_BLOCKED(client):
    """Soat orqada: chek vaqti `opened_at` dan oldin tushadi, tarixiy izlash HECH NARSA
    topmaydi va replay 400 oladi. Determinik yo'qotish — oldindan to'siladi."""
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    _open_shift(client, H)
    orqa = datetime.now(timezone.utc) - timedelta(hours=3)
    j = _policy(client, H, orqa).json()
    assert j == {"mode": "BLOCKED", "reason": "DEVICE_CLOCK_UNRELIABLE"}, j


def test_5c_soat_togri_ALLOWED(client):
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    _open_shift(client, H)
    assert _policy(client, H, datetime.now(timezone.utc)).json()["mode"] == "ALLOWED"


def test_5d_soat_yuborilmasa_tekshirilmaydi_ESKI_KLIENT(client):
    """Eski klient `client_time` yubormaydi — u yerda darvozaning O'ZI ham yo'q edi,
    shu bois holat yomonlashmaydi: qaror faqat smena bo'yicha beriladi."""
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    _open_shift(client, H)
    assert _policy(client, H).json()["mode"] == "ALLOWED"


def test_5e_siyosat_ochiq_bolsa_soat_AHAMIYATSIZ(client):
    """force_shift o'chiq: smena topilmasa ham savdo yoziladi — soat qarorga kirmaydi."""
    d = _shop()
    H, _ = _kassir(d)
    _open_shift(client, H)
    kelajak = datetime.now(timezone.utc) + timedelta(hours=2)
    assert _policy(client, H, kelajak).json()["mode"] == "ALLOWED"


# ══ 6. RAD ETISH YO'LI: `/sync/push` ════════════════════════════════════════

def test_6_smenasiz_replay_400_va_BARQAROR_KOD(client):
    """P9 TUZATISHI: rad javobi endi `OPEN_SHIFT_REQUIRED` kodini olib yuradi. Ilgari
    `code` None edi va dead-letter yozuvida faqat tilga bog'liq matn qolardi."""
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    pid = str(_product(d, name="Non", qty=50, bid=d["bids"][0])["id"])
    r = _push(client, H, pid)
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["ok"] is False, res
    assert res["retry"] is False, res              # DOIMIY rad -> dead-letter (retry emas)
    assert res["code"] == "OPEN_SHIFT_REQUIRED", res
    assert r.json()["accepted"] == 0


def test_6b_togridan_togri_POST_sales_da_ham_kod_bor(client):
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    pid = str(_product(d, name="Non", qty=50, bid=d["bids"][0])["id"])
    w = client.post("/api/v1/sales", headers=H, json={
        "items": [{"product_id": pid, "qty": 1, "unit_price": 100}],
        "payment_method": "cash", "given_amount": 100, "client_uuid": str(uuid.uuid4())})
    assert w.status_code == 400 and _hdr(w) == "OPEN_SHIFT_REQUIRED", w.text


def test_6c_ochiq_smena_bilan_replay_QABUL(client):
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    _open_shift(client, H)
    pid = str(_product(d, name="Non", qty=50, bid=d["bids"][0])["id"])
    # ⚠️  Chek vaqti smena OYNASI ichida bo'lishi SHART: tarixiy izlash `opened_at <= sold_at`
    #     talab qiladi. Smenadan OLDINGI vaqt (xato soat) — rad etiladi (test_5b darvozasi).
    r = _push(client, H, pid, sold_at=datetime.now(timezone.utc))
    assert r.json()["accepted"] == 1, r.text


# ══ 7. SMENA YOPILGANDAN KEYINGI REPLAY (tarixiy bog'lash) ═════════════════

def test_7_smena_yopilgach_replay_TARIXIY_smenaga_boglanadi(client):
    """Savdo olingan paytda ochiq bo'lgan smena keyin yopilsa ham chek O'SHA smenaga
    bog'lanadi (`sales.py`: `opened_at <= sold_at AND (closed_at IS NULL OR
    closed_at >= sold_at)`) — ya'ni force_shift QANOATLANADI.

    ⚠️  BU SQLite (legacy/pre-T0) XULQI. Naqd majburlash yoqilgan (post-T0) do'konda
        AYNI holat `CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY` bilan RAD etiladi —
        `test_offline_shift_policy_pg.py` ga qarang."""
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    sid = _open_shift(client, H)
    pid = str(_product(d, name="Non", qty=50, bid=d["bids"][0])["id"])
    sotilgan = datetime.now(timezone.utc)          # smena OCHIQ paytdagi savdo
    _close_shift(client, H, sid)
    r = _push(client, H, pid, sold_at=sotilgan)
    assert r.json()["accepted"] == 1, r.text
    from app.models.sales import Sale
    with _db() as db:
        s = db.query(Sale).filter(Sale.company_id == d["cid"]).one()
        assert str(s.shift_id) == sid, "chek YOPILGAN smenaga bog'lanishi kerak"


def test_7b_smena_umuman_bolmaganda_replay_RAD(client):
    """Smena HECH QACHON ochilmagan bo'lsa tarixiy izlash ham hech narsa topmaydi."""
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    pid = str(_product(d, name="Non", qty=50, bid=d["bids"][0])["id"])
    r = _push(client, H, pid, sold_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    res = r.json()["results"][0]
    assert (res["ok"], res["code"]) == (False, "OPEN_SHIFT_REQUIRED"), res


# ══ 8. TAKROR REPLAY — IKKI MARTA YOZILMAYDI ═══════════════════════════════

def test_8_bir_xil_client_uuid_IKKI_MARTA_yozilmaydi(client):
    """Qayta ulanish sikli bir chekni bir necha marta yuborishi mumkin (30 s interval +
    `online` hodisasi). `client_uuid` idempotentligi pulni ikki marta yozdirmasin."""
    from app.models.sales import Sale
    d = _shop()
    H, _ = _kassir(d)
    _open_shift(client, H)
    pid = str(_product(d, name="Non", qty=50, bid=d["bids"][0])["id"])
    cu = uuid.uuid4()
    r1 = _push(client, H, pid, cu=cu)
    r2 = _push(client, H, pid, cu=cu)
    assert r1.json()["accepted"] == 1 and r2.json()["accepted"] == 1, (r1.text, r2.text)
    assert r1.json()["results"][0]["id"] == r2.json()["results"][0]["id"]
    with _db() as db:
        assert db.query(Sale).filter(Sale.company_id == d["cid"]).count() == 1


def test_8b_rad_etilgan_chek_smena_ochilgach_AYNI_kalit_bilan_yoziladi(client):
    """Tiklash yo'li: rad etilgan chek dead-letter'da AYNI `client_uuid` bilan turadi.
    Kassir smenani ochib qayta yuborsa — BITTA savdo yoziladi (ikki marta emas)."""
    from app.models.sales import Sale
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    pid = str(_product(d, name="Non", qty=50, bid=d["bids"][0])["id"])
    cu = uuid.uuid4()
    assert _push(client, H, pid, cu=cu).json()["accepted"] == 0      # rad -> dead-letter
    _open_shift(client, H)
    assert _push(client, H, pid, cu=cu).json()["accepted"] == 1      # tiklash
    assert _push(client, H, pid, cu=cu).json()["accepted"] == 1      # takror — dublikat YO'Q
    with _db() as db:
        assert db.query(Sale).filter(Sale.company_id == d["cid"]).count() == 1


# ══ 9. RAD ETILGAN CHEK HECH NARSA YOZMAYDI ════════════════════════════════

def test_9_rad_etilgan_replay_STOK_va_SAVDO_yozmaydi(client):
    """400 dan keyin serverda IZ QOLMASIN: savdo yo'q, qoldiq tegilmagan. Aks holda
    dead-letter'dagi chekni qayta yuborish stokni ikki marta kamaytirardi."""
    from app.models.inventory import Inventory
    from app.models.sales import Sale
    d = _shop()
    _force_shift(d["cid"])
    H, _ = _kassir(d)
    pid = str(_product(d, name="Non", qty=50, bid=d["bids"][0])["id"])

    def _qoldiq():
        with _db() as db:
            rows = db.query(Inventory).filter(Inventory.product_id == uuid.UUID(pid)).all()
            return sum(float(x.qty) for x in rows)

    oldin = _qoldiq()
    assert _push(client, H, pid, qty=3).json()["accepted"] == 0
    with _db() as db:
        assert db.query(Sale).filter(Sale.company_id == d["cid"]).count() == 0
    assert _qoldiq() == oldin, "rad etilgan savdo qoldiqqa TEGMASLIGI kerak"
