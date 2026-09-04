"""CashPostingService — biznes-hodisa → CashLedger yagona posting chegarasi.

Kontrakt v1.0 (POSTING SERVICE CONTRACT READY) ning 15-qadamli pipeline'ini bajaradi.
FAQAT shu servis `cash.cash_ledger_entries`ga yozadi (DB'da `cash_posting` roli).

Qadamlar tartibi (kontrakt §03):
 1 auth  2 validate  3 resolve account  4 lock  5 IN-LOCK idempotency (sufficiency'DAN OLDIN)
 6 currency  7 timestamp  8 shift A/B/C/D  9 OUT sufficiency  10 negative approval
 11 reversal  12 transfer(alohida)  13 exception rows  14 atomik persist  15 canonical result

MUHIM: idempotency OUT-sufficiency'DAN OLDIN — dublikat OUT retry hech qачон INSUFFICIENT_CASH
bo'lmaydi (adversarial review MAJOR). Transfer TILL leg'ining смена qatori ham lock qilinadi
(transfer-vs-close race — adversarial review CRITICAL).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.cash import (
    CashAccount,
    CashCategory,
    CashDirection,
    CashLedgerEntry,
    CashLedgerException,
    CashPostingKind,
    CashShift,
    CashShiftStatus,
    CashSourceType,
    CashTransfer,
    NegativeCashApproval,
)
from app.services.cash import repositories as repo
from app.services.cash.commands import (
    IDEMPOTENCY_CREATED,
    IDEMPOTENCY_DUPLICATE,
    PostingCommand,
    PostingResult,
    ReversalCommand,
    TransferCommand,
)
from app.services.cash.errors import CashError, CashPostingError

_MANAGER_PLUS = {"ega", "administrator", "menejer"}
# Timestamp oynasi (kontrakt §06, offline-safe): [opened_at − tol, opened_at + max_dur + tol],
# barqaror/preserved qiymatlarga bog'langan (server_received_at'ga EMAS). Sozlanadi.
_MAX_SHIFT_HOURS = int(os.getenv("CASH_MAX_SHIFT_HOURS", "24"))
_TS_TOLERANCE_MIN = int(os.getenv("CASH_TS_TOLERANCE_MIN", "60"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _D(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def _is_manager_plus(emp) -> bool:
    return getattr(getattr(emp, "role", None), "code", None) in _MANAGER_PLUS


class CashPostingService:
    """Yagona posting chegarasi. Har metod BITTA atomik tranzaksiyani boshqaradi."""

    # ── ochiq API ────────────────────────────────────────────────────────────
    def post(self, db: Session, emp, cmd: PostingCommand, *, commit: bool = True) -> PostingResult:
        """commit=True (standalone): servis tranzaksiyani boshqaradi.
        commit=False (retrofit/dual-write): chaqiruvchining tranzaksiyasiga qo'shiladi —
        servis COMMIT/ROLLBACK qilmaydi, faqat flush qiladi (source+ledger atomik bo'lsin)."""
        cmd.tenant_id = self._tenant(emp, cmd.tenant_id)
        recv = _now()
        device_ts = cmd.device_occurred_at or recv

        # 1) authorize
        self._authorize(emp, cmd)
        # 2) validate input
        self._validate(cmd)
        # 3) resolve CashAccount
        acct = self._resolve_account(db, cmd.tenant_id, cmd.cash_account_id)
        currency = cmd.currency or acct.currency

        # EARLY idempotency short-circuit (lock'dan OLDIN) — allaqachon yozilgan dublikatni qaytaradi
        early = repo.get_entry_by_business_key(db, cmd.tenant_id, cmd.source_type, cmd.source_id, cmd.leg_index)
        if early is not None:
            if commit:
                db.rollback()
            return self._result_from_entry(early, IDEMPOTENCY_DUPLICATE)

        # 4) lock account (+ nomzod смена qatori TILL uchun)
        self._lock_account(db, cmd.tenant_id, acct.id)
        cand_shift = self._lock_candidate_shift(db, cmd.tenant_id, acct, cmd.origin_shift_id)

        # 5) AUTHORITATIVE in-lock idempotency (sufficiency'DAN OLDIN)
        again = repo.get_entry_by_business_key(db, cmd.tenant_id, cmd.source_type, cmd.source_id, cmd.leg_index)
        if again is not None:
            if commit:
                db.rollback()
            return self._result_from_entry(again, IDEMPOTENCY_DUPLICATE)

        # 6) currency
        if currency != acct.currency:
            raise CashPostingError(CashError.CURRENCY_MISMATCH,
                                   f"Valyuta mos emas: {currency} != {acct.currency}")
        # 7) timestamp validation (verdict shift-window bo'yicha; §08/§09)
        self._validate_timestamp(device_ts)
        # 8) shift resolution A/B/C/D
        posting_kind, shift_id, exc_kinds = self._resolve_shift(cmd, acct, cand_shift, device_ts)

        # 9/10) OUT sufficiency + negative override
        till_before = till_after = None
        override = False
        if cmd.direction == CashDirection.OUT.value:
            bal = repo.account_balance(db, cmd.tenant_id, acct.id)
            if bal - _D(cmd.amount) < 0:
                if acct.type != "TILL":
                    raise CashPostingError(CashError.INSUFFICIENT_CASH,
                                           f"Naqd yetarli emas: balans {bal}, summa {cmd.amount}")
                if not cmd.allow_negative:
                    raise CashPostingError(CashError.INSUFFICIENT_CASH,
                                           f"Naqd yetarli emas: balans {bal}, summa {cmd.amount}")
                if not _is_manager_plus(emp):
                    raise CashPostingError(CashError.NEGATIVE_APPROVAL_REQUIRED,
                                           "Manfiy naqd uchun menejer tasdiqi kerak")
                override = True
                till_before = bal
                till_after = bal - _D(cmd.amount)
                exc_kinds = exc_kinds + ["NEGATIVE_OVERRIDE"]

        # 11) reversal semantics
        if cmd.reverses_id is not None:
            self._validate_reversal(db, cmd)

        # 13/14) build + persist atomically
        return self._persist(db, emp, cmd, acct, currency, device_ts, recv,
                             posting_kind, shift_id, exc_kinds,
                             override, till_before, till_after, commit=commit)

    def post_reversal(self, db: Session, emp, rc: ReversalCommand, *, commit: bool = True) -> PostingResult:
        rc.tenant_id = self._tenant(emp, rc.tenant_id)
        orig = db.get(CashLedgerEntry, rc.reverses_id)
        if orig is None or orig.tenant_id != rc.tenant_id:
            raise CashPostingError(CashError.INVALID_REVERSAL, "Original entry topilmadi")
        opp = (CashDirection.IN.value if orig.direction == CashDirection.OUT.value
               else CashDirection.OUT.value)
        cmd = PostingCommand(
            cash_account_id=orig.cash_account_id,
            source_type=orig.source_type,
            source_id=rc.source_id,
            direction=opp,
            category=CashCategory.ADJUSTMENT.value,
            amount=_D(orig.amount),
            origin_shift_id=rc.origin_shift_id,
            currency=orig.currency,
            device_occurred_at=rc.device_occurred_at,
            idempotency_key=rc.idempotency_key,
            reverses_id=orig.id,
            tenant_id=rc.tenant_id,
        )
        return self.post(db, emp, cmd, commit=commit)

    def post_transfer(self, db: Session, emp, tc: TransferCommand, *, commit: bool = True) -> PostingResult:
        tc.tenant_id = self._tenant(emp, tc.tenant_id)
        recv = _now()
        device_ts = tc.device_occurred_at or recv
        if tc.from_account_id == tc.to_account_id:
            raise CashPostingError(CashError.INVALID_TRANSFER, "from == to")
        frm = self._resolve_account(db, tc.tenant_id, tc.from_account_id)
        to = self._resolve_account(db, tc.tenant_id, tc.to_account_id)
        currency = tc.currency or frm.currency
        if frm.currency != to.currency or currency != frm.currency:
            raise CashPostingError(CashError.CURRENCY_MISMATCH, "Transfer valyutasi mos emas")

        # EARLY idempotency (OUT leg biznes-kaliti bo'yicha)
        early = repo.get_entry_by_business_key(db, tc.tenant_id, CashSourceType.TRANSFER.value, tc.source_id, 0)
        if early is not None:
            if commit:
                db.rollback()
            return self._result_from_entry(early, IDEMPOTENCY_DUPLICATE, transfer=True)

        # 5) lock: ikkala hisob ASCENDING ID tartibida + TILL leg(lar)ining смена qatori
        for aid in sorted([frm.id, to.id], key=lambda x: str(x)):
            self._lock_account(db, tc.tenant_id, aid)
        for acc in (frm, to):
            if acc.type == "TILL":
                self._lock_candidate_shift(db, tc.tenant_id, acc, None)

        # in-lock idempotency (sufficiency'дан oldin)
        again = repo.get_entry_by_business_key(db, tc.tenant_id, CashSourceType.TRANSFER.value, tc.source_id, 0)
        if again is not None:
            if commit:
                db.rollback()
            return self._result_from_entry(again, IDEMPOTENCY_DUPLICATE, transfer=True)

        # 8) source balance yetarliligi
        bal = repo.account_balance(db, tc.tenant_id, frm.id)
        if bal - _D(tc.amount) < 0:
            raise CashPostingError(CashError.INSUFFICIENT_CASH,
                                   f"Transfer uchun naqd yetarli emas: {bal} < {tc.amount}")

        # 9-11) header + OUT + IN
        header = CashTransfer(tenant_id=tc.tenant_id, from_account_id=frm.id, to_account_id=to.id,
                              amount=_D(tc.amount), currency=currency, actor_id=getattr(emp, "id", None),
                              occurred_at=device_ts, created_at=recv)
        db.add(header)
        db.flush()
        out_kind, out_shift, _ = self._resolve_transfer_leg(db, tc.tenant_id, frm, device_ts)
        in_kind, in_shift, _ = self._resolve_transfer_leg(db, tc.tenant_id, to, device_ts)
        out_leg = self._new_entry(tc.tenant_id, frm, currency, CashDirection.OUT.value,
                                  CashCategory.TRANSFER.value, _D(tc.amount), CashSourceType.TRANSFER.value,
                                  tc.source_id, 0, out_kind, out_shift, device_ts, recv,
                                  getattr(emp, "id", None), tc.idempotency_key, transfer_group_id=header.id,
                                  origin_device_id=tc.origin_device_id)
        in_leg = self._new_entry(tc.tenant_id, to, currency, CashDirection.IN.value,
                                 CashCategory.TRANSFER.value, _D(tc.amount), CashSourceType.TRANSFER.value,
                                 tc.source_id, 1, in_kind, in_shift, device_ts, recv,
                                 getattr(emp, "id", None), tc.idempotency_key, transfer_group_id=header.id,
                                 origin_device_id=tc.origin_device_id)
        db.add_all([out_leg, in_leg])
        if not commit:
            db.flush()
        else:
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = repo.get_entry_by_business_key(db, tc.tenant_id, CashSourceType.TRANSFER.value, tc.source_id, 0)
                if existing is not None:
                    return self._result_from_entry(existing, IDEMPOTENCY_DUPLICATE, transfer=True)
                raise CashPostingError(CashError.INVALID_TRANSFER, "Transfer yozib bo'lmadi")
        return PostingResult(
            entry_ids=[out_leg.id, in_leg.id], cash_account_id=frm.id, shift_id=out_shift,
            posting_kind=out_kind, amount=_D(tc.amount), direction="TRANSFER", category="TRANSFER",
            currency=currency, device_occurred_at=device_ts, recorded_at=recv,
            idempotency=IDEMPOTENCY_CREATED, transfer_group_id=header.id,
        )

    # ── ichki: auth / validate / resolve ─────────────────────────────────────
    def _tenant(self, emp, claimed):
        real = getattr(emp, "company_id", None)
        if real is None:
            raise CashPostingError(CashError.UNAUTHORIZED_OPERATION, "Autentifikatsiya yo'q")
        if claimed is not None and claimed != real:
            raise CashPostingError(CashError.TENANT_MISMATCH, "Tenant mos emas")
        return real

    def _authorize(self, emp, cmd: PostingCommand):
        # MANUAL adjustment (reversal EMAS) va manfiy override — menejer+ (§18).
        # Reversal ham category=ADJUSTMENT ishlatadi, lekin u kassir operatsiyasi (reverses_id bor).
        if (cmd.category == CashCategory.ADJUSTMENT.value and cmd.reverses_id is None
                and not _is_manager_plus(emp)):
            raise CashPostingError(CashError.UNAUTHORIZED_OPERATION, "Tuzatish uchun menejer+ kerak")
        if cmd.allow_negative and not _is_manager_plus(emp):
            raise CashPostingError(CashError.UNAUTHORIZED_OPERATION, "Manfiy override uchun menejer+ kerak")

    def _validate(self, cmd: PostingCommand):
        if _D(cmd.amount) <= 0:
            raise CashPostingError(CashError.INVALID_INPUT, "Summa musbat bo'lishi kerak")
        if cmd.direction not in (CashDirection.IN.value, CashDirection.OUT.value):
            raise CashPostingError(CashError.INVALID_INPUT, "Yo'nalish noto'g'ri")
        if cmd.provenance == "RECONSTRUCTION" and not (
            cmd.reconstruction_reason and cmd.reconstruction_source_ref
        ):
            raise CashPostingError(CashError.INVALID_INPUT,
                                   "RECONSTRUCTION uchun reason+source_ref kerak")
        if cmd.provenance == "NORMAL" and (cmd.reconstruction_reason or cmd.reconstruction_source_ref):
            raise CashPostingError(CashError.INVALID_INPUT, "NORMAL leg'да reconstruction maydonlari bo'lmaydi")

    def _resolve_account(self, db: Session, tenant_id, account_id) -> CashAccount:
        acct = db.get(CashAccount, account_id)
        if acct is None:
            raise CashPostingError(CashError.ACCOUNT_NOT_FOUND, "Hisob topilmadi", status_code=404)
        if acct.tenant_id != tenant_id:
            raise CashPostingError(CashError.TENANT_MISMATCH, "Hisob boshqa tenantniki")
        if acct.status == "ARCHIVED":
            raise CashPostingError(CashError.ACCOUNT_ARCHIVED, "Hisob arxivlangan")
        return acct

    # ── ichki: lock ──────────────────────────────────────────────────────────
    def _lock_account(self, db: Session, tenant_id, account_id):
        db.execute(select(CashAccount.id).where(
            CashAccount.tenant_id == tenant_id, CashAccount.id == account_id
        ).with_for_update()).first()

    def _lock_candidate_shift(self, db: Session, tenant_id, acct: CashAccount, origin_shift_id):
        if acct.type != "TILL":
            return None
        if origin_shift_id is not None:
            sh = db.execute(select(CashShift).where(
                CashShift.tenant_id == tenant_id, CashShift.id == origin_shift_id
            ).with_for_update()).scalar_one_or_none()
            return sh
        # origin berilmasa — hisobning ochiq смена qatorini (bo'lsa) lock qilamiz (sale-vs-close)
        sh = db.execute(select(CashShift).where(
            CashShift.tenant_id == tenant_id, CashShift.cash_account_id == acct.id,
            CashShift.status == CashShiftStatus.OPEN.value
        ).with_for_update()).scalar_one_or_none()
        return sh

    # ── ichki: timestamp / shift ─────────────────────────────────────────────
    def _validate_timestamp(self, device_ts: datetime):
        if device_ts is None:
            raise CashPostingError(CashError.INVALID_TIMESTAMP, "device_occurred_at yo'q")
        # kelajakka juda uzoq (buzuq soat) — INVALID (Case-B EMAS)
        if device_ts > _now() + timedelta(days=1):
            raise CashPostingError(CashError.INVALID_TIMESTAMP, "device vaqti kelajakда (buzuq)")

    def _in_window(self, device_ts: datetime, shift: CashShift) -> bool:
        tol = timedelta(minutes=_TS_TOLERANCE_MIN)
        lo = shift.opened_at - tol
        hi = shift.opened_at + timedelta(hours=_MAX_SHIFT_HOURS) + tol
        return lo <= device_ts <= hi

    def _resolve_shift(self, cmd: PostingCommand, acct: CashAccount, cand: CashShift | None, device_ts):
        # SAFE — har doim OFF_SHIFT, смена yo'q, anomaliya yo'q
        if acct.type == "SAFE":
            return CashPostingKind.OFF_SHIFT.value, None, []
        # TILL
        if cmd.origin_shift_id is None:
            # Case D — TILL: OFF_SHIFT + UNRESOLVED_OFF_SHIFT
            return CashPostingKind.OFF_SHIFT.value, None, ["UNRESOLVED_OFF_SHIFT"]
        if cand is None:
            raise CashPostingError(CashError.SHIFT_NOT_FOUND, "Смена topilmadi")
        if cand.cash_account_id != acct.id:
            raise CashPostingError(CashError.SHIFT_NOT_BELONG_TO_ACCOUNT, "Смена bu hisobniki emas")
        in_win = self._in_window(device_ts, cand)
        if cand.status == CashShiftStatus.OPEN.value:
            if in_win:
                return CashPostingKind.ON_SHIFT.value, cand.id, []            # Case A
            return CashPostingKind.OFF_SHIFT.value, None, ["TIMESTAMP_OUT_OF_WINDOW"]  # Case B
        # CLOSED (yoki CLOSING — lock ostида CLOSED bo'lib qoladi)
        if in_win:
            return CashPostingKind.LATE_SYNC.value, cand.id, ["LATE_SYNC_UNACK"]  # Case C
        return CashPostingKind.OFF_SHIFT.value, None, ["TIMESTAMP_OUT_OF_WINDOW"]  # Case C out-of-window -> Case B

    def _resolve_transfer_leg(self, db: Session, tenant_id, acct: CashAccount, device_ts):
        # Transfer leg smenasi: SAFE -> OFF_SHIFT; TILL -> ochiq смена + in-window bo'lsa ON_SHIFT
        if acct.type == "SAFE":
            return CashPostingKind.OFF_SHIFT.value, None, []
        sh = repo.open_shift_for_account(db, tenant_id, acct.id)
        if sh is not None and self._in_window(device_ts, sh):
            return CashPostingKind.ON_SHIFT.value, sh.id, []
        return CashPostingKind.OFF_SHIFT.value, None, []

    # ── ichki: reversal ──────────────────────────────────────────────────────
    def _validate_reversal(self, db: Session, cmd: PostingCommand):
        orig = db.get(CashLedgerEntry, cmd.reverses_id)
        if orig is None or orig.tenant_id != cmd.tenant_id:
            raise CashPostingError(CashError.INVALID_REVERSAL, "Original topilmadi")
        if orig.id == cmd.reverses_id and cmd.direction == orig.direction:
            raise CashPostingError(CashError.INVALID_REVERSAL, "Reversal qarama-qarshi yo'nalishда bo'lishi kerak")
        if _D(cmd.amount) != _D(orig.amount):
            raise CashPostingError(CashError.INVALID_REVERSAL, "Reversal summasi teng bo'lishi kerak")
        existing = repo.reversal_of(db, cmd.tenant_id, orig.id)
        if existing is not None:
            raise CashPostingError(CashError.ALREADY_REVERSED, "Allaqachon reversal qilingan")

    # ── ichki: build / persist ───────────────────────────────────────────────
    def _new_entry(self, tenant_id, acct, currency, direction, category, amount, source_type,
                   source_id, leg_index, posting_kind, shift_id, device_ts, recv, actor_id,
                   idem_key, *, reverses_id=None, transfer_group_id=None, origin_device_id=None,
                   provenance="NORMAL", recon_reason=None, recon_ref=None) -> CashLedgerEntry:
        return CashLedgerEntry(
            tenant_id=tenant_id, cash_account_id=acct.id, branch_id=acct.branch_id,
            account_type=acct.type, shift_id=shift_id, posting_kind=posting_kind,
            source_type=source_type, source_id=source_id, leg_index=leg_index,
            direction=direction, category=category, amount=_D(amount), currency=currency,
            device_occurred_at=device_ts, server_received_at=recv, recorded_at=recv,
            actor_id=actor_id, idempotency_key=idem_key or str(uuid.uuid4()),
            reverses_id=reverses_id, transfer_group_id=transfer_group_id,
            origin_device_id=origin_device_id, provenance=provenance,
            reconstruction_reason=recon_reason, reconstruction_source_ref=recon_ref,
        )

    def _persist(self, db, emp, cmd, acct, currency, device_ts, recv, posting_kind, shift_id,
                 exc_kinds, override, till_before, till_after, *, commit: bool = True) -> PostingResult:
        entry = self._new_entry(
            cmd.tenant_id, acct, currency, cmd.direction, cmd.category, cmd.amount,
            cmd.source_type, cmd.source_id, cmd.leg_index, posting_kind, shift_id,
            device_ts, recv, getattr(emp, "id", None), cmd.idempotency_key,
            reverses_id=cmd.reverses_id, transfer_group_id=cmd.transfer_group_id,
            origin_device_id=cmd.origin_device_id, provenance=cmd.provenance,
            recon_reason=cmd.reconstruction_reason, recon_ref=cmd.reconstruction_source_ref,
        )
        db.add(entry)
        db.flush()  # entry.id — exception/approval unga ishora qiladi
        for kind in exc_kinds:
            db.add(CashLedgerException(tenant_id=cmd.tenant_id, entry_id=entry.id, kind=kind,
                                       state="OPEN", created_at=recv))
        if override:
            db.add(NegativeCashApproval(
                tenant_id=cmd.tenant_id, entry_id=entry.id, cash_account_id=acct.id,
                direction=CashDirection.OUT.value, account_type="TILL",
                approver_id=getattr(emp, "id", None), reason=cmd.negative_reason or "override",
                amount=_D(cmd.amount), till_balance_before=till_before, till_balance_after=till_after,
                authorized_at=recv))
        if not commit:
            # retrofit/dual-write: chaqiruvchi commit qiladi — biz faqat flush (immediate
            # constraint'lar shu yerда, deferred transfer trigger chaqiruvchi commit'ida).
            db.flush()
        else:
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = repo.get_entry_by_business_key(db, cmd.tenant_id, cmd.source_type,
                                                          cmd.source_id, cmd.leg_index)
                if existing is not None:
                    return self._result_from_entry(existing, IDEMPOTENCY_DUPLICATE)
                raise
        return PostingResult(
            entry_ids=[entry.id], cash_account_id=acct.id, shift_id=shift_id,
            posting_kind=posting_kind, amount=_D(cmd.amount), direction=cmd.direction,
            category=cmd.category, currency=currency, device_occurred_at=device_ts,
            recorded_at=recv, idempotency=IDEMPOTENCY_CREATED, exceptions=list(exc_kinds),
        )

    def _result_from_entry(self, e: CashLedgerEntry, idem: str, transfer: bool = False) -> PostingResult:
        return PostingResult(
            entry_ids=[e.id], cash_account_id=e.cash_account_id, shift_id=e.shift_id,
            posting_kind=e.posting_kind, amount=_D(e.amount),
            direction=("TRANSFER" if transfer else e.direction),
            category=e.category, currency=e.currency, device_occurred_at=e.device_occurred_at,
            recorded_at=e.recorded_at, idempotency=idem, transfer_group_id=e.transfer_group_id,
        )


# yagona instansiya (servislar/adapterlar shu orqali chaqiradi)
cash_posting_service = CashPostingService()
