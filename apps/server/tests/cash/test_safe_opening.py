# -*- coding: utf-8 -*-
"""Phase 1 — SEYF ochilishi: XULQ testlari (haqiqiy PostgreSQL).

Shartnoma: `docs/PURCHASE_SETTLEMENT_PHASE1.md` §1–§4, §8, §9, §11 (T-1…T-12, T-17, T-21).
Parity (T-13…T-16, T-20) — `test_safe_opening_parity.py`.

⚠️  Bu testlar HAQIQIY `CashPostingService` va HAQIQIY gardlarni chaqiradi — qoidalar
    qayta yozilmaydi.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.auth import Employee, Role
from app.models.cash import (
    CashAccount,
    CashAccountOpening,
    CashLedgerEntry,
    CashSourceType,
)
from app.services.cash import safe_opening as so
from app.services.cash.errors import CashError, CashPostingError
from tests.cash._factory import make_account, post_entry

REF = "DALOLATNOMA-2026-09-28/01"


# ── yordamchilar ────────────────────────────────────────────────────────────
def _emp(db: Session, env, role_code: str) -> Employee:
    """Berilgan ROL KODI bilan xodim (rol kodi `_is_manager_plus` uchun MUHIM)."""
    r = db.query(Role).filter(Role.code == role_code).first()
    if r is None:
        r = Role(code=role_code, name=role_code)
        db.add(r)
        db.flush()
    e = Employee(company_id=env.company_id, full_name=f"T {role_code}", role_id=r.id)
    db.add(e)
    db.commit()
    db.refresh(e)
    e.role  # rol yuklansin
    return e


def _safe(db, env) -> CashAccount:
    return make_account(db, env, "SAFE")


def _now():
    return datetime.now(timezone.utc)


_UNSET = object()


def _attest(db, emp, acc, *, kind="COUNTED", amount="1250000.00", at=_UNSET, ref=REF):
    """⚠️  `at=None` AYNAN uzatiladi (sentinel): "sanoq vaqti majburiy" holati sinalsin."""
    return so.attest_opening(db, emp, account=acc, kind=kind, counted_amount=amount,
                             counted_at=(_now() if at is _UNSET else at),
                             attestation_ref=ref)


# ═══ T-1 · T-3) COUNTED: leg AYNAN kutilgan shaklda, AYNAN BITTA ═══════════
def test_1_3_counted_leg_shakli(db, cashenv):
    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    row, status = _attest(db, mgr, acc)
    assert status == "created"

    legs = db.query(CashLedgerEntry).filter(
        CashLedgerEntry.tenant_id == cashenv.company_id,
        CashLedgerEntry.cash_account_id == acc.id).all()
    assert len(legs) == 1, "AYNAN bitta leg bo'lishi kerak"
    e = legs[0]
    assert e.provenance == "NORMAL"                   # RECONSTRUCTION EMAS (B1)
    assert e.source_type == CashSourceType.ACCOUNT_OPENING.value
    assert str(e.source_id) == str(row.id) and e.leg_index == 0
    assert e.direction == "IN" and e.category == "ADJUSTMENT"
    assert e.posting_kind == "OFF_SHIFT" and e.shift_id is None
    assert e.account_type == "SAFE"
    assert Decimal(str(e.amount)) == Decimal("1250000.00")
    # NORMAL leg'da rekonstruksiya maydonlari BO'LMAYDI (`cle_recon_prov`)
    assert e.reconstruction_reason is None and e.reconstruction_source_ref is None
    # attestatsiya havolasi MANBA qatorida (legga sig'maydi — CHECK taqiqlaydi)
    assert row.attestation_ref == REF and row.attested_by == mgr.id
    assert str(row.ledger_entry_id) == str(e.id)


# ═══ T-2) KNOWN_ZERO: yozuv BOR, ledger legi YO'Q ══════════════════════════
def test_2_known_zero_legsiz(db, cashenv):
    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    row, status = _attest(db, mgr, acc, kind="KNOWN_ZERO", amount="0")
    assert status == "created"
    assert row.ledger_entry_id is None
    assert db.query(CashLedgerEntry).filter(
        CashLedgerEntry.cash_account_id == acc.id).count() == 0, "nol summali leg YOZILMAYDI"
    assert so.opening_state(db, company_id=cashenv.company_id,
                            cash_account_id=acc.id) == so.KNOWN_ZERO
    assert so.is_operational(db, company_id=cashenv.company_id, account=acc) is True


# ═══ T-4) UNKNOWN: yozuv yo'q -> OPERATSION EMAS (nol EMAS) ════════════════
def test_4_unknown_operatsion_emas(db, cashenv):
    acc = _safe(db, cashenv)
    assert so.opening_state(db, company_id=cashenv.company_id,
                            cash_account_id=acc.id) == so.UNKNOWN
    assert so.is_operational(db, company_id=cashenv.company_id, account=acc) is False
    # TILL bu qoidadan TASHQARIDA
    till = make_account(db, cashenv, "TILL")
    assert so.is_operational(db, company_id=cashenv.company_id, account=till) is True


# ═══ T-5) UNKNOWN SEYFga posting -> RAD ════════════════════════════════════
def test_5_unknown_seyfga_posting_rad(db, cashenv):
    from app.services.cash.commands import PostingCommand
    from app.services.cash.posting import cash_posting_service

    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    with pytest.raises(CashPostingError) as ei:
        cash_posting_service.post(db, mgr, PostingCommand(
            cash_account_id=acc.id, source_type=CashSourceType.PURCHASE.value,
            source_id=uuid.uuid4(), leg_index=0, direction="OUT", category="PURCHASE_OUT",
            amount=Decimal("100.00"), tenant_id=cashenv.company_id), commit=False)
    db.rollback()
    assert ei.value.code == CashError.SAFE_OPENING_REQUIRED
    assert ei.value.status_code == 409


# ═══ T-6) UNKNOWN SEYFga inkassa (transfer) -> RAD ═════════════════════════
def test_6_unknown_seyfga_inkassa_rad(db, cashenv):
    from app.services.cash.commands import TransferCommand
    from app.services.cash.posting import cash_posting_service

    mgr = _emp(db, cashenv, "menejer")
    till = make_account(db, cashenv, "TILL")
    acc = _safe(db, cashenv)
    post_entry(db, cashenv, till, amount=Decimal("500.00"))     # TILLda pul bor
    with pytest.raises(CashPostingError) as ei:
        cash_posting_service.post_transfer(db, mgr, TransferCommand(
            from_account_id=till.id, to_account_id=acc.id, amount=Decimal("100.00"),
            source_id=uuid.uuid4(), tenant_id=cashenv.company_id), commit=False)
    db.rollback()
    assert ei.value.code == CashError.SAFE_OPENING_REQUIRED


# ═══ T-7) Ochilishning O'ZI gardni aylanib o'tadi; keyin SEYF ISHLAYDI ═════
def test_7_ochilish_gardni_aylanadi_va_keyin_ishlaydi(db, cashenv):
    from app.services.cash.commands import PostingCommand
    from app.services.cash.posting import cash_posting_service

    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    _attest(db, mgr, acc, amount="1000.00")            # istisno: ACCOUNT_OPENING
    assert so.is_operational(db, company_id=cashenv.company_id, account=acc) is True
    res = cash_posting_service.post(db, mgr, PostingCommand(
        cash_account_id=acc.id, source_type=CashSourceType.PURCHASE.value,
        source_id=uuid.uuid4(), leg_index=0, direction="OUT", category="PURCHASE_OUT",
        amount=Decimal("400.00"), tenant_id=cashenv.company_id), commit=True)
    assert res.entry_ids
    from app.services.cash import repositories as repo
    assert repo.account_balance(db, cashenv.company_id, acc.id) == Decimal("600.00")


# ═══ T-8) TILL hisobiga ochilish -> RAD ════════════════════════════════════
def test_8_till_uchun_ochilish_rad(db, cashenv):
    mgr = _emp(db, cashenv, "menejer")
    till = make_account(db, cashenv, "TILL")
    with pytest.raises(CashPostingError) as ei:
        _attest(db, mgr, till)
    db.rollback()
    assert ei.value.code == CashError.INVALID_ACCOUNT_TYPE


# ═══ T-9) AYNI payload qayta -> idempotent, IKKINCHI leg YO'Q ══════════════
def test_9_idempotent_qayta_attestatsiya(db, cashenv):
    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    at = _now()
    row1, s1 = _attest(db, mgr, acc, amount="777000.00", at=at)
    row2, s2 = _attest(db, mgr, acc, amount="777000.00", at=at)
    assert s1 == "created" and s2 == "duplicate"
    assert str(row1.id) == str(row2.id)
    assert db.query(CashLedgerEntry).filter(
        CashLedgerEntry.cash_account_id == acc.id).count() == 1
    assert db.query(CashAccountOpening).filter(
        CashAccountOpening.cash_account_id == acc.id).count() == 1


# ═══ T-10) BOSHQA payload -> 409, HECH NARSA yozilmaydi ════════════════════
@pytest.mark.parametrize("farq", ["summa", "havola", "vaqt", "tur"])
def test_10_zid_qayta_attestatsiya_409(db, cashenv, farq):
    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    at = _aware(acc.created_at)          # hisob yaratilgan lahza — doim QONUNIY
    _attest(db, mgr, acc, amount="500000.00", at=at)
    kw = dict(amount="500000.00", at=at, ref=REF, kind="COUNTED")
    if farq == "summa":
        kw["amount"] = "500001.00"
    elif farq == "havola":
        kw["ref"] = "BOSHQA-HUJJAT"
    elif farq == "vaqt":
        kw["at"] = at + timedelta(minutes=1)   # QONUNIY, lekin BOSHQA
    else:
        kw.update(kind="KNOWN_ZERO", amount="0")
    with pytest.raises(CashPostingError) as ei:
        _attest(db, mgr, acc, **kw)
    db.rollback()
    assert ei.value.code == CashError.SAFE_OPENING_CONFLICT
    assert ei.value.status_code == 409
    assert db.query(CashLedgerEntry).filter(
        CashLedgerEntry.cash_account_id == acc.id).count() == 1, "zid urinish leg yozdi"


# ═══ T-11) PARALLEL ikki attestatsiya -> AYNAN BITTASI yozadi ══════════════
def test_11_parallel_aynan_bittasi(db, cashenv):
    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    db.commit()
    at = _now()
    results, errors = [], []
    barrier = threading.Barrier(2)

    def worker(i):
        s = Session(cashenv.engine)
        try:
            m = s.get(Employee, mgr.id)
            m.role
            a = s.get(CashAccount, acc.id)
            barrier.wait(timeout=30)
            r, st = so.attest_opening(s, m, account=a, kind="COUNTED",
                                      counted_amount=f"{100000 + i}.00", counted_at=at,
                                      attestation_ref=f"REF-{i}")
            results.append((str(r.id), st))
        except Exception as e:                         # noqa: BLE001
            errors.append(e)
            s.rollback()
        finally:
            s.close()

    ts = [threading.Thread(target=worker, args=(i,)) for i in (0, 1)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)

    assert len(results) == 1, (results, [str(e) for e in errors])
    assert len(errors) == 1 and getattr(errors[0], "code", None) == CashError.SAFE_OPENING_CONFLICT
    fresh = Session(cashenv.engine)
    try:
        assert fresh.query(CashAccountOpening).filter(
            CashAccountOpening.cash_account_id == acc.id).count() == 1
        assert fresh.query(CashLedgerEntry).filter(
            CashLedgerEntry.cash_account_id == acc.id).count() == 1
    finally:
        fresh.close()


# ═══ T-12) Tarixi bor, ochilishi yo'q -> fail-closed ═══════════════════════
def test_12_tarix_bor_ochilish_yoq(db, cashenv):
    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    post_entry(db, cashenv, acc, amount=Decimal("300.00"))     # gardni aylanib o'tgan tarix
    with pytest.raises(CashPostingError) as ei:
        _attest(db, mgr, acc)
    db.rollback()
    assert ei.value.code == CashError.SAFE_OPENING_BLOCKED_BY_HISTORY
    # va u HAMON operatsion emas (retroaktiv "nol" YO'Q)
    assert so.is_operational(db, company_id=cashenv.company_id, account=acc) is False


# ═══ T-17) RUXSAT: menejer+ darvozasi xizmat qatlamida ═════════════════════
@pytest.mark.parametrize("rol,ok", [("ega", True), ("administrator", True),
                                    ("menejer", True), ("kassir", False),
                                    ("omborchi", False)])
def test_17_menejer_plus_darvozasi(db, cashenv, rol, ok):
    e = _emp(db, cashenv, rol)
    acc = _safe(db, cashenv)
    if ok:
        _, st = _attest(db, e, acc)
        assert st == "created"
    else:
        with pytest.raises(CashPostingError) as ei:
            _attest(db, e, acc)
        db.rollback()
        assert ei.value.code == CashError.UNAUTHORIZED_OPERATION
        assert so.opening_state(db, company_id=cashenv.company_id,
                                cash_account_id=acc.id) == so.UNKNOWN


# ═══ T-17b) KNOWN_ZERO ham menejer+ talab qiladi (leg yo'q -> darvoza SHU YERDA) ══
def test_17b_known_zero_ham_menejer_plus(db, cashenv):
    kassir = _emp(db, cashenv, "kassir")
    acc = _safe(db, cashenv)
    with pytest.raises(CashPostingError) as ei:
        _attest(db, kassir, acc, kind="KNOWN_ZERO", amount="0")
    db.rollback()
    assert ei.value.code == CashError.UNAUTHORIZED_OPERATION


# ═══ T-21) VAQT shartnomasi ════════════════════════════════════════════════
def test_21_counted_at_majburiy_va_chegaralangan(db, cashenv):
    mgr = _emp(db, cashenv, "menejer")

    acc = _safe(db, cashenv)
    with pytest.raises(CashPostingError) as e1:
        _attest(db, mgr, acc, at=None)                         # None -> majburiy
    db.rollback()
    assert e1.value.code == CashError.INVALID_TIMESTAMP

    with pytest.raises(CashPostingError) as e2:
        _attest(db, mgr, acc, at=_now() + timedelta(hours=2))  # kelajak
    db.rollback()
    assert e2.value.code == CashError.INVALID_TIMESTAMP

    with pytest.raises(CashPostingError) as e3:                # hisobdan OLDIN
        _attest(db, mgr, acc, at=_aware(acc.created_at) - timedelta(days=1))
    db.rollback()
    assert e3.value.code == CashError.INVALID_TIMESTAMP

    # to'g'ri vaqt -> legning `device_occurred_at` AYNAN sanoq vaqti.
    # ⚠️  Sanoq vaqti O'TMISHDA olinadi: `recorded_at` (SERVER vaqti) undan keyin bo'lishi
    #     kerak — ikkisi ALOHIDA vaqt, biri ikkinchisini almashtirmaydi.
    at = _aware(acc.created_at)
    row, _ = _attest(db, mgr, acc, at=at)
    e = db.get(CashLedgerEntry, row.ledger_entry_id)
    assert _aware(e.device_occurred_at) == at
    assert _aware(e.recorded_at) >= at
    assert _aware(e.recorded_at) != at                          # server vaqti — alohida


def _aware(dt):
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ═══ T-9b) shakl validatsiyasi (KNOWN_ZERO/COUNTED nomuvofiqligi) ══════════
@pytest.mark.parametrize("kind,amount", [("KNOWN_ZERO", "1.00"), ("COUNTED", "0"),
                                         ("BOSHQA", "5.00")])
def test_shakl_validatsiyasi(db, cashenv, kind, amount):
    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    with pytest.raises(CashPostingError) as ei:
        _attest(db, mgr, acc, kind=kind, amount=amount)
    db.rollback()
    assert ei.value.code == CashError.INVALID_INPUT


def test_attestatsiya_havolasi_majburiy(db, cashenv):
    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    with pytest.raises(CashPostingError) as ei:
        _attest(db, mgr, acc, ref="   ")
    db.rollback()
    assert ei.value.code == CashError.INVALID_INPUT


# ═══ O'ZGARMASLIK: ochilish yozuvini TAHRIRLAB/O'CHIRIB bo'lmaydi ══════════
def test_ochilish_yozuvi_ozgarmas(db, cashenv):
    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    row, _ = _attest(db, mgr, acc)
    db.commit()
    # `fn_block_mutation` `restrict_violation` beradi -> SQLAlchemy uni IntegrityError
    # sifatida ko'taradi (RestrictViolation).
    from sqlalchemy.exc import IntegrityError
    for sql in (f"UPDATE cash.cash_account_openings SET counted_amount = 1 WHERE id = '{row.id}'",
                f"DELETE FROM cash.cash_account_openings WHERE id = '{row.id}'"):
        with pytest.raises(IntegrityError):
            db.execute(__import__("sqlalchemy").text(sql))
        db.rollback()


# ═══ BUZUQ yozuv: manba bor, leg YO'Q -> OPERATSION EMAS ═══════════════════
def test_buzuq_yozuv_operatsion_emas(db, cashenv):
    """⚠️  Tayyorlik `kind`ga EMAS, HAQIQIY legga qaraydi."""
    mgr = _emp(db, cashenv, "menejer")
    acc = _safe(db, cashenv)
    row, _ = _attest(db, mgr, acc)
    db.commit()
    # legni "yo'qotamiz" (jadval o'zgarmas, shu bois MANBANI emas, KESHNI buzamiz):
    # yozuvni boshqa hisobga ko'chira olmaymiz, shu bois legning O'ZINI tekshiramiz
    row.ledger_entry_id  # mavjud
    e = db.get(CashLedgerEntry, row.ledger_entry_id)
    assert e is not None
    # summasi mos kelmasa -> operatsion EMAS (sun'iy: manba qatorini in-memory buzamiz)
    db.expunge(row)
    fake = CashAccountOpening(
        id=row.id, tenant_id=row.tenant_id, cash_account_id=row.cash_account_id,
        account_type=row.account_type, kind=row.kind,
        counted_amount=Decimal(str(row.counted_amount)) + 1, currency=row.currency,
        counted_at=row.counted_at, attested_by=row.attested_by,
        attestation_ref=row.attestation_ref, ledger_entry_id=row.ledger_entry_id,
        created_at=row.created_at)
    assert so._opening_consistent(db, fake) is False
