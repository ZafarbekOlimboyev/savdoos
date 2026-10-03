# -*- coding: utf-8 -*-
"""VALYUTA KONTRAKTI — SOTUV VALYUTASI O'ZGARMAS TRANZAKSIYA SURATI.

Nuqson (2026-10-03 da production'da JONLI topilgan): `sales.currency` ustunini
HECH BIR yozuvchi o'rnatmasdi, shu bois ORM ning Python-tomon `default="UZS"` i
har qatorni "UZS" qilardi. `services/receipt/dto.py` esa
`sale.currency or company.currency or "UZS"` deb o'qiydi — `'UZS'` truthy bo'lgani
uchun `company.currency` SOTUV cheki uchun HECH QACHON so'ralmasdi. Natijada KGS
do'konda sotuv cheki `so'm`, qaytarish cheki (u `company.currency` ni to'g'ridan
o'qiydi) `сом` berardi: AYNI qator, ikki xil birlik.

Shu fayl isbotlaydi:
  · har PRODUCTION sotuv yozuvchisi valyutani ANIQ yozadi (standartga tayanmaydi);
  · valyuta TRANZAKSIYA YARATILGANDA suratga olinadi va keyin o'zgarmaydi;
  · chek SAQLANGAN sotuv valyutasini afzal ko'radi, joriy do'kon valyutasini emas;
  · sotuvga BOG'LANGAN qaytarish ASL sotuv valyutasini oladi; mustaqil qaytarish
    (original_sale_id yo'q) do'kon valyutasiga tushadi — ATAYLAB va sinaladi;
  · eski `UZS` qatorlar JIM qayta talqin QILINMAYDI (haqiqiy UZS tarixi buzilmasin).
"""
import ast
import pathlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tests.test_lot_fefo_sale import _product
from tests.test_receipt_settings import _VK, _asosiy, _db
from tests.test_sales_read_permissions import _karta_sotuv, _qaytar, _qoldiq

SRV = pathlib.Path(__file__).resolve().parents[1]
_PW = "Toshkent-Bahor-2026"


def _dokon_cur(client, currency, plan="business"):
    """Berilgan ISO valyutali yangi do'kon (ega paroli bilan) — {id, cid, h}."""
    from app.models.auth import Employee
    phone = f"+99893{uuid.uuid4().int % 10000000:07d}"
    code = f"cur{uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/admin/companies", headers=_VK, json={
        "company_name": f"Valyuta {currency}", "company_code": code,
        "owner_name": "QA Valyuta Ega", "owner_phone": phone,
        "owner_password": _PW, "plan": plan, "currency": currency})
    assert r.status_code == 200, r.text
    lg = client.post("/api/v1/auth/login/password", json={"phone": phone, "password": _PW})
    assert lg.status_code == 200, lg.text
    eid = lg.json()["employee"]["id"]
    with _db() as db:
        cid = db.get(Employee, uuid.UUID(eid)).company_id
    return {"id": eid, "cid": str(cid),
            "h": {"Authorization": f"Bearer {lg.json()['access_token']}"}}


def _sotuv(client, h, bid):
    """Mahsulot + qoldiq + KARTA sotuvi (smena/kassa talab qilmaydi) -> sale json."""
    pid = _product(client, h)
    _qoldiq(pid, bid, 10)
    return pid, _karta_sotuv(client, h, pid, qty=1, price=1000)


def _sale_row(sale_id):
    from app.models.sales import Sale
    with _db() as db:
        s = db.get(Sale, uuid.UUID(sale_id))
        return None if s is None else (s.currency, s.company_id)


def _company_currency_qo(cid, yangi):
    """Do'kon valyutasini TO'G'RIDAN-TO'G'RI o'zgartiradi.

    API'da bunday endpoint YO'Q (`companies.currency` faqat yaratilishda yoziladi) —
    bu kelajakdagi imkoniyatni MODELLASHTIRADI: tarixiy sotuv o'zgarmasligini sinash
    uchun boshqa yo'l yo'q.
    """
    from app.models.org import Company
    with _db() as db:
        co = db.get(Company, uuid.UUID(cid))
        co.currency = yangi
        db.commit()


# ── 1. Yozuvchilar: valyuta yaratilishda SURATGA olinadi ─────────────────────

def test_kgs_dokon_sotuvi_KGS_bilan_saqlanadi(client):
    """ASOSIY NUQSON: KGS do'kon sotuvi UZS bo'lib yozilardi."""
    d = _dokon_cur(client, "KGS")
    bid = _asosiy(client, d["h"])
    _, sale = _sotuv(client, d["h"], bid)
    cur, _cid = _sale_row(sale["id"])
    assert cur == "KGS", f"sotuv valyutasi suratga olinmagan: {cur!r}"


def test_uzs_dokon_sotuvi_UZS_bilan_saqlanadi(client):
    d = _dokon_cur(client, "UZS")
    bid = _asosiy(client, d["h"])
    _, sale = _sotuv(client, d["h"], bid)
    cur, _cid = _sale_row(sale["id"])
    assert cur == "UZS", cur


def test_sync_push_yoli_ham_valyutani_yozadi(client):
    """Oflayn replay (`/sync/push`) AYNI yozuvchidan o'tadi — u ham surat oladi."""
    d = _dokon_cur(client, "KGS")
    bid = _asosiy(client, d["h"])
    pid = _product(client, d["h"])
    _qoldiq(pid, bid, 10)
    r = client.post("/api/v1/sync/push", headers=d["h"], json={"sales": [{
        "items": [{"product_id": pid, "qty": 1, "unit_price": 1000}],
        "payment_method": "card", "given_amount": 1000,
        "client_uuid": str(uuid.uuid4())}]})
    assert r.status_code == 200, r.text
    ids = [x.get("id") for x in r.json().get("results", []) if x.get("id")]
    assert ids, r.text
    cur, _cid = _sale_row(ids[0])
    assert cur == "KGS", cur


# ── 2. Surat O'ZGARMAS: do'kon valyutasi keyin o'zgarsa ham ──────────────────

def test_dokon_valyutasi_keyin_ozgarsa_tarix_ozgarmaydi(client):
    d = _dokon_cur(client, "KGS")
    bid = _asosiy(client, d["h"])
    _, sale = _sotuv(client, d["h"], bid)
    assert _sale_row(sale["id"])[0] == "KGS"

    _company_currency_qo(d["cid"], "UZS")           # do'kon keyin UZS ga o'tdi

    assert _sale_row(sale["id"])[0] == "KGS", "tarixiy sotuv valyutasi qayta yozilgan"
    r = client.get(f"/api/v1/sales/{sale['id']}/receipt", headers=d["h"])
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["currency"] == "KGS", "chek joriy do'kon valyutasiga ergashgan"


# ── 3. Chek: SAQLANGAN sotuv valyutasi ustun ────────────────────────────────

@pytest.mark.parametrize("cur", ["KGS", "UZS"])
def test_sotuv_cheki_saqlangan_valyutani_beradi(client, cur):
    d = _dokon_cur(client, cur)
    bid = _asosiy(client, d["h"])
    _, sale = _sotuv(client, d["h"], bid)
    r = client.get(f"/api/v1/sales/{sale['id']}/receipt", headers=d["h"])
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["currency"] == cur


@pytest.mark.parametrize("cur", ["KGS", "UZS"])
def test_boglangan_qaytarish_cheki_ASL_sotuv_valyutasini_beradi(client, cur):
    d = _dokon_cur(client, cur)
    bid = _asosiy(client, d["h"])
    pid, sale = _sotuv(client, d["h"], bid)
    q = _qaytar(client, d["h"], sale["id"], pid)
    assert q.status_code == 200, q.text
    r = client.get(f"/api/v1/returns/{q.json()['id']}/receipt", headers=d["h"])
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["currency"] == cur


def test_bogangan_qaytarish_dokon_valyutasiga_ERGASHMAYDI(client):
    """Qaytarish ASL sotuvga bog'langan bo'lsa, do'kon keyin valyutani o'zgartirsa ham
    chekda ASL sotuv valyutasi qoladi."""
    d = _dokon_cur(client, "KGS")
    bid = _asosiy(client, d["h"])
    pid, sale = _sotuv(client, d["h"], bid)
    q = _qaytar(client, d["h"], sale["id"], pid)
    assert q.status_code == 200, q.text

    _company_currency_qo(d["cid"], "UZS")

    r = client.get(f"/api/v1/returns/{q.json()['id']}/receipt", headers=d["h"])
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["currency"] == "KGS"


def test_mustaqil_qaytarish_API_tomonidan_RAD_etiladi(client):
    """DOMEN QOIDASI: `original_sale_id` sxemada ixtiyoriy va DB'da nullable, LEKIN
    API chek raqamisiz qaytarishni RAD etadi. Ya'ni API orqali tug'ilgan HAR
    qaytarish sotuvga bog'langan — shu bois valyuta manbai ANIQ."""
    d = _dokon_cur(client, "KGS")
    bid = _asosiy(client, d["h"])
    pid = _product(client, d["h"])
    _qoldiq(pid, bid, 10)
    q = client.post("/api/v1/returns", headers=d["h"], json={
        "original_sale_id": None, "reason": "customer", "restock": True,
        "refund_method": "card", "client_uuid": str(uuid.uuid4()),
        "items": [{"product_id": pid, "qty": 1, "unit_price": 1000}]})
    assert q.status_code == 400, q.text
    assert "asl chek" in q.json()["detail"]


def test_boglanmagan_TARIXIY_qaytarish_dokon_valyutasiga_tushadi(client):
    """Bog'lanmagan qaytarish faqat ESKI qator bo'lishi mumkin (API endi rad etadi).
    Unda bog'lanadigan sotuv yo'q, shu bois DTO do'kon valyutasini oladi —
    hujjatlangan ZAXIRA. (`returns` jadvalida valyuta ustuni YO'Q.)"""
    from app.models.sales import Return
    d = _dokon_cur(client, "KGS")
    bid = _asosiy(client, d["h"])
    pid, sale = _sotuv(client, d["h"], bid)
    q = _qaytar(client, d["h"], sale["id"], pid)
    assert q.status_code == 200, q.text
    rid = q.json()["id"]
    with _db() as db:                                  # eski "bog'lanmagan" qatorni modellaymiz
        db.get(Return, uuid.UUID(rid)).original_sale_id = None
        db.commit()
    r = client.get(f"/api/v1/returns/{rid}/receipt", headers=d["h"])
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["currency"] == "KGS", "zaxira do'kon valyutasi bo'lishi kerak"


# ── 4. Eski qatorlar JIM qayta talqin QILINMAYDI ────────────────────────────

def test_eski_UZS_qatori_KGS_dokonda_ham_UZS_qoladi(client):
    """Tarixiy haqiqat saqlanadi: KGS do'konda yozilgan ESKI `UZS` qator chekda
    HAMON UZS beradi. Aks holda haqiqiy UZS-davri tarixi buzilardi."""
    from app.models.sales import Sale
    d = _dokon_cur(client, "KGS")
    bid = _asosiy(client, d["h"])
    _, sale = _sotuv(client, d["h"], bid)
    assert _sale_row(sale["id"])[0] == "KGS"

    with _db() as db:                                 # eski (nuqsonli davr) qatorini modellaymiz
        db.get(Sale, uuid.UUID(sale["id"])).currency = "UZS"
        db.commit()

    r = client.get(f"/api/v1/sales/{sale['id']}/receipt", headers=d["h"])
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["currency"] == "UZS", "eski qator JIM KGS ga aylantirilgan"


# ── 5. DARVOZA: production yozuvchisi standartga TAYANA OLMAYDI ─────────────

def _valyutali_modellar() -> set[str]:
    """ORM METADATASIDAN: valyuta ustuni bor va Python-tomon STANDARTI bo'lgan modellar.

    Ro'yxat qo'lda yozilmaydi — yangi shunday model qo'shilsa darvoza uni O'ZI
    qamrab oladi. Standarti YO'Q ustun (masalan `cash` sxemasi) allaqachon
    fail-closed, shu bois talab qilinmaydi.
    """
    import app.models  # noqa: F401  (barcha modellarni ro'yxatga oladi)
    from app.db.base import Base
    out = set()
    for cls in Base.registry._class_registry.values():
        t = getattr(cls, "__table__", None)
        if t is None or "currency" not in t.c:
            continue
        if t.c["currency"].default is not None:
            out.add(cls.__name__)
    return out


def _konstruktorlar(py: pathlib.Path, _modellar=None):
    """Faylda `<Model>(...)` ko'rinishidagi konstruktorlar: (model, qator, kwarg nomlari)."""
    _modellar = _valyutali_modellar() if _modellar is None else _modellar
    try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - sintaksis xatosi boshqa darvozada tutiladi
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        nom = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
        if nom in _modellar:
            yield nom, node.lineno, {k.arg for k in node.keywords if k.arg}


def test_production_yozuvchilari_valyutani_ANIQ_yozadi():
    """Valyuta ustuni bor modelni `currency=` bermasdan qurish TAQIQ.

    Nega darvoza, nega DB standartini olib tashlamadik: jonli production sxemasida
    `sales.currency` ustunida DDL DEFAULT UMUMAN YO'Q (2026-10-03 da o'lchandi:
    `information_schema.columns.column_default IS NULL`) — qiymatni ORM ning
    Python-tomon `default="UZS"` i beradi. Shu `default=` ni olib tashlash
    production uchun xavfsiz, LEKIN u 27 ta TEST qurish joyini sindiradi
    (`tests/cash/*`, `tests/test_catalog_v2*`, lot/mobile-parity ...) — ya'ni
    standartning haqiqiy iste'molchilari testlar, production emas. Shu bois
    standart QOLADI va production kodi uchun shu darvoza qo'yiladi.
    """
    modellar = _valyutali_modellar()
    assert {"Sale", "Purchase", "Company"} <= modellar, modellar
    # SHIPPED kod yo'llari: server paketi + yetkazib berilgan skriptlar/vositalar.
    # (Hozir `app/` tashqarisida konstruktor YO'Q — bu kelajak uchun qorovul.)
    kokler = [SRV / "app", SRV / "tools", SRV.parents[1] / "scripts"]
    buzuq = []
    for kok in kokler:
        if not kok.is_dir():
            continue
        for py in sorted(kok.rglob("*.py")):
            if "__pycache__" in py.parts or ".venv" in py.parts:
                continue
            for nom, qator, kwargs in _konstruktorlar(py, modellar):
                if "currency" not in kwargs:
                    buzuq.append(f"{py}:{qator} {nom}(...) — `currency=` yo'q")
    assert not buzuq, "production yozuvchisi valyuta standartiga tayanadi:\n" + "\n".join(buzuq)


def test_darvoza_OZI_ishlaydi():
    """Darvoza yolg'on-yashil bo'lmasin: `currency=` siz konstruktorni TUTADI."""
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        p = pathlib.Path(t) / "x.py"
        p.write_text("s = Sale(company_id=1, total=2)\n", encoding="utf-8")
        topildi = [(n, q, k) for n, q, k in _konstruktorlar(p)]
        assert topildi and "currency" not in topildi[0][2]
        p.write_text("s = Sale(company_id=1, currency='KGS')\n", encoding="utf-8")
        topildi = [(n, q, k) for n, q, k in _konstruktorlar(p)]
        assert topildi and "currency" in topildi[0][2]


# ── 6. NEGATIV NAZORAT: eski yozuvchi xulqi KGS sinovini YIQITADI ───────────

def test_NEGATIV_eski_yozuvchi_xulqi_KGS_ni_bermaydi(client):
    """ORM standartiga tayanish (eski xulq) KGS do'konda ham `UZS` beradi.

    Bu nuqsonning MEXANIZMINI qadaydi: agar kimdir yozuvchidan `currency=` ni
    olib tashlasa, yuqoridagi birinchi sinov yiqiladi — chunki standart hamon
    `UZS`. Shu test o'zi standartning qiymatini o'lchaydi, tuzatishni emas.
    """
    from app.models.sales import Sale
    d = _dokon_cur(client, "KGS")
    bid = _asosiy(client, d["h"])
    with _db() as db:
        eski = Sale(                                     # ATAYLAB `currency=` YO'Q — eski xulq
            company_id=uuid.UUID(d["cid"]), branch_id=uuid.UUID(bid),
            cashier_id=uuid.UUID(d["id"]), receipt_no="NEG-" + uuid.uuid4().hex[:8],
            subtotal=Decimal("0"), discount_total=Decimal("0"), total=Decimal("0"),
            cost_total=Decimal("0"), tax_total=Decimal("0"),
            sold_at=datetime.now(timezone.utc),
            client_uuid=uuid.uuid4(), is_offline=False)
        db.add(eski)
        db.commit()
        sid = str(eski.id)
    assert _sale_row(sid)[0] == "UZS", "standart endi UZS emas — negativ nazoratni yangilang"
    assert _sale_row(sid)[0] != "KGS"
