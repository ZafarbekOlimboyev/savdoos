# -*- coding: utf-8 -*-
"""Phase 1 — SEYF ONBOARDING: ochilish attestatsiyasi va OPERATSION TAYYORLIK.

Shartnoma: `docs/PURCHASE_SETTLEMENT_PHASE1.md` (ega qarorlari B1–B7).

═══ ASOSIY PRINSIP ════════════════════════════════════════════════════════════
SEYF qoldig'i HECH QACHON quyidagilar orqali paydo bo'lmaydi:
  · yashirin balans mutatsiyasi (o'zgaruvchan `balance` ustuni YO'Q — balans HAR DOIM
    `repositories.account_balance` dan HOSIL QILINADI);
  · soxta CASH IN (ochilishning O'Z manba turi bor: `ACCOUNT_OPENING`);
  · taxmin qilingan tarixiy qoldiq (noma'lum → SEYF ISHLAMAYDI, nol DEB OLINMAYDI);
  · sun'iy production tranzaksiyasi.

═══ UCH HOLAT ════════════════════════════════════════════════════════════════
  UNKNOWN     — ochilish yozuvi YO'Q  → SEYF OPERATSION EMAS (fail-closed)
  KNOWN_ZERO  — ega ANIQ «bo'sh» deb attestatsiya qilgan → ledger legi YO'Q
  COUNTED     — sanalgan summa > 0    → AYNAN BITTA o'zgarmas IN legi

⚠️  UNKNOWN ≠ nol. Bu ega qarori (J): legacy do'konda qoldiq noma'lum bo'lsa — BLOCK,
    REVIEW emas. Nol deb qabul qilish do'kon pulini hisobdan «yo'qotardi».

═══ NEGA `provenance='NORMAL'` ═══════════════════════════════════════════════
`RECONSTRUCTION` kodda BITTA narsani bildiradi — T0 gacha bo'lgan legacy tarixning
backfill nusxasi. `preflight.post_backfill_verification` darvozasi 10 ta majburiy
tekshiruv beradi va runtime ochilish legi ulardan 5 tasini yiqitardi
(`row_count_matches`, `in_total_matches`, `deterministic_ids`, `no_ge_t0_backfilled`,
`unexplained_delta_zero`) — istisno parametri esa YO'Q. Darvozani kuchsizlantirish
TAQIQLANGAN, shu bois ochilish o'z manba turi bilan NORMAL yo'ldan yuradi.

Evaziga leg `compare_engine` ning `EXTRA_LEDGER` shoxiga TUSHADI va uni faqat ANIQ
MANBA SHARTNOMASI yopadi (`compare_engine._opening_expected`).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.cash import (
    OPENING_COUNTED,
    OPENING_KNOWN_ZERO,
    CashAccount,
    CashAccountOpening,
    CashCategory,
    CashDirection,
    CashLedgerEntry,
    CashSourceType,
)
from app.services.cash.errors import CashError, CashPostingError

# Holat nomlari (`kind` ustuni bilan AYNI qiymatlar + yozuvsiz holat)
UNKNOWN = "UNKNOWN"
KNOWN_ZERO = OPENING_KNOWN_ZERO
COUNTED = OPENING_COUNTED

# `counted_at` kelajakka nisbatan toleranti — faqat SOAT QIYSHIQLIGI uchun.
_FUTURE_SKEW = timedelta(minutes=5)

_MANAGER_PLUS = {"ega", "administrator", "menejer"}


def _D(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _is_manager_plus(emp) -> bool:
    return getattr(getattr(emp, "role", None), "code", None) in _MANAGER_PLUS


# ── O'QISH: holat va tayyorlik ──────────────────────────────────────────────
def opening_row(db: Session, *, company_id, cash_account_id) -> CashAccountOpening | None:
    return db.execute(select(CashAccountOpening).where(
        CashAccountOpening.tenant_id == company_id,
        CashAccountOpening.cash_account_id == cash_account_id,
    )).scalar_one_or_none()


def opening_state(db: Session, *, company_id, cash_account_id) -> str:
    row = opening_row(db, company_id=company_id, cash_account_id=cash_account_id)
    if row is None:
        return UNKNOWN
    return KNOWN_ZERO if row.kind == OPENING_KNOWN_ZERO else COUNTED


def _opening_consistent(db: Session, row: CashAccountOpening) -> bool:
    """COUNTED yozuvi HAQIQIY leg bilan mos kelishini tekshiradi.

    ⚠️  Buzuq yozuv JIMGINA «tayyor» deb qabul QILINMAYDI: manba qatori bor, legi esa
        yo'q/boshqa summada bo'lsa balans yolg'on bo'lardi."""
    if row.kind == OPENING_KNOWN_ZERO:
        return row.ledger_entry_id is None and _D(row.counted_amount) == 0
    if row.ledger_entry_id is None:
        return False
    e = db.get(CashLedgerEntry, row.ledger_entry_id)
    return bool(
        e is not None
        and e.tenant_id == row.tenant_id
        and e.cash_account_id == row.cash_account_id
        and e.source_type == CashSourceType.ACCOUNT_OPENING.value
        and str(e.source_id) == str(row.id)
        and e.leg_index == 0
        and e.direction == CashDirection.IN.value
        and e.category == CashCategory.ADJUSTMENT.value
        and e.account_type == "SAFE"
        and e.provenance == "NORMAL"
        and _D(e.amount) == _D(row.counted_amount)
    )


def is_operational(db: Session, *, company_id, account: CashAccount) -> bool:
    """SEYF ishlata olinadimi. TILL — HAR DOIM True (bu qoida SEYFga xos).

    MARKAZLASHGAN PREDIKAT: `CashPostingService` va HAMMA custody/sarflash yo'li shuni
    chaqiradi — UI emas. UI SEYFni yashirishi mumkin, lekin kafolat SERVERDA."""
    if getattr(account, "type", None) != "SAFE":
        return True
    row = opening_row(db, company_id=company_id, cash_account_id=account.id)
    if row is None:
        return False
    return _opening_consistent(db, row)


def require_operational(db: Session, *, company_id, account: CashAccount,
                        operation: str | None = None) -> None:
    if is_operational(db, company_id=company_id, account=account):
        return
    raise CashPostingError(
        CashError.SAFE_OPENING_REQUIRED,
        "Seyf ishga tayyor emas: ochilish qoldig'i attestatsiya qilinmagan. "
        "Avval jismoniy sanoqni kiriting (noma'lum qoldiq NOL deb olinmaydi).",
        company_id=company_id, account_id=getattr(account, "id", None), operation=operation)


def _ledger_leg_count(db: Session, *, company_id, cash_account_id) -> int:
    return int(db.execute(select(func.count(CashLedgerEntry.id)).where(
        CashLedgerEntry.tenant_id == company_id,
        CashLedgerEntry.cash_account_id == cash_account_id,
    )).scalar() or 0)


# ── YOZISH: attestatsiya ────────────────────────────────────────────────────
def attest_opening(db: Session, emp, *, account: CashAccount, kind: str, counted_amount,
                   counted_at: datetime, attestation_ref: str, currency: str | None = None,
                   commit: bool = True) -> tuple[CashAccountOpening, str]:
    """SEYF ochilish attestatsiyasi. Qaytaradi `(yozuv, 'created' | 'duplicate')`.

    MANBA + LEDGER LEGI AYNI TRANZAKSIYADA. Ledgerga YAGONA yozuvchi —
    `CashPostingService` (bu yerda `commit=False` bilan chaqiriladi), biz faqat o'z
    manba qatorimizni qo'shamiz.

    ⚠️  `id` OLDIN generatsiya qilinadi: `ledger_entry_id` COUNTED uchun NOT NULL va
        jadval o'zgarmas (UPDATE bloklangan), ya'ni «avval INSERT, keyin UPDATE»
        MUMKIN EMAS. `source_id` esa mantiqiy havola (FK emas — DDL izohi), shu bois
        legni manba qatoridan oldin yozish qonuniy.
    """
    company_id = getattr(emp, "company_id", None)
    if company_id is None:
        raise CashPostingError(CashError.UNAUTHORIZED_OPERATION, "Autentifikatsiya yo'q")
    if account.tenant_id != company_id:
        raise CashPostingError(CashError.TENANT_MISMATCH, "Hisob boshqa tenantniki")

    # 1) RUXSAT — IKKALA shart birga: marshrutdagi `kassa.attest` VA menejer+ roli.
    #    (COUNTED yo'lida `posting._authorize` ham AYNI darvozani qo'yadi — ADJUSTMENT;
    #     KNOWN_ZERO da leg yo'q, shu bois darvoza SHU YERDA ham ANIQ tekshiriladi.)
    if not _is_manager_plus(emp):
        raise CashPostingError(CashError.UNAUTHORIZED_OPERATION,
                               "Ochilish attestatsiyasi uchun menejer+ kerak",
                               company_id=company_id, account_id=account.id)

    # 2) SEYF va faqat SEYF
    if account.type != "SAFE":
        raise CashPostingError(CashError.INVALID_ACCOUNT_TYPE,
                               "Ochilish attestatsiyasi faqat SEYF uchun")
    if account.status == "ARCHIVED":
        raise CashPostingError(CashError.ACCOUNT_ARCHIVED, "Hisob arxivlangan")

    # 3) shakl
    if kind not in (OPENING_KNOWN_ZERO, OPENING_COUNTED):
        raise CashPostingError(CashError.INVALID_INPUT,
                               "kind faqat KNOWN_ZERO yoki COUNTED bo'ladi")
    amount = _D(counted_amount)
    if amount < 0:
        raise CashPostingError(CashError.INVALID_INPUT, "Summa manfiy bo'lmaydi")
    if (kind == OPENING_COUNTED) != (amount > 0):
        raise CashPostingError(
            CashError.INVALID_INPUT,
            "KNOWN_ZERO aynan 0 ni, COUNTED esa musbat summani talab qiladi")
    ref = (attestation_ref or "").strip()
    if not ref:
        raise CashPostingError(CashError.INVALID_INPUT, "Attestatsiya havolasi majburiy")
    cur = (currency or account.currency)
    if cur != account.currency:
        raise CashPostingError(CashError.CURRENCY_MISMATCH,
                               f"Valyuta mos emas: {cur} != {account.currency}")

    # 4) VAQT — hisob hodisasining vaqti JISMONIY SANOQ vaqti (§8).
    #    ⚠️  Server vaqtiga JIMGINA tushmaydi: sanoq vaqti noma'lum bo'lsa bu NOANIQLIK
    #        va u yashirilmaydi.
    at = _aware(counted_at)
    if at is None:
        raise CashPostingError(CashError.INVALID_TIMESTAMP,
                               "Sanoq vaqti (counted_at) majburiy")
    now = datetime.now(timezone.utc)
    if at > now + _FUTURE_SKEW:
        raise CashPostingError(CashError.INVALID_TIMESTAMP, "Sanoq vaqti KELAJAKDA")
    created = _aware(getattr(account, "created_at", None))
    if created is not None and at < created:
        # Jismoniy pul eskiroq bo'lishi MUMKIN, lekin SHU HISOBNI ochgan sanoq hisob
        # mavjud bo'lgandan keyin bajariladi. Bu sana to'qishni ham, ochilishni T0 dan
        # oldingi oynaga suqishni ham to'sadi.
        raise CashPostingError(CashError.INVALID_TIMESTAMP,
                               "Sanoq vaqti hisob yaratilgan vaqtdan OLDIN")

    # 5) HISOBNI QULFLASH — parallel ikki attestatsiya seriyalanadi
    db.execute(select(CashAccount.id).where(
        CashAccount.tenant_id == company_id, CashAccount.id == account.id
    ).with_for_update()).first()

    # 6) MAVJUD yozuv: ayni payload -> idempotent; boshqa payload -> 409
    existing = opening_row(db, company_id=company_id, cash_account_id=account.id)
    if existing is not None:
        if _same_payload(existing, kind, amount, cur, ref, at):
            return existing, "duplicate"
        raise CashPostingError(
            CashError.SAFE_OPENING_CONFLICT,
            "Bu seyf uchun ochilish ALLAQACHON attestatsiya qilingan va mazmuni boshqa. "
            "Ochilishni tahrirlash mumkin emas.",
            company_id=company_id, account_id=account.id)

    # 7) TARIXI bor, ochilishi yo'q -> fail-closed (retroaktiv «nol» YO'Q)
    if _ledger_leg_count(db, company_id=company_id, cash_account_id=account.id) > 0:
        raise CashPostingError(
            CashError.SAFE_OPENING_BLOCKED_BY_HISTORY,
            "Seyfda kassa harakati bor, ochilish yozuvi esa yo'q — retroaktiv ochilish "
            "mavjud tarixni qayta talqin qilardi. Alohida migratsiya qarori kerak.",
            company_id=company_id, account_id=account.id)

    # 8) COUNTED -> ledger legi (YAGONA yozuvchi orqali); KNOWN_ZERO -> leg YO'Q
    opening_id = uuid.uuid4()
    entry_id = None
    if kind == OPENING_COUNTED:
        from app.services.cash.commands import PostingCommand
        from app.services.cash.posting import cash_posting_service
        res = cash_posting_service.post(db, emp, PostingCommand(
            cash_account_id=account.id,
            source_type=CashSourceType.ACCOUNT_OPENING.value,
            source_id=opening_id,
            leg_index=0,
            direction=CashDirection.IN.value,
            category=CashCategory.ADJUSTMENT.value,
            amount=amount,
            currency=cur,
            device_occurred_at=at,
            idempotency_key=f"account-opening:{opening_id}",
            tenant_id=company_id,
        ), commit=False)
        entry_id = res.entry_ids[0]

    row = CashAccountOpening(
        id=opening_id, tenant_id=company_id, cash_account_id=account.id,
        account_type=account.type, kind=kind, counted_amount=amount, currency=cur,
        counted_at=at, attested_by=getattr(emp, "id", None), attestation_ref=ref,
        ledger_entry_id=entry_id, created_at=now,
    )
    db.add(row)
    try:
        db.flush()
        if commit:
            db.commit()
    except IntegrityError:
        db.rollback()
        again = opening_row(db, company_id=company_id, cash_account_id=account.id)
        if again is not None and _same_payload(again, kind, amount, cur, ref, at):
            return again, "duplicate"
        raise CashPostingError(
            CashError.SAFE_OPENING_CONFLICT,
            "Ochilish yozib bo'lmadi — bu seyf uchun ochilish allaqachon mavjud.",
            company_id=company_id, account_id=account.id)
    return row, "created"


def _same_payload(row: CashAccountOpening, kind, amount, currency, ref, at) -> bool:
    """«Ayni so'rov» = MODDIY maydonlarning TO'LIQ tengligi (`PHASE1.md` §2.2).

    ⚠️  Farq bo'lsa bu TAKROR emas — boshqa amal. U yozilmaydi va «ok» ham deyilmaydi
        (`IDEMPOTENCY_KEY_REUSED` naqshidagi ayni dars)."""
    return (row.kind == kind
            and _D(row.counted_amount) == _D(amount)
            and row.currency == currency
            and (row.attestation_ref or "") == ref
            and _aware(row.counted_at) == _aware(at))


# ── O'QISH: balans ko'rinishi (`GET /safes/{id}/balance`) ───────────────────
def balance_view(db: Session, *, company_id, account: CashAccount) -> dict:
    """SEYF identiteti + ochilish holati + HOSIL QILINGAN balans.

    ⚠️  UNKNOWN da `balance` — `None` (0 EMAS). Nol raqam «seyf bo'sh» degan YOLG'ON
        ma'no berardi; sabab `operational=false` + `opening.state` da ko'rinadi."""
    from app.services.cash import repositories as repo

    row = opening_row(db, company_id=company_id, cash_account_id=account.id)
    state = UNKNOWN if row is None else (KNOWN_ZERO if row.kind == OPENING_KNOWN_ZERO
                                         else COUNTED)
    operational = is_operational(db, company_id=company_id, account=account)
    opening = {"state": state, "amount": None, "counted_at": None,
               "attested_by": None, "attestation_ref": None}
    if row is not None:
        opening.update(
            amount=(str(_D(row.counted_amount)) if row.kind == OPENING_COUNTED else None),
            counted_at=_aware(row.counted_at),
            attested_by=str(row.attested_by) if row.attested_by else None,
            attestation_ref=row.attestation_ref,
        )
    return {
        "id": str(account.id), "branch_id": str(account.branch_id),
        "label": account.label, "currency": account.currency, "status": account.status,
        "operational": operational,
        "opening": opening,
        # UNKNOWN -> None: yolg'on «0» KO'RSATILMAYDI
        "balance": (None if state == UNKNOWN
                    else str(repo.account_balance(db, company_id, account.id))),
        "as_of": datetime.now(timezone.utc),
    }
