# -*- coding: utf-8 -*-
"""R6.8 P0-1 — HISOBDAN CHIQARISH IKKI MARTA YOZILMASIN.

NUQSON (R6.7 auditida topilgan). Ikki marta yozishga qarshi YAGONA to'siq —
mobil ekrandagi `_frozenUuid` (`writeoff_screen.dart:93`) va u FAQAT widget
`State` ichida yashaydi. Kalit `Random.secure()` UUIDv4, tanadan KELIB
CHIQMAYDI, ya'ni qayta hisoblanmaydi. Server dedup'i esa AYNAN
`(client_uuid, product_id, type)` doirasida (`ux_stockmov_client_prod_type`) —
tana bo'yicha ZAXIRA YO'Q.

Natijada: 401, qulfdan chiqish, qulf tiklash, crash yoki iOS'ning ilovani
fonda o'ldirishi `State` ni yo'q qiladi; operator AYNI amalni qaytadan
kiritadi; YANGI tasodifiy kalit serverda YANGI, qabul qilinadigan write-off
bo'ladi va QOLDIQ + TANNARX IKKI MARTA hisobdan chiqadi.

TUZATISH ikki qatlam:
  A. SERVER — «so'nggi o'xshash chiqarish» darvozasi (`confirm_duplicate`):
     ayni filial + mahsulot + miqdor + sabab, BOSHQA kalit bilan va oyna
     ichida kelsa -> 409 `WRITEOFF_DUPLICATE_SUSPECTED`. Bu DEDUP EMAS: amal
     jimgina yutilmaydi, operator TASDIQLASA (`confirm_duplicate=true`)
     ikkinchi yozuv BAJARILADI — chunki bir xil mahsulot/miqdor/sabab bilan
     ikkita HAQIQIY, alohida chiqarish qonuniy bo'lishi mumkin.
  B. SERVER — kalit QAYTA ISHLATILGANINI aniqlash: ayni kalit BOSHQA mazmun
     bilan kelsa `duplicate: true` DEYILMAYDI (u yolg'on «yozildi» signali
     edi) -> 409 `IDEMPOTENCY_KEY_REUSED`, repo konvensiyasi bilan AYNI.
  C. SERVER — holat so'rovi: `GET /inventory/writeoff/status?client_uuid=`
     natijasi NOMA'LUM urinishni TAXMINSIZ hal qiladi.
  (Mobil qatlam — `DraftGuard` orqali kalitni saqlash — alohida:
   `apps/mobile/test/r68_writeoff_draft_test.dart`.)

Bu fayl isbotlaydi:
   1. normal 2xx — bitta harakat qatori, qoldiq bir marta kamaydi;
   2. AYNI kalit + AYNI tana -> `duplicate: true`, YANGI qator YO'Q;
   3. AYNI kalit + BOSHQA miqdor -> 409 `IDEMPOTENCY_KEY_REUSED` (yolg'on
      «duplicate» EMAS), yozuv YO'Q;
   4. AYNI kalit + BOSHQA sabab -> 409, yozuv YO'Q;
   5. BOSHQA kalit + AYNI tana (javob yo'qolgan urinish) -> 409
      `WRITEOFF_DUPLICATE_SUSPECTED`, IKKINCHI yozuv YO'Q;
   6. 5-holat + `confirm_duplicate=true` -> 200, IKKINCHI yozuv BOR
      (haqiqiy alohida amal bloklanmaydi);
   7. BOSHQA filial -> darvoza TEGMAYDI (boshqa zaxira);
   8. BOSHQA miqdor -> darvoza TEGMAYDI;
   9. BOSHQA sabab -> darvoza TEGMAYDI;
  10. oyna TASHQARISIDAGI eski chiqarish -> darvoza TEGMAYDI;
  11. BOSHQA xodim ham to'siladi (zarar xodimga bog'liq emas — qoldiq bitta);
  12. holat so'rovi: yozilgan kalit -> `recorded: true` + tafsilot;
  13. holat so'rovi: yozilmagan kalit -> `recorded: false`;
  14. holat so'rovi BOSHQA do'kon kalitini KO'RMAYDI (tenant izolyatsiyasi).
"""
import uuid as _uuid
from decimal import Decimal

import pytest

API = "/api/v1"


# ══ YORDAMCHILAR ═════════════════════════════════════════════════════════════

def _db():
    from app.db.session import SessionLocal
    return SessionLocal()


def _own_product():
    """SHU FAYLGA tegishli KUZATUVSIZ mahsulot yaratadi.

    ⚠️  NEGA `products[0]` EMAS. `client` fiksturasi SEANS doirasida, ya'ni
        bitta bazani butun to'plam bo'lishadi va boshqa testlar birinchi
        mahsulotda PARTIYA KUZATUVINI YOQADI (kuzatuv ortga qaytmaydi).
        O'shanda bu fayldagi kuzatuvsiz kirim 400 oladi: «partiya bo'yicha
        kuzatiladi — har kirim qatori uchun `lots` MAJBURIY». O'lchangan:
        to'liq to'plamda 14 setup xatosi, yolg'iz yurishda YASHIL — ya'ni
        nuqson TARTIBGA tayanish edi.
    ⚠️  AYNI SINF uchinchi marta: tartibsiz yoki umumiy fikstura qatorini
        olish SEANS doirasidagi bazada ishonchsiz. Qoida: o'z qatorini yarat.
    """
    from app.models.catalog import Product, Unit
    from app.models.org import Company
    s = _db()
    try:
        cid = s.query(Company).filter(Company.code == "demo").one().id
        suffix = _uuid.uuid4().hex[:8]
        unit = s.query(Unit).filter(Unit.code == "dona").first() or s.query(Unit).first()
        p = Product(id=_uuid.uuid4(), company_id=cid, name=f"R68W {suffix}",
                    article_code=f"R68W-{suffix}", sku=suffix,
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100,
                    tax_rate=0, track_lots=False)
        s.add(p)
        s.commit()
        return str(p.id)
    finally:
        s.close()


def _kirim(client, H, pid, qty=100):
    r = client.post(f"{API}/receiving/commit", headers=H, json={
        "items": [{"product_id": pid, "qty": qty, "unit_cost": 100, "unit": "dona"}],
        "supplier_id": None, "payment": "cash", "client_uuid": str(_uuid.uuid4()),
        "source": "manual"})
    assert r.status_code == 200, r.text


def _writeoff(client, H, pid, **kw):
    body = {"product_id": pid, "qty": kw.pop("qty", 3), "reason": kw.pop("reason", "brak"),
            "client_uuid": kw.pop("client_uuid", str(_uuid.uuid4()))}
    body.update(kw)
    return client.post(f"{API}/inventory/writeoff", headers=H, json=body)


def _harakatlar(pid, *, branch_id=None):
    """Shu mahsulotdagi BARCHA `writeoff` harakat qatorlari (eng yangisi oldinda)."""
    from app.models.enums import MovementType
    from app.models.inventory import StockMovement
    s = _db()
    try:
        q = (s.query(StockMovement)
             .filter(StockMovement.product_id == _uuid.UUID(pid),
                     StockMovement.type == MovementType.writeoff))
        if branch_id:
            q = q.filter(StockMovement.branch_id == _uuid.UUID(branch_id))
        return [(str(m.id), str(m.client_uuid) if m.client_uuid else None,
                 Decimal(str(m.qty)), m.reason, str(m.branch_id))
                for m in q.order_by(StockMovement.created_at.desc()).all()]
    finally:
        s.close()


def _qoldiq(pid, branch_id):
    from app.models.inventory import Inventory
    s = _db()
    try:
        inv = (s.query(Inventory)
               .filter(Inventory.product_id == _uuid.UUID(pid),
                       Inventory.branch_id == _uuid.UUID(branch_id)).first())
        return Decimal(str(inv.qty)) if inv else None
    finally:
        s.close()


def _actor_branch_id(client, H):
    r = client.get(f"{API}/auth/context", headers=H)
    assert r.status_code == 200, r.text
    return r.json()["actor_branch"]["id"]


def _ikkinchi_filial():
    from app.models.org import Branch
    s = _db()
    try:
        cid = s.query(Branch).first().company_id
        b = s.query(Branch).filter(Branch.company_id == cid, Branch.code == "F0R68W").first()
        if b is None:
            b = Branch(id=_uuid.uuid4(), company_id=cid, code="F0R68W",
                       name="R6.8 writeoff filial", timezone="Asia/Tashkent", is_active=True)
            s.add(b)
            s.commit()
        return str(b.id)
    finally:
        s.close()


def _eskirtir(movement_id: str, daqiqa: int):
    """Harakat qatorini `daqiqa` daqiqa ORQAGA suradi — darvoza oynasini sinash."""
    from datetime import timedelta
    from app.models.inventory import StockMovement
    s = _db()
    try:
        m = s.get(StockMovement, _uuid.UUID(movement_id))
        m.created_at = m.created_at - timedelta(minutes=daqiqa)
        s.commit()
    finally:
        s.close()


def _kod(r) -> str | None:
    return r.headers.get("X-Error-Code")


@pytest.fixture
def mahsulot(client, admin_headers):
    """SHU TESTGA tegishli, zaxirasi to'ldirilgan mahsulot + yozuv filiali."""
    pid = _own_product()
    _kirim(client, admin_headers, pid, qty=200)
    return pid, _actor_branch_id(client, admin_headers)


@pytest.fixture(autouse=True)
def _tozalash(client):
    """HAR testdan oldin shu mahsulotning `writeoff` qatorlarini olib tashlaydi.

    ⚠️  NEGA KERAK. `client` SEANS doirasida, ya'ni bitta bazani hamma test
        bo'lishadi. Yangi darvoza AYNI oyna ichidagi o'xshash chiqarishlarni
        to'sadi — oldingi testning qatorlari keyingi testni YOLG'ON 409 qilardi.
    ⚠️  FAQAT `writeoff`: kirim, sotuv va boshqa harakatlarga TEGILMAYDI.
    """
    from app.models.catalog import Product
    from app.models.enums import MovementType
    from app.models.inventory import StockMovement
    s = _db()
    try:
        #  ⚠️  FAQAT SHU FAYL MAHSULOTLARI. Ilgari butun jadvaldagi `writeoff`
        #      qatorlari o'chirilardi — bu BOSHQA testlarning dalillarini ham
        #      yo'q qilardi (to'liq to'plamda jim sizish).
        own = [r[0] for r in s.query(Product.id).filter(Product.name.like("R68W %")).all()]
        if own:
            s.query(StockMovement).filter(
                StockMovement.product_id.in_(own),
                StockMovement.type == MovementType.writeoff).delete(synchronize_session=False)
            s.commit()
    finally:
        s.close()
    yield


# ══ 1. NORMAL YO'L ═══════════════════════════════════════════════════════════

def test_normal_chiqarish_BITTA_qator_va_qoldiq_bir_marta_kamayadi(client, admin_headers,
                                                                   mahsulot):
    pid, bid = mahsulot
    oldin = _qoldiq(pid, bid)

    r = _writeoff(client, admin_headers, pid, qty=3)

    assert r.status_code == 200, r.text
    assert r.json().get("duplicate") is not True
    mv = _harakatlar(pid, branch_id=bid)
    assert len(mv) == 1, mv
    assert mv[0][2] == Decimal("-3")
    assert _qoldiq(pid, bid) == oldin - Decimal("3")


# ══ 2-4. AYNI KALIT ══════════════════════════════════════════════════════════

def test_AYNI_kalit_AYNI_tana_duplicate_va_YANGI_qator_YOQ(client, admin_headers, mahsulot):
    pid, bid = mahsulot
    cu = str(_uuid.uuid4())
    assert _writeoff(client, admin_headers, pid, qty=3, client_uuid=cu).status_code == 200
    keyin = _qoldiq(pid, bid)

    r = _writeoff(client, admin_headers, pid, qty=3, client_uuid=cu)

    assert r.status_code == 200, r.text
    assert r.json().get("duplicate") is True, r.text
    assert len(_harakatlar(pid, branch_id=bid)) == 1
    assert _qoldiq(pid, bid) == keyin, "takror chiqarish qoldiqni yana kamaytirdi"


def test_AYNI_kalit_BOSHQA_miqdor_409_IDEMPOTENCY_KEY_REUSED(client, admin_headers, mahsulot):
    """⚠️  NUQSON SINFI. Ilgari bu yo'l `duplicate: true` qaytarardi: operator
    3 dona chiqarishni so'ragan, server esa oldin 5 ni yozgan va javob
    «bajarildi» deb ko'rinardi. Hech narsa yozilmagan — bu TAKROR emas, YANGI
    amal. Repo konvensiyasi: `IDEMPOTENCY_KEY_REUSED` (409)."""
    pid, bid = mahsulot
    cu = str(_uuid.uuid4())
    assert _writeoff(client, admin_headers, pid, qty=5, client_uuid=cu).status_code == 200
    keyin = _qoldiq(pid, bid)

    r = _writeoff(client, admin_headers, pid, qty=3, client_uuid=cu)

    assert r.status_code == 409, r.text
    assert _kod(r) == "IDEMPOTENCY_KEY_REUSED", r.headers
    assert len(_harakatlar(pid, branch_id=bid)) == 1
    assert _qoldiq(pid, bid) == keyin


def test_AYNI_kalit_BOSHQA_sabab_409(client, admin_headers, mahsulot):
    pid, bid = mahsulot
    cu = str(_uuid.uuid4())
    assert _writeoff(client, admin_headers, pid, qty=3, reason="brak",
                     client_uuid=cu).status_code == 200

    r = _writeoff(client, admin_headers, pid, qty=3, reason="expired", client_uuid=cu)

    assert r.status_code == 409, r.text
    assert _kod(r) == "IDEMPOTENCY_KEY_REUSED", r.headers
    assert len(_harakatlar(pid, branch_id=bid)) == 1


# ══ 5-6. BOSHQA KALIT + AYNI TANA — ASOSIY P0 ════════════════════════════════

def test_BOSHQA_kalit_AYNI_tana_409_va_IKKINCHI_yozuv_YOQ(client, admin_headers, mahsulot):
    """AYNAN P0 ssenariysi: birinchi urinish serverda YOZILGAN, javob klientga
    YETMAGAN, `State` yo'q bo'lgan, operator qaytadan kiritgan — YANGI kalit."""
    pid, bid = mahsulot
    assert _writeoff(client, admin_headers, pid, qty=3).status_code == 200
    keyin = _qoldiq(pid, bid)

    r = _writeoff(client, admin_headers, pid, qty=3)      # YANGI kalit, AYNI tana

    assert r.status_code == 409, r.text
    assert _kod(r) == "WRITEOFF_DUPLICATE_SUSPECTED", r.headers
    assert len(_harakatlar(pid, branch_id=bid)) == 1, "IKKINCHI write-off yozildi"
    assert _qoldiq(pid, bid) == keyin, "qoldiq IKKI MARTA kamaydi"


def test_TASDIQLANGAN_takroriy_amal_OTADI_va_ikkinchi_yozuv_BOR(client, admin_headers,
                                                                mahsulot):
    """⚠️  BU DEDUP EMAS. Bir xil mahsulot/miqdor/sabab bilan ikkita HAQIQIY,
    alohida chiqarish qonuniy bo'lishi mumkin (javonda yana shuncha brak
    topildi). Operator TASDIQLAGANDAN keyin ikkinchi yozuv BAJARILADI."""
    pid, bid = mahsulot
    assert _writeoff(client, admin_headers, pid, qty=3).status_code == 200
    keyin = _qoldiq(pid, bid)

    r = _writeoff(client, admin_headers, pid, qty=3, confirm_duplicate=True)

    assert r.status_code == 200, r.text
    mv = _harakatlar(pid, branch_id=bid)
    assert len(mv) == 2, mv
    assert _qoldiq(pid, bid) == keyin - Decimal("3")


# ══ 7-11. DARVOZANING ANIQLIGI (yolg'on pozitivlar) ══════════════════════════

def test_BOSHQA_filial_darvozaga_TUSHMAYDI(client, admin_headers, mahsulot):
    pid, bid = mahsulot
    b2 = _ikkinchi_filial()
    # Ikkinchi filialga ham zaxira kerak (`updated_at` NOT NULL).
    from datetime import datetime, timezone
    from app.models.inventory import Inventory
    s = _db()
    try:
        s.add(Inventory(id=_uuid.uuid4(), product_id=_uuid.UUID(pid),
                        branch_id=_uuid.UUID(b2), qty=Decimal("50"), min_qty=0,
                        updated_at=datetime.now(timezone.utc)))
        s.commit()
    finally:
        s.close()
    assert _writeoff(client, admin_headers, pid, qty=3).status_code == 200

    r = _writeoff(client, admin_headers, pid, qty=3, branch_id=b2)

    assert r.status_code == 200, r.text
    assert len(_harakatlar(pid, branch_id=b2)) == 1
    assert len(_harakatlar(pid, branch_id=bid)) == 1


def test_BOSHQA_miqdor_darvozaga_TUSHMAYDI(client, admin_headers, mahsulot):
    pid, bid = mahsulot
    assert _writeoff(client, admin_headers, pid, qty=3).status_code == 200

    r = _writeoff(client, admin_headers, pid, qty=4)

    assert r.status_code == 200, r.text
    assert len(_harakatlar(pid, branch_id=bid)) == 2


def test_BOSHQA_sabab_darvozaga_TUSHMAYDI(client, admin_headers, mahsulot):
    pid, bid = mahsulot
    assert _writeoff(client, admin_headers, pid, qty=3, reason="brak").status_code == 200

    r = _writeoff(client, admin_headers, pid, qty=3, reason="expired")

    assert r.status_code == 200, r.text
    assert len(_harakatlar(pid, branch_id=bid)) == 2


def test_OYNA_tashqarisidagi_eski_chiqarish_darvozaga_TUSHMAYDI(client, admin_headers,
                                                                mahsulot):
    from app.api.v1.inventory import WRITEOFF_DUP_WINDOW_MIN
    pid, bid = mahsulot
    assert _writeoff(client, admin_headers, pid, qty=3).status_code == 200
    _eskirtir(_harakatlar(pid, branch_id=bid)[0][0], WRITEOFF_DUP_WINDOW_MIN + 5)

    r = _writeoff(client, admin_headers, pid, qty=3)

    assert r.status_code == 200, r.text
    assert len(_harakatlar(pid, branch_id=bid)) == 2


def test_BOSHQA_xodim_HAM_tosiladi(client, admin_headers, mahsulot):
    """⚠️  DARVOZA FILIAL DOIRASIDA, xodim doirasida EMAS — va bu ataylab.
    Zarar qoldiqda, qoldiq esa bitta: kim ikkinchi marta yozishidan qat'iy
    nazar partiya va tannarx ikki marta chiqadi. Tasdiqlash yo'li ochiq, ya'ni
    haqiqiy alohida amal bloklanmaydi."""
    pid, bid = mahsulot
    assert _writeoff(client, admin_headers, pid, qty=3).status_code == 200
    # Ikkinchi xodim — omborchi (ombor.edit bor), demo seed'dan.
    r = client.post(f"{API}/auth/login/password",
                    json={"phone": "+998975678901", "password": "demo1234"})
    assert r.status_code == 200, r.text
    H2 = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = _writeoff(client, H2, pid, qty=3)

    assert r.status_code == 409, r.text
    assert _kod(r) == "WRITEOFF_DUPLICATE_SUSPECTED", r.headers
    assert len(_harakatlar(pid, branch_id=bid)) == 1


# ══ 11b. TARIXIY QAYTA YURISH DARVOZADAN CHIQARILGAN ═════════════════════════

def test_TARIXIY_yol_darvozadan_CHIQARILGAN():
    """Oyna JONLI operator evristikasi — o'tmish hodisalarini qayta ijro
    etishda uning ma'nosi YO'Q. Yaqinda bo'lgan JONLI chiqarish tarixiy
    replay'ni to'sib qo'ymasligi SHART.

    ⚠️  BU MANBA TASDIG'I, va bu ATAYLAB. Tarixiy yozuvni haqiqiy chaqirish
        `historical.enter(...)` kontekstini, u esa DEMO IJARACHI shartlarini
        (`assert_demo_tenant`) talab qiladi — o'sha mashina
        `tests/test_h3b_historical_writers.py` da allaqachon qurilgan va
        u HAQIQIY tarixiy hisobdan chiqarishni bajaradi (:272). Shu bois
        XULQ qoplamasi o'sha faylda; bu yerda faqat SHART qadab qo'yiladi,
        ya'ni darvoza tarixiy yo'lga jimgina kirib ketsa sezilади.
    """
    import pathlib
    src = pathlib.Path("app/api/v1/inventory.py").read_text(encoding="utf-8")
    assert "if at is None and not data.confirm_duplicate:" in src, \
        "darvoza tarixiy yo'lni (`at is not None`) CHIQARMAYDI — yaqinda " \
        "bo'lgan jonli chiqarish tarixiy replay'ni to'sib qo'yishi mumkin"
    #  `at` tarixiy yozuvchiga AYNAN shu yo'l bilan yetadi.
    hx = pathlib.Path("app/api/v1/historical_exec.py").read_text(encoding="utf-8")
    assert "_writeoff_once(p, emp, db, at=at)" in hx


# ══ 12-14. HOLAT SO'ROVI (RECONCILIATION) ════════════════════════════════════

def test_holat_sorovi_YOZILGAN_kalitni_topadi(client, admin_headers, mahsulot):
    pid, _bid = mahsulot
    cu = str(_uuid.uuid4())
    assert _writeoff(client, admin_headers, pid, qty=3, client_uuid=cu).status_code == 200

    r = client.get(f"{API}/inventory/writeoff/status",
                   headers=admin_headers, params={"client_uuid": cu, "product_id": pid})

    assert r.status_code == 200, r.text
    j = r.json()
    assert j["recorded"] is True, j
    assert abs(float(j["qty"]) - 3.0) < 1e-9, j
    assert j["reason"] == "brak", j
    assert j.get("at"), j


def test_holat_sorovi_YOZILMAGAN_kalit_uchun_false(client, admin_headers, mahsulot):
    pid, _bid = mahsulot

    r = client.get(f"{API}/inventory/writeoff/status", headers=admin_headers,
                   params={"client_uuid": str(_uuid.uuid4()), "product_id": pid})

    assert r.status_code == 200, r.text
    assert r.json()["recorded"] is False, r.text


def test_holat_sorovi_BOSHQA_dokon_mahsulotini_KORMAYDI(client, admin_headers, mahsulot):
    """⚠️  `stock_movements` da `company_id` ustuni YO'Q (`inventory.py:261` izohi):
    mahsulotsiz yoki tekshirilmagan so'rov BOSHQA do'konning kalitini ochib
    berardi. Shu bois mahsulot EGALIGI tekshiriladi.

    ⚠️  HOLAT KODI 400, 404 EMAS — `_get_product` butun modulda AYNI shunday
        javob beradi («Mahsulot topilmadi: <so'ralgan id>»). Yangi marshrut uchun
        BOSHQA konvensiya yaratilmaydi; muhimi — begona do'kon ma'lumoti oshkor
        BO'LMASLIGI va javob o'sha kalit mavjudligini ham aytmasligi."""
    from app.models.catalog import Product, Unit
    from app.models.org import Company
    s = _db()
    try:
        co = Company(id=_uuid.uuid4(), name="R68W begona",
                     code="r68w" + _uuid.uuid4().hex[:6], currency="UZS")
        s.add(co)
        s.flush()
        unit = s.query(Unit).first()
        p = Product(id=_uuid.uuid4(), company_id=co.id, name="R68W begona mahsulot",
                    article_code="R68W-" + _uuid.uuid4().hex[:8], sku=_uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=1, base_sell_price=2, tax_rate=0)
        s.add(p)
        s.commit()
        begona_pid = str(p.id)
    finally:
        s.close()

    r = client.get(f"{API}/inventory/writeoff/status", headers=admin_headers,
                   params={"client_uuid": str(_uuid.uuid4()), "product_id": begona_pid})

    assert r.status_code == 400, r.text
    assert "recorded" not in r.text, r.text
