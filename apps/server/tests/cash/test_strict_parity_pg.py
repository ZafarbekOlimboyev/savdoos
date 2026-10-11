# -*- coding: utf-8 -*-
"""QAT'IY FINALIZE KOMPARATORI — HAQIQIY LEGLAR (faqat PostgreSQL).

Naqd ledgeri ATAYLAB faqat Postgres'da bor (`retrofit.cash_enabled` boshqa
dialektda False), shu bois haqiqiy leg talab qiladigan holatlar SHU YERDA.
Sof komponent arifmetikasi va hukm funksiyasi: `tests/test_strict_parity.py`.

Ega bergan matritsa (holat raqamlari saqlangan):
 1  bo'sh till / opening 3000 -> leg 3000                     PASS
 2  keyingi smena / B_pre=3000 / opening 3000 -> leg 0         PASS
 3  keyingi smena / B_pre=0 / opening 3000 / leg YO'Q          FAIL
 4  B_pre=1000 / opening 3000 -> leg 2000                      PASS
 5  kutilgan 2000 / haqiqiy 3000                               FAIL
 6  kutilgan 0 / qo'shimcha OPENING                            FAIL
 7  nusxa / buzuq bog'langan OPENING                           FAIL
 9  sog'lom carry-over: 3 smena / 1 till                       PASS
10  mavjud ataylab-yo'q-leg (ikkinchi kassir) regressiyasi      FAIL
11  tartib noaniqligi (inversiya)                              UNDETERMINED
12  bog'lanmagan soxta OPENING source_id                       FAIL
14  REKONSTRUKSIYA to'liq-ochilish konvensiyasi                PASS
15  NORMAL delta-ochilish konvensiyasi                         PASS (1/4 bilan)

⚠️  3/5/6 holatlari MA'LUMOT BILAN qurilmaydi: `trg_cle_immutable` va
    `REVOKE UPDATE, DELETE` legni o'chirishni/o'zgartirishni TAQIQLAYDI, shu
    bois yozuvchi monkeypatch qilinadi (ega ratifikatsiyasi bilan).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.api.v1.shifts import CloseShift, OpenShift, close_shift, open_shift
from app.api.v1.tills import TillCreate, create_till
from app.models.auth import Employee, EmployeeBranch, Role
from app.models.cash import CashLedgerEntry as CLE
from app.models.catalog import Product, Unit
from app.models.inventory import Inventory
from app.models.org import Branch, Company
from app.models.shifts import Shift
from app.schemas.sales import SaleCreate, SaleItemIn
from app.services.cash import shadow_compare as SC
from app.services.cash import tenant as _t
from app.services.sales import create_sale


def _hex():
    return uuid.uuid4().hex[:8]


def _now():
    return datetime.now(timezone.utc)


def _co(db, native=True):
    """Do'kon + filial + ega + filial biriktirmasi.

    `native=False` — T0 QO'YILMAYDI (legacy/pre-T0 tenant). 10-holat uchun SHART:
    post-T0 da `shifts.py:155-160` bir TILL'da ikkinchi smenani UMUMAN ochmaydi,
    ya'ni ikkinchi-kassir stsenariysi legacy tolerantligiga tayanadi."""
    co = Company(name="SP" + _hex(), code="sp" + _hex(), currency="UZS")
    db.add(co); db.flush()
    br = Branch(company_id=co.id, code="F01", name="Asosiy", is_active=True)
    db.add(br); db.flush()
    if native:
        _t.mark_ledger_native(db, co.id)
    role = db.query(Role).filter(Role.code == "ega").first() or db.query(Role).first()
    emp = Employee(company_id=co.id, full_name="Ega", role_id=role.id)
    db.add(emp); db.flush()
    db.add(EmployeeBranch(employee_id=emp.id, branch_id=br.id)); db.flush()
    db.commit()
    return co, br, emp


def _product(db, co, br, price="10000"):
    u = Unit(code="u" + _hex(), name="dona"); db.add(u); db.flush()
    p = Product(company_id=co.id, article_code="A" + _hex(), name="M" + _hex(),
                unit_id=u.id, base_buy_price=Decimal("6000"),
                base_sell_price=Decimal(price), tax_rate=Decimal("0"))
    db.add(p); db.flush()
    db.add(Inventory(product_id=p.id, branch_id=br.id, qty=Decimal("1000"),
                     updated_at=_now()))
    db.commit()
    return p


def _till(db, emp, br, code="TILL-01"):
    return create_till(TillCreate(branch_id=br.id, code=code), emp=emp, db=db)


def _open(db, emp, till_id, opening="0"):
    return open_shift(OpenShift(opening_cash=Decimal(str(opening)),
                                till_id=uuid.UUID(str(till_id))), emp=emp, db=db)


def _close(db, emp, shift_id, counted="0"):
    return close_shift(uuid.UUID(str(shift_id)),
                       CloseShift(counted_cash=Decimal(str(counted))), emp=emp, db=db)


def _bal(db, co, acc):
    tot = Decimal("0")
    for l in db.query(CLE).filter(CLE.tenant_id == co.id,
                                  CLE.cash_account_id == uuid.UUID(str(acc))).all():
        tot += Decimal(str(l.amount)) if l.direction == "IN" else -Decimal(str(l.amount))
    return tot


def _forge(db, co, br, acc, **over):
    """Leg'ni TO'G'RIDAN-TO'G'RI yozadi — komparatorni baza yarata olmaydigan
    buzuq holatda sinash uchun (ega ratifikatsiyasi)."""
    d = dict(tenant_id=co.id, cash_account_id=uuid.UUID(str(acc)), branch_id=br.id,
             account_type="TILL", shift_id=None, posting_kind="OFF_SHIFT",
             source_type="SHIFT_OPEN", source_id=uuid.uuid4(), leg_index=0,
             direction="IN", category="OPENING", amount=Decimal("1000.00"),
             currency="UZS", device_occurred_at=_now(), server_received_at=_now(),
             recorded_at=_now(), actor_id=None, idempotency_key=str(uuid.uuid4()),
             provenance="NORMAL")
    d.update(over)
    e = CLE(**d)
    db.add(e); db.commit()
    return e


def _dual(db):
    from app.services.cash import retrofit as _cr
    return _cr.dual_write_enabled(db)


def _ochilish(rep, shift_id):
    return next((o for o in rep["openings"] if o["shift_id"] == str(shift_id)), None)


# ═══ 1 / 15) bo'sh till, NORMAL delta konvensiyasi ═════════════════════════
def test_01_bosh_till_ochilish_legi_TOLIQ(db, cashenv):
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    sh = _open(db, emp, till["id"], "3000"); db.commit()

    assert _bal(db, co, till["id"]) == Decimal("3000")
    rep = SC.strict_finalize_report(db, co.id)
    o = _ochilish(rep, sh["id"])
    assert o is not None and o["status"] == "MATCH", o
    assert o["convention"] == "NORMAL"
    assert o["b_pre"] == 0.0 and o["expected"] == 3000.0 and o["actual"] == 3000.0
    assert rep["structural"] == [] and rep["orphan_openings"] == []
    ok, sabab = SC.strict_finalize_verdict(rep)
    assert ok is True, sabab


# ═══ 2) carry-over: kutilgan 0, leg yo'q ═══════════════════════════════════
def test_02_carryover_kutilgan_NOL_leg_YOQ(db, cashenv):
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    sh1 = _open(db, emp, till["id"], "3000"); db.commit()
    _close(db, emp, sh1["id"], "3000"); db.commit()
    sh2 = _open(db, emp, till["id"], "3000"); db.commit()

    assert _bal(db, co, till["id"]) == Decimal("3000"), "sanoq IKKI MARTA yozildi"
    rep = SC.strict_finalize_report(db, co.id)
    o2 = _ochilish(rep, sh2["id"])
    assert o2["status"] == "MATCH", o2
    assert o2["b_pre"] == 3000.0 and o2["expected"] == 0.0 and o2["legs"] == 0
    ok, sabab = SC.strict_finalize_verdict(rep)
    assert ok is True, sabab

    #  ⚠️  ESKI SKALYAR BU YERDA NOLDAN FARQLI — aynan shu sabab u PASS qarorini
    #      bera olmaydi. Legacy: 3000+3000=6000, ledger: 3000.
    eski = SC.compare_tenant(db, co.id, t0=None)
    assert eski["status"] == "REVIEW" and eski["abs_delta"] == 3000.0, eski
    assert SC.finalize_parity_verdict(eski)[0] is False


# ═══ 3) yozilmagan ochilish legi -> FAIL ═══════════════════════════════════
def test_03_ochilish_legi_YOZILMASA_FAIL(db, cashenv, monkeypatch):
    """B_pre=0 bo'lsa leg YOZILISHI SHART. Yozilmasa — bu AYNAN eganing
    kontrmisoli va 1-daraja uni o'tkazib yuborardi."""
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    prod = _product(db, co, br, price="10000")
    till = _till(db, emp, br)

    sh1 = _open(db, emp, till["id"], "3000"); db.commit()
    #  Yashikni NOLGA tushiramiz (xarajat — ikki tomonda ham simmetrik).
    from app.api.v1.cashops import CashOpIn, cash_op
    cash_op(CashOpIn(type="expense", amount=3000.0, reason="drenaj"), emp=emp, db=db)
    db.commit()
    assert _bal(db, co, till["id"]) == Decimal("0")
    _close(db, emp, sh1["id"], "0"); db.commit()

    #  NUQSONNI KIRITAMIZ: yozuvchi legni yozmaydi (legni o'chirish IMKONSIZ —
    #  `trg_cle_immutable` + REVOKE UPDATE,DELETE).
    monkeypatch.setattr("app.services.cash.adapters.opening_float",
                        lambda *a, **k: None)
    sh2 = _open(db, emp, till["id"], "3000"); db.commit()
    monkeypatch.undo()

    rep = SC.strict_finalize_report(db, co.id)
    o2 = _ochilish(rep, sh2["id"])
    assert o2["status"] == "FAIL" and o2["reason"] == "MISSING_OPENING_LEG", o2
    assert o2["b_pre"] == 0.0 and o2["expected"] == 3000.0 and o2["actual"] is None
    ok, sabab = SC.strict_finalize_verdict(rep)
    assert ok is False and "OCHILISH" in sabab, sabab


# ═══ 4) qisman drenaj -> leg = farq ════════════════════════════════════════
def test_04_qisman_drenaj_leg_FARQ(db, cashenv):
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    sh1 = _open(db, emp, till["id"], "3000"); db.commit()
    from app.api.v1.cashops import CashOpIn, cash_op
    cash_op(CashOpIn(type="expense", amount=2000.0, reason="qisman"), emp=emp, db=db)
    db.commit()
    assert _bal(db, co, till["id"]) == Decimal("1000")
    _close(db, emp, sh1["id"], "1000"); db.commit()

    sh2 = _open(db, emp, till["id"], "3000"); db.commit()
    rep = SC.strict_finalize_report(db, co.id)
    o2 = _ochilish(rep, sh2["id"])
    assert o2["status"] == "MATCH", o2
    assert o2["b_pre"] == 1000.0 and o2["expected"] == 2000.0 and o2["actual"] == 2000.0
    assert SC.strict_finalize_verdict(rep)[0] is True


# ═══ 5) noto'g'ri summa -> FAIL ════════════════════════════════════════════
def test_05_ochilish_summasi_NOTOGRI_FAIL(db, cashenv, monkeypatch):
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    sh1 = _open(db, emp, till["id"], "3000"); db.commit()
    from app.api.v1.cashops import CashOpIn, cash_op
    cash_op(CashOpIn(type="expense", amount=2000.0, reason="qisman"), emp=emp, db=db)
    db.commit()
    _close(db, emp, sh1["id"], "1000"); db.commit()

    #  Yozuvchi FARQ emas, TO'LIQ sanoqni yozadi (noto'g'ri konvensiya).
    import app.services.cash.adapters as _ad
    asl = _ad.opening_float
    monkeypatch.setattr(
        "app.services.cash.adapters.opening_float",
        lambda db_, emp_, **kw: asl(db_, emp_, **{**kw, "amount": Decimal("3000")}))
    sh2 = _open(db, emp, till["id"], "3000"); db.commit()
    monkeypatch.undo()

    rep = SC.strict_finalize_report(db, co.id)
    o2 = _ochilish(rep, sh2["id"])
    assert o2["status"] == "FAIL" and o2["reason"] == "OPENING_AMOUNT", o2
    assert o2["expected"] == 2000.0 and o2["actual"] == 3000.0
    assert SC.strict_finalize_verdict(rep)[0] is False


# ═══ 6) kutilgan 0, lekin leg bor -> FAIL ══════════════════════════════════
def test_06_kutilgan_NOL_lekin_leg_BOR_FAIL(db, cashenv, monkeypatch):
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    sh1 = _open(db, emp, till["id"], "3000"); db.commit()
    _close(db, emp, sh1["id"], "3000"); db.commit()

    #  Yozuvchi `delta <= 0` bo'lsa ham yozadi (qoidani buzadi).
    import app.services.cash.adapters as _ad
    asl = _ad.opening_float
    monkeypatch.setattr(
        "app.services.cash.retrofit.adapters.opening_float",
        lambda db_, emp_, **kw: asl(db_, emp_, **{**kw, "amount": Decimal("3000")}))
    #  `_delta > 0` sharti o'zgarmagani uchun yozuvchi chaqirmaydi — legni
    #  TO'G'RIDAN-TO'G'RI yozamiz, AYNI biznes kaliti bilan.
    monkeypatch.undo()
    sh2 = _open(db, emp, till["id"], "3000"); db.commit()
    _forge(db, co, br, till["id"], source_id=uuid.UUID(str(sh2["id"])),
           amount=Decimal("3000.00"), shift_id=uuid.UUID(str(sh2["id"])),
           posting_kind="ON_SHIFT",
           device_occurred_at=db.get(Shift, uuid.UUID(str(sh2["id"]))).opened_at)

    rep = SC.strict_finalize_report(db, co.id)
    o2 = _ochilish(rep, sh2["id"])
    assert o2["status"] == "FAIL" and o2["reason"] == "UNEXPECTED_OPENING_LEG", o2
    assert o2["expected"] == 0.0
    assert SC.strict_finalize_verdict(rep)[0] is False


# ═══ 7) nusxa / buzuq bog'langan leg -> FAIL ═══════════════════════════════
@pytest.mark.parametrize("over,kutilgan", [
    ({"leg_index": 1}, "MALFORMED_LINKED_LEG"),
    ({"leg_index": 2, "direction": "OUT"}, "MALFORMED_LINKED_LEG"),
    ({"leg_index": 3, "category": "SALE"}, "MALFORMED_LINKED_LEG"),
])
def test_07_nusxa_yoki_buzuq_bogʻlangan_leg_FAIL(db, cashenv, over, kutilgan):
    """⚠️  HAQIQIY DUPLICATE (ikki KANONIK leg) bazada ERISHIB BO'LMAYDI:
    `cle_uq_business UNIQUE (tenant_id, source_type, source_id, leg_index)`
    `leg_index=0` ni band qiladi, kanonik yozuvchi esa doim 0 ishlatadi. Shu
    bois `leg_index != 0` MALFORMED bo'lib yiqiladi (ayni natija: FAIL), va
    komparatordagi `DUPLICATE_OPENING_LEG` shoxi himoyaning IKKINCHI qatlami
    bo'lib qoladi — sxema darajasida yetib bo'lmaydigan holat uchun."""
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    sh = _open(db, emp, till["id"], "3000"); db.commit()
    sid = uuid.UUID(str(sh["id"]))
    opened = db.get(Shift, sid).opened_at
    _forge(db, co, br, till["id"], source_id=sid, amount=Decimal("3000.00"),
           device_occurred_at=opened, **over)

    rep = SC.strict_finalize_report(db, co.id)
    o = _ochilish(rep, sid)
    assert o["status"] == "FAIL" and o["reason"] == kutilgan, o
    assert SC.strict_finalize_verdict(rep)[0] is False


# ═══ 9) sog'lom carry-over: 3 smena / 1 till -> PASS ═══════════════════════
def test_09_SOGLOM_carryover_3_smena_1_till_PASS(db, cashenv):
    """`test_M_carryover_does_not_double_count` stsenariysi, lekin QAT'IY
    komparator bilan tasdiqlanadi. ESKI skalyar bu yerda REVIEW beradi."""
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    prod = _product(db, co, br, price="10000")
    till = _till(db, emp, br)

    sh1 = _open(db, emp, till["id"], "0"); db.commit()
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=10)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()
    _close(db, emp, sh1["id"], "100000"); db.commit()

    sh2 = _open(db, emp, till["id"], "100000"); db.commit()
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=5)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()
    _close(db, emp, sh2["id"], "150000"); db.commit()

    sh3 = _open(db, emp, till["id"], "200000"); db.commit()
    assert _bal(db, co, till["id"]) == Decimal("200000")

    rep = SC.strict_finalize_report(db, co.id)
    for sh, kut_b, kut_e in ((sh1, 0.0, 0.0), (sh2, 100000.0, 0.0), (sh3, 150000.0, 50000.0)):
        o = _ochilish(rep, sh["id"])
        assert o["status"] == "MATCH", o
        assert o["b_pre"] == kut_b and o["expected"] == kut_e, (sh["id"], o)
    assert [c for c in rep["components"] if c["status"] != "MATCH"] == [], rep["components"]
    ok, sabab = SC.strict_finalize_verdict(rep)
    assert ok is True, sabab

    #  ⚠️  ESKI SKALYAR shu SOG'LOM rejani RAD etardi — isbot.
    eski = SC.compare_tenant(db, co.id, t0=None)
    assert eski["status"] == "REVIEW", eski
    assert SC.finalize_parity_verdict(eski)[0] is False


# ═══ 10) ikkinchi kassir regressiyasi -> HALI HAM FAIL ═════════════════════
def test_10_ikkinchi_kassir_regressiyasi_HALI_HAM_FAIL(db, cashenv):
    """⚠️  Aniq per-smena invarianti YOLG'IZ bu holatni O'TKAZIB YUBORADI
    (`max(50000-100000,0)=0`, legi 0 -> MATCH). STRUKTURAVIY twin bandi
    aynan shu sabab SAQLANGAN."""
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db, native=False)
    till = _till(db, emp, br)
    shA = _open(db, emp, till["id"], "100000"); db.commit()

    role = db.query(Role).first()
    empB = Employee(company_id=co.id, full_name="Kassir B", role_id=role.id)
    db.add(empB); db.flush()
    db.add(EmployeeBranch(employee_id=empB.id, branch_id=br.id)); db.commit()
    shB = _open(db, empB, till["id"], "50000"); db.commit()

    rep = SC.strict_finalize_report(db, co.id)
    #  A sog'lom; B ning cash.shifts EGIZAGI YO'Q.
    assert _ochilish(rep, shA["id"])["status"] == "MATCH"
    st = [x for x in rep["structural"] if x["shift_id"] == str(shB["id"])]
    assert st and st[0]["status"] == "NO_TWIN", rep["structural"]
    ok, sabab = SC.strict_finalize_verdict(rep)
    assert ok is False and "STRUKTURAVIY" in sabab, sabab

    #  ESKI yuza BAYT-AYNAN o'zgarmagan (operator kontrakti).
    ct = SC.compare_till(db, co.id, uuid.UUID(str(till["id"])), t0=None)
    assert ct["status"] == "REVIEW" and ct["delta"] == -50000.0, ct


# ═══ 11) tartib noaniqligi -> UNDETERMINED ═════════════════════════════════
def test_11_TARTIB_NOANIQLIGI_UNDETERMINED(db, cashenv):
    """Biznes-vaqt bilan qayd vaqti ORASIDA inversiya — `B_pre` ni ishonchli
    tiklab bo'lmaydi, demak fail-closed."""
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    sh1 = _open(db, emp, till["id"], "3000"); db.commit()
    _close(db, emp, sh1["id"], "3000"); db.commit()
    sh2 = _open(db, emp, till["id"], "5000"); db.commit()

    #  INVERSIYA: biznes-vaqti ERTA, lekin qayd vaqti KEYIN.
    opened2 = db.get(Shift, uuid.UUID(str(sh2["id"]))).opened_at
    _forge(db, co, br, till["id"], source_type="CASH_OP", category="CASH_IN",
           source_id=uuid.uuid4(), amount=Decimal("1.00"),
           device_occurred_at=opened2 - timedelta(hours=3),
           recorded_at=_now() + timedelta(minutes=5))

    rep = SC.strict_finalize_report(db, co.id)
    o2 = _ochilish(rep, sh2["id"])
    assert o2["status"] == "UNDETERMINED", o2
    assert o2["reason"] == "ORDERING_AMBIGUOUS", o2
    ok, sabab = SC.strict_finalize_verdict(rep)
    assert ok is False and "NOANIQ" in sabab, sabab


# ═══ 12) bog'lanmagan soxta OPENING -> FAIL ════════════════════════════════
def test_12_BOGLANMAGAN_soxta_OPENING_FAIL(db, cashenv):
    """Tasodifiy `source_id` li OPENING legi hech qaysi smenaga kalitlanmaydi —
    faqat «smena -> leg» yo'nalishi uni UMUMAN ko'rmasdi
    (`cash/lifecycle.open_shift` aynan shunday yozuvchi)."""
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    sh = _open(db, emp, till["id"], "3000"); db.commit()
    _forge(db, co, br, till["id"], source_id=uuid.uuid4(), amount=Decimal("7777.00"))

    rep = SC.strict_finalize_report(db, co.id)
    assert _ochilish(rep, sh["id"])["status"] == "MATCH", "smena o'zi sog'lom bo'lishi kerak"
    orp = rep["orphan_openings"]
    assert len(orp) == 1 and orp[0]["reason"] == "OPENING_UNLINKED", orp
    ok, sabab = SC.strict_finalize_verdict(rep)
    assert ok is False and "BOG'LANMAGAN" in sabab, sabab


# ═══ 14) REKONSTRUKSIYA konvensiyasi -> PASS ═══════════════════════════════
def test_14_REKONSTRUKSIYA_toliq_ochilish_konvensiyasi_PASS(db, cashenv, monkeypatch):
    """Phase-1 backfill'i ochilish legini TO'LIQ `opening_cash` bilan yozadi,
    jonli yozuvchi esa FARQNI. Ikkisi AYNI biznes kalitini egallaydi, shu bois
    kutilgan summa legning O'Z provenance'iga qarab tanlanadi — aralashtirilmaydi.
    """
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    #  Avval yashikda pul bo'ladi (B_pre > 0) — NORMAL konvensiyada kutilgan 0
    #  bo'lardi; REKONSTRUKSIYA konvensiyasida esa TO'LIQ sanoq.
    sh1 = _open(db, emp, till["id"], "4000"); db.commit()
    _close(db, emp, sh1["id"], "4000"); db.commit()

    monkeypatch.setattr("app.services.cash.adapters.opening_float", lambda *a, **k: None)
    sh2 = _open(db, emp, till["id"], "4000"); db.commit()
    monkeypatch.undo()
    sid2 = uuid.UUID(str(sh2["id"]))
    opened2 = db.get(Shift, sid2).opened_at
    _forge(db, co, br, till["id"], source_id=sid2, amount=Decimal("4000.00"),
           device_occurred_at=opened2, provenance="RECONSTRUCTION",
           reconstruction_reason="phase1", reconstruction_source_ref=f"shift:{sid2}")

    rep = SC.strict_finalize_report(db, co.id)
    o2 = _ochilish(rep, sid2)
    assert o2["convention"] == "RECONSTRUCTION", o2
    assert o2["status"] == "MATCH", o2
    assert o2["expected"] == 4000.0 and o2["actual"] == 4000.0
    assert o2["b_pre"] is None, "REKONSTRUKSIYA kutilmasi B_pre ga BOG'LIQ EMAS"
    #  Noto'g'ri summali rekonstruksiya legi esa YIQILADI.
    assert _ochilish(rep, sh1["id"])["status"] == "MATCH"


def test_14b_REKONSTRUKSIYA_summasi_NOTOGRI_FAIL(db, cashenv, monkeypatch):
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    monkeypatch.setattr("app.services.cash.adapters.opening_float", lambda *a, **k: None)
    sh = _open(db, emp, till["id"], "4000"); db.commit()
    monkeypatch.undo()
    sid = uuid.UUID(str(sh["id"]))
    _forge(db, co, br, till["id"], source_id=sid, amount=Decimal("999.00"),
           device_occurred_at=db.get(Shift, sid).opened_at, provenance="RECONSTRUCTION",
           reconstruction_reason="phase1", reconstruction_source_ref=f"shift:{sid}")
    rep = SC.strict_finalize_report(db, co.id)
    o = _ochilish(rep, sid)
    assert o["status"] == "FAIL" and o["reason"] == "RECONSTRUCTION_AMOUNT", o


# ═══ 13-PG) qoplanmagan toifa HAQIQIY legda ════════════════════════════════
def test_13pg_QOPLANMAGAN_toifa_haqiqiy_legda_UNDETERMINED(db, cashenv):
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    till = _till(db, emp, br)
    sh = _open(db, emp, till["id"], "3000"); db.commit()
    #  ADJUSTMENT — qoplanmagan va `ACCOUNT_OPENING` manba turi EMAS, demak
    #  `_ledger_flows` filtridan ham o'tadi.
    _forge(db, co, br, till["id"], source_type="CASH_OP", category="ADJUSTMENT",
           source_id=uuid.uuid4(), amount=Decimal("5.00"))
    rep = SC.strict_finalize_report(db, co.id)
    uc = [u["category"] for u in rep["uncovered_categories"]]
    assert "ADJUSTMENT" in uc, rep["uncovered_categories"]
    ok, sabab = SC.strict_finalize_verdict(rep)
    assert ok is False and "QOPLANMAGAN" in sabab, sabab


# ═══ komponentlar HAQIQIY legda ════════════════════════════════════════════
def test_komponentlar_haqiqiy_naqd_savdoda_NOL_delta(db, cashenv):
    if not _dual(db):
        pytest.skip("dual-write o'chiq")
    co, br, emp = _co(db)
    prod = _product(db, co, br, price="10000")
    till = _till(db, emp, br)
    sh = _open(db, emp, till["id"], "0"); db.commit()
    create_sale(db, emp, SaleCreate(items=[SaleItemIn(product_id=prod.id, qty=3)],
                                    payment_method="cash", client_uuid=uuid.uuid4()))
    db.commit()
    from app.api.v1.cashops import CashOpIn, cash_op
    cash_op(CashOpIn(type="expense", amount=4000.0, reason="x"), emp=emp, db=db)
    cash_op(CashOpIn(type="payin", amount=1500.0, reason="y"), emp=emp, db=db)
    db.commit()

    rep = SC.strict_finalize_report(db, co.id)
    d = {c["component"]: c for c in rep["components"]}
    assert d["cash_sales"]["ledger_signed"] == 30000.0
    assert d["expense"]["ledger_signed"] == -4000.0
    assert d["payin"]["ledger_signed"] == 1500.0
    for nom in ("cash_sales", "expense", "payin", "payout", "net_cash_purchases"):
        assert d[nom]["status"] == "MATCH", d[nom]
    assert SC.strict_finalize_verdict(rep)[0] is True
