# -*- coding: utf-8 -*-
"""H3b — UCH YOZUVCHINING NAQD LEDGER OYOQLARI (FAQAT Postgres).

NEGA ALOHIDA, POSTGRES'DA
=========================
H3b uchta ledger hook'iga tarixiy paytni uzatdi:
  · `retrofit.on_cash_op`         (kassa kirimi / xarajati)   -> `_post` kanali
  · `retrofit.on_cash_collection` (inkassa TILL -> SAFE)      -> `TransferCommand` kanali
  · `retrofit.on_debt_payment`    (mijoz qarz to'lovi)        -> `_post` kanali

⚠️  BU YO'L SQLite'DA UMUMAN BAJARILMAYDI: `retrofit.dual_write_enabled`
    `cash_enabled(db)` ni talab qiladi va u postgresql bo'lmagan dialektda
    `False`. Ya'ni `tests/test_h3b_historical_writers.py` bu hook'larga
    uzatilgan `at` ni KO'RMAYDI — u yerda ular GUARDED NO-OP.

⚠️  INKASSA BOSHQA KANAL. `on_cash_collection` `_post` emas, `TransferCommand`
    -> `post_transfer` orqali ketadi. `TransferCommand.device_occurred_at`
    ALLAQACHON mavjud (`commands.py`) va u IKKI joyga boradi: `CashTransfer`
    sarlavhasining `occurred_at` iga VA `_resolve_transfer_leg` ning HAR IKKI
    oyoq tasnifiga. Bitta oyoqni tekshirish YARMINI o'tkazib yuborardi.

⚠️  TO'G'RIDAN ORM BILAN LEDGER YOZILMAYDI — faqat kanonik yozuvchilar.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services import historical as H

TZ = "Asia/Tashkent"
DEPTH = 170
PLAN = "h3b-cash-pg"


def _aw(dt):
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@pytest.fixture()
def demo(db, cashenv):
    """DEMO tenant (kod `demo-...`, T0 YO'Q) + filial + kassir + TILL + SAFE.

    `cashenv` umumiy kompaniyasi ISHLATILMAYDI: H1 darvozasi `test`/`demo`
    kodli do'konni TALAB qiladi (umumiy fixture kodi `cashtst`).
    """
    from app.models.auth import Employee, Role
    from app.models.cash import CashAccount
    from app.models.catalog import Product, Unit
    from app.models.customers import Customer
    from app.models.enums import EmployeeStatus
    from app.models.inventory import Inventory
    from app.models.org import Branch, Company
    from app.services.cash import till_identity as _ti

    now = datetime.now(timezone.utc)
    day = (now - timedelta(days=DEPTH)).replace(hour=0, minute=0, second=0, microsecond=0)
    comp = Company(id=uuid.uuid4(), name="H3b naqd demo",
                   code=f"demo-h3bpg-{uuid.uuid4().hex[:6]}", currency="KGS")
    db.add(comp)
    db.flush()
    br = Branch(id=uuid.uuid4(), company_id=comp.id, name="F01", code="F01",
                timezone=TZ, is_active=True, created_at=now - timedelta(days=400))
    db.add(br)
    db.flush()
    role = db.query(Role).first()
    if role is None:
        role = Role(id=uuid.uuid4(), code="ega", name="Ega")
        db.add(role)
        db.flush()
    emp = Employee(id=uuid.uuid4(), company_id=comp.id, role_id=role.id,
                   full_name="H3b kassir", phone=f"+9983{uuid.uuid4().int % 10**7:07d}",
                   status=EmployeeStatus.active, sec_epoch=0)
    db.add(emp)
    #  ⚠️  HISOBLAR TARIXIY KUNDAN OLDIN yaratilgan bo'lsin: attestatsiya
    #      `counted_at=account.created_at` ni ishlatadi (`_factory.open_safe`),
    #      ya'ni seyf ochilishi ham tarixiy kunga qadar bo'ladi.
    acc_at = day - timedelta(days=1)
    till = CashAccount(id=uuid.uuid4(), tenant_id=comp.id, branch_id=br.id,
                       type="TILL", currency="KGS", status="ACTIVE",
                       label=_ti.till_label(f"TILL-{uuid.uuid4().hex[:4]}", None),
                       created_at=acc_at)
    safe = CashAccount(id=uuid.uuid4(), tenant_id=comp.id, branch_id=br.id,
                       type="SAFE", currency="KGS", status="ACTIVE",
                       label=_ti.safe_label(f"SAFE-{uuid.uuid4().hex[:4]}"),
                       created_at=acc_at)
    db.add_all([till, safe])
    cust = Customer(id=uuid.uuid4(), company_id=comp.id,
                    code="M" + uuid.uuid4().hex[:10], full_name="H3b qarzdor",
                    credit_balance=Decimal("50000"), credit_limit=Decimal("1000000"))
    db.add(cust)
    u = db.query(Unit).filter_by(code="dona").first()
    if u is None:
        u = Unit(id=uuid.uuid4(), code="dona", name="dona", allow_fraction=False)
        db.add(u)
        db.flush()
    prod = Product(id=uuid.uuid4(), company_id=comp.id, name="H3b dona",
                   article_code="H3BPG-" + uuid.uuid4().hex[:8], sku=uuid.uuid4().hex[:8],
                   unit_id=u.id, base_buy_price=500, base_sell_price=1000, tax_rate=0)
    db.add(prod)
    db.flush()
    db.add(Inventory(product_id=prod.id, branch_id=br.id, qty=Decimal("20"),
                     min_qty=0, updated_at=now))
    db.commit()

    #  SEYFNI ISHGA TAYYOR qilish — HAQIQIY xizmat orqali (qoida qayta yozilmaydi).
    #  ⚠️  `emp=` UZATILMAYDI: attestatsiya MENEJER+ rolini talab qiladi
    #      (`safe_opening._is_manager_plus`), bizning kassir esa unga mos emas —
    #      o'lchangan: `UNAUTHORIZED_OPERATION`. `_factory.open_safe` standart
    #      holda shu do'kon uchun menejer yaratadi/qayta ishlatadi.
    #  ⚠️  `counted_at` = `account.created_at` (factory shunday), ya'ni hisob
    #      TARIXIY kundan oldin yaratilgani uchun ochilish ham tarixiy bo'ladi.
    from tests.cash._factory import open_safe
    open_safe(db, cashenv, safe, company_id=comp.id)
    db.commit()
    return {"comp": comp, "emp": emp, "br": br, "till": till, "safe": safe,
            "cust": cust, "prod": prod, "day": day}


class _Open:
    opening_cash = 200000.0
    terminal_id = None
    till_id = None


def _legs(db, tenant_id):
    from app.models.cash import CashLedgerEntry
    return (db.query(CashLedgerEntry)
            .filter(CashLedgerEntry.tenant_id == tenant_id)
            .order_by(CashLedgerEntry.device_occurred_at).all())


def _tarixiy_kun(db, demo, *, plan=PLAN):
    """Bitta tarixiy kun, bitta smena oynasi:
    smena 08:00 -> kirim 09:00 -> xarajat 10:00 -> inkassa 11:00
    -> qarz to'lovi 12:00 -> hisobdan chiqarish 13:00 (naqd legi BO'LMASLIGI shart).
    """
    from app.api.v1.cashops import CashOpIn, _cash_op_once
    from app.api.v1.customers import CreditPayment, _pay_credit_once
    from app.api.v1.inventory import WriteoffIn, _writeoff_once
    from app.services.shifts import open_shift_svc

    comp, emp, day = demo["comp"], demo["emp"], demo["day"]
    T = {"shift": day + timedelta(hours=8), "payin": day + timedelta(hours=9),
         "expense": day + timedelta(hours=10), "collection": day + timedelta(hours=11),
         "debt": day + timedelta(hours=12), "writeoff": day + timedelta(hours=13)}
    _Open.till_id = demo["till"].id

    with H.enter(db, comp, plan_id=plan, instant=T["shift"]) as ctx:
        sh = open_shift_svc(_Open(), emp, db, at=T["shift"],
                            client_uuid=ctx.key("shift", "open"))
    out = {"T": T, "shift_id": uuid.UUID(sh["id"])}

    with H.enter(db, comp, plan_id=plan, instant=T["payin"]) as ctx:
        _cash_op_once(CashOpIn(type="payin", amount=5000, reason="H3b kirim",
                               client_uuid=ctx.key("payin")), emp, db, at=T["payin"])
    with H.enter(db, comp, plan_id=plan, instant=T["expense"]) as ctx:
        _cash_op_once(CashOpIn(type="expense", amount=3000, reason="H3b xarajat",
                               client_uuid=ctx.key("expense")), emp, db, at=T["expense"])
    with H.enter(db, comp, plan_id=plan, instant=T["collection"]) as ctx:
        _cash_op_once(CashOpIn(type="collection", amount=30000,
                               destination_safe_id=demo["safe"].id,
                               client_uuid=ctx.key("collection")),
                      emp, db, at=T["collection"])
    with H.enter(db, comp, plan_id=plan, instant=T["debt"]) as ctx:
        _pay_credit_once(demo["cust"].id,
                         CreditPayment(amount=20000, method="cash",
                                       client_uuid=ctx.key("debt")),
                         emp, db, at=T["debt"])
    with H.enter(db, comp, plan_id=plan, instant=T["writeoff"]) as ctx:
        _writeoff_once(WriteoffIn(product_id=demo["prod"].id, qty=2, reason="brak",
                                  branch_id=demo["br"].id, client_uuid=ctx.key("wo")),
                       emp, db, at=T["writeoff"])
    db.commit()
    return out


def test_naqd_oyoqlari_TARIXIY_paytni_oladi(db, demo):
    """Har legning `device_occurred_at` i AYNAN rejadagi payt bo'lishi SHART."""
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq (cash sxemasi yo'q) — naqd oyoqlari o'lchanmaydi")

    z = _tarixiy_kun(db, demo)
    legs = _legs(db, demo["comp"].id)
    assert legs, "naqd ledger legi UMUMAN yozilmadi — test o'z sahnasini tekshirmayapti"

    kutilgan = {"SHIFT_OPEN": z["T"]["shift"],
                "CASH_OP": None,          # pastda ALOHIDA (uch xil amal, bir manba turi)
                "CREDIT_PAYMENT": z["T"]["debt"]}
    korilgan: dict = {}
    for lg in legs:
        src = str(lg.source_type).split(".")[-1]
        korilgan.setdefault(src, []).append(lg)
    print("  yozilgan manba turlari:", {k: len(v) for k, v in korilgan.items()})

    #  Har legning payti REJADAGI uchta paytdan BIRIGA mos bo'lishi SHART va
    #  BIRORTASI bugungi bo'lmasligi kerak.
    ruxsat = set(z["T"].values())
    for lg in legs:
        src = str(lg.source_type).split(".")[-1]
        d_at = _aw(lg.device_occurred_at)
        mos = [t for t in ruxsat if abs((d_at - t).total_seconds()) < 2]
        assert mos, (f"`{src}` legining `device_occurred_at` i rejadagi HECH QAYSI "
                     f"paytga mos emas: {d_at} (reja: {sorted(str(t)[:16] for t in ruxsat)})")


def test_naqd_oyoqlari_ON_SHIFT_va_TARIXIY_smenada(db, demo):
    """TILL oyoqlari tarixiy smena OYNASIGA tushishi va unga biriktirilishi SHART."""
    from app.models.cash import CashPostingKind
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq")

    z = _tarixiy_kun(db, demo)
    legs = _legs(db, demo["comp"].id)
    off = [(str(lg.source_type), str(lg.posting_kind), str(lg.device_occurred_at))
           for lg in legs
           if str(lg.posting_kind).endswith("OFF_SHIFT")
           and str(lg.account_type).endswith("TILL")]
    assert not off, \
        (f"TILL legi OYNADAN TASHQARI: {off}. Ya'ni tarixiy payt uzatilmagan yoki "
         f"smena oynasi bilan mos kelmagan.")

    till_legs = [lg for lg in legs if str(lg.account_type).endswith("TILL")]
    assert till_legs, "TILL legi yo'q — sahna kutilganidek qurilmagan"
    for lg in till_legs:
        assert str(lg.posting_kind).endswith(CashPostingKind.ON_SHIFT.value), \
            f"TILL legi ON_SHIFT emas: {lg.posting_kind} ({lg.source_type})"
        assert lg.shift_id == z["shift_id"], \
            f"leg BOSHQA smenaga biriktirilgan: {lg.shift_id} != {z['shift_id']}"


def test_INKASSA_transfer_sarlavhasi_va_IKKI_oyoq_tarixiy(db, demo):
    """⚠️  INKASSA BOSHQA KANAL (`TransferCommand` -> `post_transfer`).

    `CashTransfer.occurred_at` VA ikki oyoqning ikkisi ham tarixiy bo'lishi
    SHART — bitta oyoqni tekshirish yarmini o'tkazib yuborardi.
    """
    from sqlalchemy import text

    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq")

    z = _tarixiy_kun(db, demo)
    t_coll = z["T"]["collection"]

    rows = db.execute(text(
        "SELECT id, occurred_at FROM cash.cash_transfers WHERE tenant_id = :t"),
        {"t": str(demo["comp"].id)}).all()
    assert rows, "`cash_transfers` sarlavhasi YOZILMADI — inkassa kanali ishlamagan"
    for tid, occ in rows:
        assert abs((_aw(occ) - t_coll).total_seconds()) < 2, \
            f"`cash_transfers.occurred_at` TARIXIY emas: {occ} != {t_coll}"

    #  IKKI OYOQ: bitta `transfer_group_id`, biri TILL OUT, biri SAFE IN.
    from app.models.cash import CashLedgerEntry
    tlegs = (db.query(CashLedgerEntry)
             .filter(CashLedgerEntry.tenant_id == demo["comp"].id,
                     CashLedgerEntry.transfer_group_id.isnot(None)).all())
    assert len(tlegs) == 2, f"inkassa IKKI oyoq yozishi SHART: {len(tlegs)}"
    guruh = {lg.transfer_group_id for lg in tlegs}
    assert len(guruh) == 1, f"oyoqlar BITTA transfer_group'da bo'lishi SHART: {guruh}"
    yonalish = {str(lg.direction).split(".")[-1] for lg in tlegs}
    assert yonalish == {"IN", "OUT"}, f"yo'nalishlar: {yonalish}"
    for lg in tlegs:
        assert abs((_aw(lg.device_occurred_at) - t_coll).total_seconds()) < 2, \
            (f"inkassa oyog'i ({lg.account_type}/{lg.direction}) TARIXIY emas: "
             f"{lg.device_occurred_at} != {t_coll}")


def test_QARZ_TOLOVI_legi_tarixiy(db, demo):
    """`on_debt_payment` legi rejadagi paytni olishi SHART."""
    from app.models.cash import CashLedgerEntry
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq")

    z = _tarixiy_kun(db, demo)
    #  ⚠️  MANBA TURI `CUSTOMER_PAYMENT` (`adapters.debt_payment` ->
    #      `CashSourceType.CUSTOMER_PAYMENT`), «CREDIT»/«DEBT» EMAS — birinchi
    #      variantim noto'g'ri filtr bilan bo'sh to'plam olgan. `category` esa
    #      `DEBT_IN`, lekin biz manba turi bo'yicha izlaymiz.
    legs = [lg for lg in _legs(db, demo["comp"].id)
            if "CUSTOMER_PAYMENT" in str(lg.source_type).upper()]
    assert legs, (f"qarz to'lovi legi YO'Q. Yozilganlar: "
                  f"{sorted({str(l.source_type) for l in _legs(db, demo['comp'].id)})}")
    for lg in legs:
        assert abs((_aw(lg.device_occurred_at) - z["T"]["debt"]).total_seconds()) < 2, \
            f"qarz to'lovi legi TARIXIY emas: {lg.device_occurred_at} != {z['T']['debt']}"


def test_HISOBDAN_CHIQARISH_naqd_legi_YOZMAYDI(db, demo):
    """⚠️  Hisobdan chiqarish NAQD PULGA TEGMAYDI — bu kontrakt.

    Tashlangan tovar zaxira yo'qotishi, kassa amali EMAS. Ledgerga leg yozish
    kassada bo'lmagan pul harakatini ko'rsatardi va smena yopilishini buzardi
    (`api/v1/inventory.py` docstring'i). Bu test shuni QADAYDI: H3b chiqarish
    yozuvchisiga `at` qo'shdi, lekin naqd leg QO'SHMADI.
    """
    from app.models.cash import CashLedgerEntry
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq")

    _tarixiy_kun(db, demo)
    legs = _legs(db, demo["comp"].id)
    yomon = [str(lg.source_type) for lg in legs
             if "WRITEOFF" in str(lg.source_type).upper()
             or "WRITE_OFF" in str(lg.source_type).upper()]
    assert not yomon, f"hisobdan chiqarish NAQD legi yozdi: {yomon}"
    #  Va chiqarish summasi (2 x 500 = 1000) hech bir legda bo'lmasligi kerak.
    assert not [lg for lg in legs
                if Decimal(str(lg.amount)) == Decimal("1000")
                and "PURCHASE" not in str(lg.source_type).upper()], \
        "chiqarish tannarxi naqd legga oqib ketgan"


def test_QABUL_vaqti_QALBAKILASHTIRILMAYDI(db, demo):
    """`server_received_at` / `recorded_at` ATAYLAB haqiqiy vaqt bo'lib qoladi.

    Ularni orqaga sanash replay'ni jonli amaldan ajratadigan YAGONA audit
    o'qini yo'q qilardi.
    """
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq")

    _tarixiy_kun(db, demo)
    hozir = datetime.now(timezone.utc)
    for lg in _legs(db, demo["comp"].id):
        assert (hozir - _aw(lg.server_received_at)).total_seconds() < 3600, \
            f"`server_received_at` ORQAGA sanalgan: {lg.server_received_at}"
        yosh = (_aw(lg.server_received_at) - _aw(lg.device_occurred_at)).total_seconds()
        assert yosh > 86400, \
            (f"leg biznes payti TARIXIY emas: device={lg.device_occurred_at} "
             f"received={lg.server_received_at} farq={yosh:.0f}s ({lg.source_type})")


def test_NORMAL_kassa_amali_HOZIRGI_vaqt_Postgresda(db, demo):
    """Normal yo'l (kontekst YO'Q) hamon hozirgi vaqt bilan yozadi — PG'da ham."""
    from app.api.v1.cashops import CashOpIn, cash_op
    from app.models.cash import CashLedgerEntry
    from app.services.cash import retrofit as _cr
    if not _cr.dual_write_enabled(db):
        pytest.skip("dual-write o'chiq")

    #  ⚠️  SMENA KANONIK SERVIS BILAN OCHILADI, xom ORM bilan EMAS. O'LCHANGAN:
    #      ORM bilan qurilgan legacy smenaning `cash.shifts` EGIZAGI yo'q, shu
    #      bois `on_cash_op` -> `_shift_ctx` legni o'sha smenaga biriktira
    #      olmaydi va `shift_id` bo'yicha filtr BO'SH chiqadi (birinchi
    #      variantim aynan shunday yiqildi — nuqson emas, sahna xatosi).
    from app.services.shifts import open_shift_svc

    class _OpenNow:
        opening_cash = 100000.0
        terminal_id = None
        till_id = demo["till"].id
    sh = open_shift_svc(_OpenNow(), demo["emp"], db)      # `at` YO'Q -> HOZIR
    db.commit()
    shift_id = uuid.UUID(sh["id"])
    #  MARSHRUT o'rovchisi, pozitsion — mavjud testlar bilan AYNI shakl.
    cash_op(CashOpIn(type="payin", amount=7000), demo["emp"], db)
    db.commit()

    legs = [lg for lg in _legs(db, demo["comp"].id) if lg.shift_id == shift_id]
    assert legs, "normal kassa amali leg yozmadi"
    for lg in legs:
        assert abs((_aw(lg.device_occurred_at) - datetime.now(timezone.utc))
                   .total_seconds()) < 900, \
            f"NORMAL amal HOZIRGI vaqt bilan yozilishi SHART: {lg.device_occurred_at}"
