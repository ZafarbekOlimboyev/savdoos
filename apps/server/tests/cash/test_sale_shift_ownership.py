# -*- coding: utf-8 -*-
"""P9/3A — SOTUV LEDGER LEGINING SMENA EGALIGI va YOPILISH POYGASI.

ILDIZ SABAB
===========
`create_sale` naqd legini O'ZI yozadi (`services/sales.py`: `db.flush()` -> `on_cash_sale`).
`retrofit.on_cash_sale` esa smenani `_open_cash_shift_id` bilan — ya'ni HOZIR OCHIQ smenani
olardi, SOTUVNING O'Z smenasini emas. Oqibatlari:

  · offline chek smena yopilgandan keyin sinxronlanса (yoki savdo yopilish bilan ustma-ust
    tushsa) va o'sha kassada YANGI smena ochiq bo'lsa -> naqd BEGONA smenaga yozilardi
    (A soxta kamomad, B soxta ortiqcha);
  · ochiq smena bo'lmasa -> leg OFF_SHIFT bo'lib, pul umuman smenasiz qolardi.

`cle_uq_business (tenant, source_type, source_id, leg_index)` bu xatoni TO'SMAYDI: kalit
bitta va leg BIR MARTA yoziladi — noto'g'ri joyga. `trg_cle_immutable` esa uni ABADIY
muzlatadi (UPDATE/DELETE taqiq).

TUZATISH (P9/3A)
================
1. `sales.py` smena qatorini `FOR NO KEY UPDATE` bilan QULFLAYDI va holatini qulf ostida
   QAYTA O'QIYDI — gardlar va ledger bitta, barqaror haqiqatni ko'radi.
2. `on_cash_sale(shift_id=...)` — leg SOTUVNING o'z smenasiga bog'lanadi
   (`cash.shifts.id == legacy shifts.id`, `on_shift_open` shunday yaratadi).
3. Case C (yopilgan smenaga kech kelgan naqd) RATIFIKATSIYA QILINGAN holida QOLADI:
   leg `LATE_SYNC` bo'lib O'Z smenasiga yoziladi va `LATE_SYNC_UNACK` bilan belgilanadi.
   Uni rad etish ko'rib chiqilgan va RAD ETILGAN: `test_posting_service::test_41` LATE_SYNC
   legi yopilgan yarashtirish snapshotini o'zgartira olmasligini isbotlaydi, ya'ni xavf
   ledger darajasida allaqachon yopilgan; rad etish esa pulni YOZILMAGAN qilardi.
   P9/3A ning hissasi — bu shoxga endi FAQAT sotuvning o'z smenasi bilan kelinadi.

⚠️  NEGA POSTGRES. `dual_write_enabled()` SQLite'da DOIM False (cash sxemasi yo'q), ya'ni
    bu xulqni SQLite'da sinash MUMKIN EMAS. Har tasdiq HAQIQIY QATORLARNI o'qiydi.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models.cash import CashLedgerEntry, CashShift
from app.models.catalog import Product, Unit
from app.models.enums import ShiftStatus
from app.models.inventory import Inventory
from app.models.sales import Sale
from app.models.shifts import Shift
from app.schemas.sales import SaleCreate
from app.services.cash.errors import CashPostingError
from app.services.sales import create_sale

from tests.cash._factory import make_account

NOW = datetime.now(timezone.utc)


def _session(env) -> Session:
    """⚠️  ILOVA BILAN AYNI sozlama — `autoflush=False`."""
    return sessionmaker(bind=env.engine, autoflush=False,
                        expire_on_commit=False, class_=Session)()


@pytest.fixture()
def env(cashenv):
    """Kompaniya + O'Z KASSIRI + TILL + kuzatuvsiz mahsulot + qoldiq.

    ⚠️  HAR TESTGA ALOHIDA KASSIR. `cashenv` SESSIYA doirasida va ledger APPEND-ONLY
        (`trg_cle_immutable` DELETE'ni taqiqlaydi), ya'ni testlar orasida holatni
        tozalab bo'lmaydi. Bitta kassirni bo'lishsa, avvalgi testlarning OCHIQ
        smenalari to'planib qolardi va `create_sale` ning `.first()` i
        NODETERMINISTIK smenani tanlardi (bu test DB'sida `ux_shifts_cashier_open`
        indeksi yo'q). Kassirni ajratish izolyatsiyani TABIIY qiladi: barcha
        izlashlar `cashier_id` bo'yicha filtrlanadi."""
    from app.models.auth import Employee
    s = _session(cashenv)
    try:
        base = s.get(Employee, cashenv.employee_id)
        emp = Employee(id=uuid.uuid4(), company_id=cashenv.company_id,
                       full_name="3A kassir " + uuid.uuid4().hex[:6], role_id=base.role_id)
        s.add(emp)
        s.flush()
        emp_id = emp.id
        till = make_account(s, cashenv, "TILL")
        unit = s.query(Unit).first()
        if unit is None:
            unit = Unit(id=uuid.uuid4(), code="dona", name="dona")
            s.add(unit)
            s.flush()
        p = Product(id=uuid.uuid4(), company_id=cashenv.company_id,
                    name="3A sinov " + uuid.uuid4().hex[:6],
                    article_code="3A-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                    unit_id=unit.id, base_buy_price=50, base_sell_price=100, tax_rate=0)
        s.add(p)
        s.flush()
        s.add(Inventory(id=uuid.uuid4(), product_id=p.id, branch_id=cashenv.branch_id,
                        qty=Decimal("1000"), min_qty=0, updated_at=NOW))
        s.commit()
        return cashenv, till, p.id, emp_id
    finally:
        s.close()


# ══ YORDAMCHILAR — legacy va cash smenalari AYNI id bilan ═══════════════════

def _shift_pair(cashenv, till, cashier_id, *, status="open", opened_ago_h=2, closed_ago_h=None,
                cash_shift=True, cash_account=None):
    """Legacy `shifts` + (ixtiyoriy) `cash.shifts` — AYNI `id` bilan.

    `cash_shift=False` — HUJJATLANGAN legacy holat: bitta yashiqda ikkinchi kassir
    (`sh_one_open_per_account` bitta ochiq cash smenaga ruxsat beradi, legacy esa
    kassir-boshiga). Bunda `cash.shifts` qatori UMUMAN bo'lmaydi.
    """
    s = _session(cashenv)
    try:
        sid = uuid.uuid4()
        opened = NOW - timedelta(hours=opened_ago_h)
        closed = (NOW - timedelta(hours=closed_ago_h)) if closed_ago_h is not None else None
        s.add(Shift(id=sid, branch_id=cashenv.branch_id,
                    cashier_id=cashier_id,
                    opened_at=opened, closed_at=closed, opening_cash=Decimal("0"),
                    status=ShiftStatus.closed if closed is not None else ShiftStatus.open,
                    till_id=till.id))
        if cash_shift:
            acc = cash_account or till
            s.add(CashShift(id=sid, tenant_id=cashenv.company_id, cash_account_id=acc.id,
                            branch_id=acc.branch_id, account_type="TILL",
                            status="CLOSED" if closed is not None else "OPEN",
                            opened_at=opened, closed_at=closed,
                            opened_by=cashenv.employee_id, version=1))
        s.commit()
        return sid
    finally:
        s.close()


def _other_emp(cashenv):
    """Qo'shimcha kassir — «bitta yashiq, ikki kassir» holatini modellash uchun."""
    from app.models.auth import Employee
    s = _session(cashenv)
    try:
        base = s.get(Employee, cashenv.employee_id)
        e = Employee(id=uuid.uuid4(), company_id=cashenv.company_id,
                     full_name="3A boshqa " + uuid.uuid4().hex[:6], role_id=base.role_id)
        s.add(e)
        s.commit()
        return e.id
    finally:
        s.close()


def _sell(cashenv, pid, emp_id, *, cu=None, qty=1, price=100, honor=False, at=None):
    """HAQIQIY `create_sale` — `/sync/push` (honor=True) yoki onlayn (honor=False) yo'li."""
    s = _session(cashenv)
    try:
        from app.models.auth import Employee
        body = {"items": [{"product_id": str(pid), "qty": qty, "unit_price": price}],
                "payment_method": "cash", "given_amount": qty * price,
                "client_uuid": cu or uuid.uuid4()}
        sale = create_sale(s, s.get(Employee, emp_id), SaleCreate(**body),
                           at=at, honor_price_snapshot=honor)
        s.commit()
        return sale.id
    finally:
        s.close()


def _legs(cashenv, sale_id):
    s = _session(cashenv)
    try:
        return s.query(CashLedgerEntry).filter(
            CashLedgerEntry.tenant_id == cashenv.company_id,
            CashLedgerEntry.source_type == "SALE",
            CashLedgerEntry.source_id == sale_id).all()
    finally:
        s.close()


def _legs_of_shift(cashenv, shift_id):
    s = _session(cashenv)
    try:
        return s.query(CashLedgerEntry).filter(
            CashLedgerEntry.tenant_id == cashenv.company_id,
            CashLedgerEntry.shift_id == shift_id).all()
    finally:
        s.close()


def _exceptions(cashenv, entry_id):
    s = _session(cashenv)
    try:
        return [r[0] for r in s.execute(text(
            "SELECT kind FROM cash.cash_ledger_exceptions WHERE entry_id = :e"),
            {"e": str(entry_id)}).all()]
    finally:
        s.close()


def _sales_by_cu(cashenv, cu):
    s = _session(cashenv)
    try:
        return s.query(Sale).filter(Sale.company_id == cashenv.company_id,
                                    Sale.client_uuid == cu).all()
    finally:
        s.close()


def _stock(cashenv, pid):
    s = _session(cashenv)
    try:
        return Decimal(str(s.query(Inventory).filter(
            Inventory.product_id == pid, Inventory.branch_id == cashenv.branch_id).one().qty))
    finally:
        s.close()


def _t0(cashenv, *, hours_ago=1):
    """Cutover (T0) ni O'TMISHGA qo'yadi — post-T0 majburlash FAOL bo'ladi."""
    from app.models.settings import Setting
    s = _session(cashenv)
    try:
        row = (s.query(Setting).filter(Setting.company_id == cashenv.company_id,
                                       Setting.key == "cash",
                                       Setting.branch_id.is_(None)).first())
        val = {"cutover_at": (NOW - timedelta(hours=hours_ago)).isoformat()}
        if row is None:
            s.add(Setting(company_id=cashenv.company_id, branch_id=None, key="cash", value=val))
        else:
            row.value = val
        s.commit()
    finally:
        s.close()


def _no_t0(cashenv):
    from app.models.settings import Setting
    s = _session(cashenv)
    try:
        row = (s.query(Setting).filter(Setting.company_id == cashenv.company_id,
                                       Setting.key == "cash",
                                       Setting.branch_id.is_(None)).first())
        if row is not None:
            s.delete(row)
            s.commit()
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _clean_cutover(cashenv):
    """Har test O'Z T0 holatini belgilaydi — sessiya-doirasidagi sozlama oqmasin."""
    _no_t0(cashenv)
    yield
    _no_t0(cashenv)


# ══ 1. TO'G'RI EGALIK — leg SOTUV smenasiga tushadi ════════════════════════

def test_1_leg_SOTUV_smenasiga_tushadi(env):
    """Asosiy ijobiy holat: ochiq smena A -> leg AYNAN A da, ON_SHIFT."""
    cashenv, till, pid, emp_id = env
    a = _shift_pair(cashenv, till, emp_id, status="open")
    sale_id = _sell(cashenv, pid, emp_id)
    legs = _legs(cashenv, sale_id)
    assert len(legs) == 1, f"{len(legs)} leg (kutilgan 1)"
    assert str(legs[0].shift_id) == str(a), "leg SOTUV smenasiga bog'lanmagan"
    assert legs[0].posting_kind == "ON_SHIFT", legs[0].posting_kind
    assert legs[0].cash_account_id == till.id


def test_2_sale_shift_id_va_leg_shift_id_AYNI(env):
    """Ikki yozuv bir-biriga ZID bo'lmasin: `Sale.shift_id` == `leg.shift_id`."""
    cashenv, till, pid, emp_id = env
    _shift_pair(cashenv, till, emp_id, status="open")
    sale_id = _sell(cashenv, pid, emp_id)
    s = _session(cashenv)
    try:
        sale = s.get(Sale, sale_id)
        legs = _legs(cashenv, sale_id)
        assert len(legs) == 1
        assert str(sale.shift_id) == str(legs[0].shift_id), (sale.shift_id, legs[0].shift_id)
    finally:
        s.close()


# ══ 2. ASOSIY REGRESSIYA — BEGONA smenaga yozilmaydi ══════════════════════

def test_3_kech_chek_OZ_smenasiga_tushadi_BEGONASIGA_emas(env):
    """P9/3A NING MAG'ZI.

    A smenasi YOPILGAN, AYNI kassada B smenasi OCHIQ. A oynasidagi offline chek keladi.

    ILGARI: `_open_cash_shift_id` -> B -> naqd BEGONA (ochiq) smenaga yozilardi
            (A soxta kamomad, B soxta ortiqcha) va `trg_cle_immutable` uni abadiy
            muzlatardi. `cle_uq_business` bunga TO'SQINLIK QILMAYDI: kalit bitta va
            leg bir marta yoziladi — noto'g'ri joyga.
    ENDI:   leg SOTUVNING O'Z smenasiga (A) `LATE_SYNC` bo'lib tushadi va
            `LATE_SYNC_UNACK` istisnosi bilan belgilanadi. B — TEGILMAYDI."""
    cashenv, till, pid, emp_id = env
    a = _shift_pair(cashenv, till, emp_id, opened_ago_h=6, closed_ago_h=4)   # YOPILGAN
    b = _shift_pair(cashenv, till, emp_id, status="open", opened_ago_h=1)    # OCHIQ (ayni kassa)
    sale_id = _sell(cashenv, pid, emp_id, honor=True, at=NOW - timedelta(hours=5))

    legs = _legs(cashenv, sale_id)
    assert len(legs) == 1, f"{len(legs)} leg (kutilgan 1)"
    assert str(legs[0].shift_id) == str(a), "leg SOTUVNING O'Z smenasiga tushmadi"
    assert legs[0].posting_kind == "LATE_SYNC", legs[0].posting_kind
    assert "LATE_SYNC_UNACK" in _exceptions(cashenv, legs[0].id), "anomaliya belgilanmagan"
    # ENG MUHIMI: begona ochiq smena TEGILMAGAN — ilgari aynan shu buzilardi.
    assert _legs_of_shift(cashenv, b) == [], "leg BEGONA (ochiq) smenaga yozildi"


def test_4_LATE_SYNC_FAQAT_oz_smenasida_paydo_boladi(env):
    """Ruxsatsiz/tasodifiy LATE_SYNC bo'lmasin: bazadagi HAR LATE_SYNC legi AYNAN
    o'z sotuvining smenasiga tegishli bo'lishi shart."""
    cashenv, till, pid, emp_id = env
    a = _shift_pair(cashenv, till, emp_id, opened_ago_h=6, closed_ago_h=4)
    b = _shift_pair(cashenv, till, emp_id, status="open", opened_ago_h=1)
    sale_id = _sell(cashenv, pid, emp_id, honor=True, at=NOW - timedelta(hours=5))
    s = _session(cashenv)
    try:
        rows = s.execute(text(
            "SELECT source_id, shift_id FROM cash.cash_ledger_entries "
            "WHERE tenant_id = :t AND posting_kind = 'LATE_SYNC'"),
            {"t": str(cashenv.company_id)}).all()
    finally:
        s.close()
    mine = [r for r in rows if str(r[0]) == str(sale_id)]
    assert len(mine) == 1, f"{len(mine)} ta LATE_SYNC legi (kutilgan 1)"
    assert str(mine[0][1]) == str(a)
    assert all(str(r[1]) != str(b) for r in rows), "B smenasida LATE_SYNC legi paydo bo'ldi"


def test_4b_LATE_SYNC_legi_KUTILGAN_NAQDNI_oshirmaydi(env):
    """MOLIYAVIY INVARIANT: kech kelgan leg YOPILGAN smenaning kutilgan naqdini
    O'ZGARTIRMAYDI (`shift_movement_total` faqat `ON_SHIFT` ni sanaydi). Ya'ni yopilgan
    hisob-kitob JIMGINA qayta yozilmaydi — u faqat istisno bilan BELGILANADI."""
    from app.services.cash import repositories as _repo
    cashenv, till, pid, emp_id = env
    a = _shift_pair(cashenv, till, emp_id, opened_ago_h=6, closed_ago_h=4)
    _shift_pair(cashenv, till, emp_id, status="open", opened_ago_h=1)
    s = _session(cashenv)
    try:
        before = _repo.shift_movement_total(s, cashenv.company_id, a)
    finally:
        s.close()
    _sell(cashenv, pid, emp_id, honor=True, at=NOW - timedelta(hours=5))
    s = _session(cashenv)
    try:
        after = _repo.shift_movement_total(s, cashenv.company_id, a)
    finally:
        s.close()
    assert before == after, (before, after)


# ══ 3. PRE-T0 va POST-T0 farqi ════════════════════════════════════════════

def test_5_PRE_T0_kech_chek_QABUL_va_OZ_smenasida(env):
    """T0 YO'Q (legacy/shadow): `reject_closed_shift_replay` ishlamaydi, chek QABUL
    qilinadi — LEKIN o'z smenasida va `LATE_SYNC_UNACK` bilan belgilangan holda.
    Pul YOZILADI (yo'qolmaydi) va ANOMALIYA sifatida ko'rinadi."""
    cashenv, till, pid, emp_id = env
    _no_t0(cashenv)
    a = _shift_pair(cashenv, till, emp_id, opened_ago_h=6, closed_ago_h=4)
    sale_id = _sell(cashenv, pid, emp_id, honor=True, at=NOW - timedelta(hours=5))
    legs = _legs(cashenv, sale_id)
    assert len(legs) == 1
    assert str(legs[0].shift_id) == str(a)
    assert legs[0].posting_kind == "LATE_SYNC"
    assert "LATE_SYNC_UNACK" in _exceptions(cashenv, legs[0].id)


def test_6_POST_T0_da_cutover_gardi_BIRINCHI_ishlaydi(env):
    """T0 o'tgan: `CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY` posting qatlamiga
    YETIB BORMAYDI — garddan oldin rad etiladi. Ikki qatlam bir-birini almashtirmaydi."""
    from fastapi import HTTPException
    cashenv, till, pid, emp_id = env
    _t0(cashenv)
    _shift_pair(cashenv, till, emp_id, opened_ago_h=6, closed_ago_h=4)
    with pytest.raises(HTTPException) as ex:
        _sell(cashenv, pid, emp_id, honor=True, at=NOW - timedelta(hours=5))
    detail = str(getattr(ex.value, "detail", ""))
    assert "CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY" in detail, detail
    assert ex.value.status_code == 400


# ══ 4. HUJJATLANGAN LEGACY HOLAT — cash.shifts qatori YO'Q ════════════════

def test_7_cash_smenasi_YOQ_bolsa_OFF_SHIFT_anomaliyasi(env):
    """Bitta yashiqdagi IKKINCHI kassir: legacy smena bor, `cash.shifts` YO'Q.

    Savdo O'TISHI kerak (mavjud xulq saqlanadi), lekin leg BEGONA smenaga
    yozilmasin — OFF_SHIFT + `UNRESOLVED_OFF_SHIFT` bo'lib ANOMALIYA ko'rinadi."""
    cashenv, till, pid, emp_id = env
    # BIRINCHI kassir yashiqning YAGONA ochiq cash smenasini egallaydi
    # (`sh_one_open_per_account`).
    other_emp = _other_emp(cashenv)
    other = _shift_pair(cashenv, till, other_emp, status="open", opened_ago_h=3)
    # IKKINCHI kassir (biz): legacy smena bor, `cash.shifts` qatori YO'Q — aynan
    # `on_shift_open` ning skip holati.
    mine = _shift_pair(cashenv, till, emp_id, status="open", opened_ago_h=1, cash_shift=False)
    s = _session(cashenv)
    try:
        assert s.get(Shift, mine).cashier_id == emp_id
    finally:
        s.close()
    sale_id = _sell(cashenv, pid, emp_id)
    legs = _legs(cashenv, sale_id)
    assert len(legs) == 1
    assert legs[0].shift_id is None, "cash smenasi yo'q — leg smenaga bog'lanmasligi kerak"
    assert legs[0].posting_kind == "OFF_SHIFT", legs[0].posting_kind
    assert "UNRESOLVED_OFF_SHIFT" in _exceptions(cashenv, legs[0].id)
    assert _legs_of_shift(cashenv, other) == [], "leg BOSHQA kassirning smenasiga tushdi"


# ══ 5. TAKROR YETKAZISH — AYNAN BITTA leg ═════════════════════════════════

def test_8_takror_client_uuid_BITTA_savdo_BITTA_leg(env):
    """Qayta ulanish sikli bir chekni bir necha marta yuboradi."""
    cashenv, till, pid, emp_id = env
    a = _shift_pair(cashenv, till, emp_id, status="open")
    cu = uuid.uuid4()
    id1 = _sell(cashenv, pid, emp_id, cu=cu)
    id2 = _sell(cashenv, pid, emp_id, cu=cu)
    assert id1 == id2, "takror push YANGI savdo yaratdi"
    assert len(_sales_by_cu(cashenv, cu)) == 1
    legs = _legs(cashenv, id1)
    assert len(legs) == 1, f"{len(legs)} leg — takror yetkazish ikkinchi leg yozdi"
    assert str(legs[0].shift_id) == str(a)


# ══ 6. XAVFSIZ ATRIBUSIYA ANIQLANMASA — FAIL CLOSED ══════════════════════

def test_9_smena_BOSHQA_kassaga_tegishli_bolsa_RAD(env):
    """`Sale.till_id` va smenaning kassasi ZID bo'lsa — taxmin qilinmaydi, rad etiladi."""
    cashenv, till, pid, emp_id = env
    _s = _session(cashenv)
    try:
        other_till = make_account(_s, cashenv, "TILL")
    finally:
        _s.close()
    # Legacy smena `till` ni ko'rsatadi, cash smena esa BOSHQA kassada.
    _shift_pair(cashenv, till, emp_id, status="open", cash_account=other_till)
    stock_before = _stock(cashenv, pid)
    cu = uuid.uuid4()
    with pytest.raises(CashPostingError) as ex:
        _sell(cashenv, pid, emp_id, cu=cu)
    assert ex.value.code == "SHIFT_NOT_BELONG_TO_ACCOUNT", ex.value.code
    assert _sales_by_cu(cashenv, cu) == [], "xavfsiz atribusiya yo'q, lekin savdo yozildi"
    assert _stock(cashenv, pid) == stock_before


# ══ 7. YOPILISH POYGASI — QULFLAR TO'QNASHADI ════════════════════════════

def test_10_savdo_va_yopish_AYNI_smena_qatorida_TOQNASHADI(env):
    """QULF SHARTNOMASI ISBOTI.

    `create_sale` smena qatorini `FOR NO KEY UPDATE` bilan oladi, `close_shift` esa
    `FOR UPDATE`. Ikkovi TO'QNASHISHI shart — aks holda savdo yopilayotgan smenani
    'ochiq' deb ko'rib gardlardan o'tib ketardi.

    `lock_timeout` bilan determinik: qulf bo'sh bo'lsa ikkinchi sessiya DARHOL o'tardi."""
    cashenv, till, pid, emp_id = env
    sid = _shift_pair(cashenv, till, emp_id, status="open")
    s1 = _session(cashenv)
    s2 = _session(cashenv)
    try:
        # 1-sessiya: savdo yo'li oladigan AYNI qulf.
        got = s1.execute(text("SELECT id FROM shifts WHERE id = :i FOR NO KEY UPDATE"),
                         {"i": str(sid)}).scalar()
        assert got is not None
        # 2-sessiya: `close_shift` oladigan AYNI qulf — bloklanishi SHART.
        s2.execute(text("SET LOCAL lock_timeout = '600ms'"))
        with pytest.raises(Exception) as ex:
            s2.execute(text("SELECT id FROM shifts WHERE id = :i FOR UPDATE"), {"i": str(sid)})
        assert "lock" in str(ex.value).lower() or "timeout" in str(ex.value).lower(), str(ex.value)
    finally:
        s1.rollback(); s1.close()
        s2.rollback(); s2.close()


def test_11_ayni_smenaga_ikki_savdo_BLOKLANMAYDI_ketma_ket(env):
    """Qulf savdolarni SERIALIZATSIYA qiladi, lekin YO'QOTMAYDI: ketma-ket ikki savdo
    ikki leg beradi va ikkovi AYNI smenada."""
    cashenv, till, pid, emp_id = env
    a = _shift_pair(cashenv, till, emp_id, status="open")
    id1 = _sell(cashenv, pid, emp_id)
    id2 = _sell(cashenv, pid, emp_id)
    assert id1 != id2
    for sid_ in (id1, id2):
        legs = _legs(cashenv, sid_)
        assert len(legs) == 1
        assert str(legs[0].shift_id) == str(a)


# ══ 8. TENANT va KASSIR IZOLYATSIYASI ════════════════════════════════════

def test_12_boshqa_kassirning_ochiq_smenasi_ISHLATILMAYDI(env):
    """Onlayn savdo FAQAT o'z kassirining ochiq smenasini oladi (`cashier_id` filtri).
    Boshqa kassirning smenasi ham, uning legi ham tegilmasin."""
    cashenv, till, pid, emp_id = env
    other_id = _other_emp(cashenv)
    # Begona kassirning OCHIQ smenasi — yashiqning yagona cash smenasini ham u egallaydi.
    foreign = _shift_pair(cashenv, till, other_id, status="open", opened_ago_h=3)
    mine = _shift_pair(cashenv, till, emp_id, status="open", opened_ago_h=1, cash_shift=False)
    sale_id = _sell(cashenv, pid, emp_id)
    s = _session(cashenv)
    try:
        assert str(s.get(Sale, sale_id).shift_id) == str(mine), "savdo begona smenaga bog'landi"
    finally:
        s.close()
    assert _legs_of_shift(cashenv, foreign) == [], "leg BEGONA kassirning smenasiga tushdi"


def test_13_leg_tenant_va_kassa_bilan_BOGLANGAN(env):
    """Ledger legi tenant + kassa + filialni AYNAN olib yuradi (DDL kompozit FK'lari)."""
    cashenv, till, pid, emp_id = env
    _shift_pair(cashenv, till, emp_id, status="open")
    sale_id = _sell(cashenv, pid, emp_id)
    leg = _legs(cashenv, sale_id)[0]
    assert leg.tenant_id == cashenv.company_id
    assert leg.cash_account_id == till.id
    assert leg.branch_id == till.branch_id
    assert leg.account_type == "TILL"


# ══ 9. ATRIBUSIYA AUDITI (faqat o'qish) ══════════════════════════════════

def test_14_audit_notogri_atribusiyani_TOPADI(env):
    """Detektor: yopilgan smenadagi savdoning legi BOSHQA smenada bo'lsa — `leg_other_shift`.

    Tarixiy (P9/3A dan OLDIN yozilgan) nuqsonni modellash uchun leg QO'LDA boshqa
    smenaga yoziladi — aynan eski kod shunday qilardi."""
    cashenv, till, pid, emp_id = env
    a = _shift_pair(cashenv, till, emp_id, status="open")
    sale_id = _sell(cashenv, pid, emp_id)
    b = _shift_pair(cashenv, till, emp_id, opened_ago_h=6, closed_ago_h=5)   # yopilgan smena
    s = _session(cashenv)
    try:
        # Savdoni YOPILGAN b smenasiga ko'chiramiz (legi esa a da qoladi) — "leg_other_shift".
        s.query(Sale).filter(Sale.id == sale_id).update({"shift_id": b})
        # b ni ham yopilgan deb muzlatamiz (expected_cash) — auditning legacy tomoni uchun.
        s.query(Shift).filter(Shift.id == b).update({"expected_cash": Decimal("0")})
        s.commit()
    finally:
        s.close()
    from app.api.v1.shifts import shifts_attribution_audit
    from app.models.auth import Employee
    s = _session(cashenv)
    try:
        out = shifts_attribution_audit(limit=50, emp=s.get(Employee, cashenv.employee_id), db=s)
    finally:
        s.close()
    row = next((r for r in out["shifts"] if r["shift_id"] == str(b)), None)
    assert row is not None, "yopilgan smena auditda yo'q"
    assert row["leg_other_shift"] == 1, row
    assert row["clean"] is False, row
    assert out["ledger_checked"] is True
    assert str(a) != str(b)


def test_15_audit_HECH_NARSA_yozmaydi(env):
    """Detektor FAQAT O'QIYDI: muzlatilgan ustunlar tegilmasin."""
    cashenv, till, pid, emp_id = env
    b = _shift_pair(cashenv, till, emp_id, opened_ago_h=6, closed_ago_h=5)
    s = _session(cashenv)
    try:
        s.query(Shift).filter(Shift.id == b).update(
            {"expected_cash": Decimal("777.00"), "counted_cash": Decimal("700.00"),
             "difference": Decimal("-77.00")})
        s.commit()
        before = s.execute(text("SELECT expected_cash, counted_cash, difference, closed_at "
                                "FROM shifts WHERE id = :i"), {"i": str(b)}).one()
    finally:
        s.close()
    from app.api.v1.shifts import shifts_attribution_audit
    from app.models.auth import Employee
    s = _session(cashenv)
    try:
        shifts_attribution_audit(limit=50, emp=s.get(Employee, cashenv.employee_id), db=s)
    finally:
        s.close()
    s = _session(cashenv)
    try:
        after = s.execute(text("SELECT expected_cash, counted_cash, difference, closed_at "
                               "FROM shifts WHERE id = :i"), {"i": str(b)}).one()
    finally:
        s.close()
    assert tuple(before) == tuple(after), (before, after)
