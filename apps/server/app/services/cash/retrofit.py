"""Phase 2b — mavjud biznes-servislarni CashPostingService'ga ulash (dual-write).

Har hook GUARD ostida: cash quyi tizimi FAQAT Postgres (schema/trigger) — SQLite (dev/test)'da
va cash hisobi HALI xaritalanmagan filialda NO-OP (legacy oqim davom etadi, sinmaydi).
Aktiv bo'lганда: cash leg chaqiruvchining O'SHA tranzaksiyasiga qo'shiladi (commit=False) —
source + ledger ATOMIK (kontrakt §14). ledger cash.cash_ledger_entries'ga FAQAT CashPostingService
orqali yoziladi (to'g'ridan-to'g'ri yozuv yo'q).

MUHIM: dual-write смена ochilishidan (opening float) boshlab aktiv bo'lса, ledger balansи legacy
kassa balansига TENG bo'ladi — shунda OUT-sufficiency to'g'ri ishlaydi. Xaritalanmagan/eski ochiq
смена — cash.shift yo'q -> sotuv OFF_SHIFT (anomaliya, migratsiya hал qiladi).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.cash import (
    CashAccount,
    CashCategory,
    CashDirection,
    CashShift,
    CashSourceType,
)
from app.services.cash import adapters
from app.services.cash import mode as _mode
from app.services.cash import repositories as repo
from app.services.cash import till_identity as _ti
from app.services.cash import lifecycle as _lifecycle  # noqa: F401  (test/keyingi faza uchun)

_CASH_READY: dict = {}   # bind-url -> bool (schema mavjudligi cache)


def _now():
    return datetime.now(timezone.utc)


def cash_enabled(db: Session) -> bool:
    """Postgres VA `cash` schema mavjud bo'lsa True (INFRA tayyorligi — rejimдан qat'i nazar)."""
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    key = str(bind.url)
    if key not in _CASH_READY:
        row = db.execute(text(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name='cash'")).first()
        _CASH_READY[key] = row is not None
    return _CASH_READY[key]


def dual_write_enabled(db: Session) -> bool:
    """Dual-write FAOL: infra tayyor (Postgres+cash schema) VA rejim LEGACY_ONLY EMAS (Phase 2 gate).
    SQLite/schema yo'q -> False (guarded no-op). LEGACY_ONLY -> False (ledger butunlay o'chiq).
    SHADOW/PRIMARY -> True. Barcha posting hook'lari SHU guard orqali o'tadi."""
    return cash_enabled(db) and _mode.dual_write_active()


def resolve_till(db: Session, tenant_id, branch_id, *, terminal_id=None,
                 allow_single_checkout: bool = True) -> CashAccount | None:
    """FIZIK drawer resolver (GUARDED). Bir branch KO'P TILL'ga ega bo'la oladi (real model):
      0 TILL              -> None (xaritalanmagan -> dual-write skip)
      1 TILL              -> o'sha (yagona fizik checkout -> aniq)
      >1 TILL + terminal  -> terminal-bog'langan TILL (NOYOB moslik), aks holда None
      >1 TILL + terminal yo'q -> None (drawer noaniq)
    HECH QACHON ko'p-TILL branch'да ixtiyoriy .first() TANLAMAYDI (silent branch-default fallback YO'Q).
    None qaytса hook guarded no-op qiladi (comparison'да OFF_SHIFT/REVIEW bilan ko'rinadi)."""
    acc, _why = _ti.resolve_till_exact(db, tenant_id, branch_id, terminal_id=terminal_id,
                                       allow_single_checkout=allow_single_checkout)
    return acc


def resolve_safe(db: Session, tenant_id, branch_id) -> CashAccount | None:
    return repo.find_account(db, tenant_id, branch_id, "SAFE")


def resolve_till_id(db: Session, tenant_id, branch_id, *, terminal_id=None,
                    allow_single_checkout: bool = True):
    """AUDIT uchun fizik TILL id (Sale/Shift.till_id). GUARDED: cash_enabled (Postgres + cash schema)
    bo'lsa resolve_till (exact, branch-default YO'Q), aks holда None (SQLite/cash-disabled -> noma'lum,
    TAXMIN QILINMAYDI). Ko'p-TILL branch'да terminal moslik bo'lmasa ham None (jimgina tanlamaydi)."""
    if not cash_enabled(db):
        return None
    acc = resolve_till(db, tenant_id, branch_id, terminal_id=terminal_id,
                       allow_single_checkout=allow_single_checkout)
    return acc.id if acc is not None else None


def _open_cash_shift_id(db: Session, tenant_id, till: CashAccount):
    sh = repo.open_shift_for_account(db, tenant_id, till.id)
    return sh.id if sh is not None else None


def _exact_or_resolve(db: Session, tenant_id, branch_id, till_id, terminal_id):
    """AYNAN till_id (validatsiyalangan: shu tenant, ACTIVE TILL, shu filial) USTUN; berilmasa
    eski resolve (terminal -> exact; aks holda guarded). Bitta joyda — split-brain qaytmasin."""
    if till_id is not None:
        acc, _err = _ti.get_till(db, tenant_id, till_id)
        if acc is not None and str(acc.branch_id) == str(branch_id):
            return acc
    return resolve_till(db, tenant_id, branch_id, terminal_id=terminal_id)


# ── Shift lifecycle (dual-write) ─────────────────────────────────────────────
def on_shift_open(db: Session, emp, *, branch_id, legacy_shift_id, opening_cash=0,
                  terminal_id=None, till_id=None) -> CashShift | None:
    """Legacy смена ochilганда cash.shift ochadi (+ opening float). commit=False.

    §4: till_id (Shift.till_id — endpoint AYNAN aniqlagan drawer) berilsa cash.shift AYNAN o'shanda
    ochiladi. QAYTA RESOLVE QILINMAYDI: aks holda ko'p-TILL filialda terminal bo'lmasa `None`
    chiqib, legacy smena ochilgani holda cash.shift UMUMAN yaratilmasdi — ya'ni butun smenada
    ledger ankori bo'lmasdi. terminal_id eski (till_id'siz) yo'l uchun qoladi."""
    if not dual_write_enabled(db):
        return None
    tenant = emp.company_id
    till = _exact_or_resolve(db, tenant, branch_id, till_id, terminal_id)
    if till is None:
        return None
    # §19 topilma (MAJOR): cash sxema TILL'ga BITTA ochiq smena beradi (sh_one_open_per_account); legacy
    # esa kassir-boshiga (bir filialда bir necha kassir mumkin). SHADOW rejimда dual-write legacy'ni HECH
    # QACHON SINDIRMASLIGI SHART. Ikkinchi kassir shu filialда smena ochsa, cash.shift yarata olmaymiz —
    # LEKIN legacy smena ochilishi DAVOM etsin (anomaliya comparison'да OFF_SHIFT/REVIEW bilan ko'rinadi).
    #   fast path: TILL'да allaqачон ochiq cash.shift bo'lса -> skip.
    if repo.open_shift_for_account(db, tenant, till.id) is not None:
        return None
    # konkurrent poyga (ikki kassir bir vaqtда): SAVEPOINT izolyatsiyasi — cash unique buzilса FAQAT
    # savepoint qaytadi, chaqiruvchi (legacy) tranzaksiyasi BUZILMAYDI.
    from sqlalchemy.exc import IntegrityError as _IE
    # cash.shift id == LEGACY shift id (backfill reconstruct_shifts ham legacy id ishlatadi -> runtime va
    # backfill IZCHIL; shadow_compare va T0 chegarasi shu bir xil id orqali trivial mos keladi).
    try:
        with db.begin_nested():
            sh = CashShift(id=legacy_shift_id, tenant_id=tenant, cash_account_id=till.id,
                           branch_id=till.branch_id, account_type="TILL", status="OPEN",
                           opened_at=_now(), opened_by=getattr(emp, "id", None), version=1)
            db.add(sh)
            db.flush()
            if float(opening_cash or 0) > 0:
                adapters.opening_float(db, emp, cash_account_id=till.id, source_id=legacy_shift_id,
                                       amount=opening_cash, origin_shift_id=sh.id, commit=False)
    except _IE:
        return None   # boshqa kassir bir vaqtда shu TILL'ga ochiq cash.shift oldi -> legacy'ni sindirmaymiz
    return sh


def on_shift_close(db: Session, emp, *, branch_id, counted_cash=0, terminal_id=None, till_id=None):
    """Legacy смена yopilганда cash.shift ni yopadi + reconciliation snapshot. commit=False.
    §4: till_id berilsa AYNAN o'sha kassa yopiladi (ochilishdagi bilan bir xil ankor)."""
    if not dual_write_enabled(db):
        return None
    tenant = emp.company_id
    till = _exact_or_resolve(db, tenant, branch_id, till_id, terminal_id)
    if till is None:
        return None
    sh = repo.open_shift_for_account(db, tenant, till.id)
    if sh is None:
        return None
    expected = repo.shift_expected_cash(db, tenant, sh.id)
    now = _now()
    sh.status = "CLOSED"
    sh.closed_at = now
    sh.closed_by = getattr(emp, "id", None)
    rec = _lifecycle._new_recon(db, tenant, shift_id=sh.id, snapshot=expected,
                                counted=_lifecycle._D(counted_cash),
                                diff=_lifecycle._D(counted_cash) - expected, now=now)
    db.add(rec)
    db.flush()
    return rec


# ── Posting hooks (dual-write) — hammasi guarded + commit=False ─────────────
def _shift_ctx(db, emp, branch_id, *, terminal_id=None, till_id=None):
    """(till, cash_shift_id) — dual-write faol bo'lsa; aks holда (None, None).

    §4 SPLIT-BRAIN TUZATISH: smena AYNAN kassaga bog'langan bo'lsa (Shift.till_id), ledger AYNAN
    o'shani ishlatadi — QAYTA RESOLVE QILMAYDI. Ilgari hook (tenant, branch, terminal_id) dan
    MUSTAQIL resolve qilardi: guard `shift.till_id` ni tasdiqlagan bo'lsa-da, hook boshqa javob
    (yoki ko'p-TILL filialda terminal bo'lmasa — HECH QANDAY javob) olishi mumkin edi, natijada
    legacy yozuv commit bo'lib, ledger legi JIMGINA TUSHIB QOLARDI.
    till_id berilmasa — eski yo'l (terminal -> exact; aks holda guarded skip)."""
    if not dual_write_enabled(db):
        return None, None
    till = None
    if till_id is not None:
        acc, _err = _ti.get_till(db, emp.company_id, till_id)
        if acc is not None and str(acc.branch_id) == str(branch_id):
            till = acc
    if till is None:
        till = resolve_till(db, emp.company_id, branch_id, terminal_id=terminal_id)
    if till is None:
        return None, None
    return till, _open_cash_shift_id(db, emp.company_id, till)


def on_cash_sale(db, emp, *, branch_id, sale_id, cash_amount, device_occurred_at=None,
                 terminal_id=None, till_id=None):
    """Sotuvning NAQD qismi -> IN·SALE (kartа/QR qismi ledger'ga tegmaydi).

    AUDIT: till_id berilса (Sale.till_id — server-authoritative fizik drawer) ledger AYNAN o'sha TILL'ga
    yoziladi (account_id == Sale.till_id). Aks holда (eski yo'l) terminal'дан resolve. Ikkalasi ham
    guarded: dual-write o'chiq / xaritalanmagan / noto'g'ri TILL -> no-op (jimgina noma'lum TILL'ga YO'Q)."""
    if float(cash_amount or 0) <= 0:
        return None
    if not dual_write_enabled(db):
        return None
    if till_id is not None:
        till, _err = _ti.get_till(db, emp.company_id, till_id)   # SHU tenant ACTIVE TILL bo'lishi SHART
        if till is None:
            return None
        shift_id = _open_cash_shift_id(db, emp.company_id, till)
    else:
        till, shift_id = _shift_ctx(db, emp, branch_id, terminal_id=terminal_id)
    if till is None:
        return None
    return adapters.cash_sale(db, emp, cash_account_id=till.id, source_id=sale_id,
                              amount=cash_amount, origin_shift_id=shift_id,
                              device_occurred_at=device_occurred_at, commit=False)


def on_cash_refund(db, emp, *, branch_id, return_id, cash_amount, till_id=None):
    """NAQD qaytarish -> OUT·REFUND. AUDIT: till_id berilса (Return.till_id — refund'ni bajarган fizik
    drawer, asl sale TILL'дан FARQ mumkin) ledger AYNAN o'sha TILL'дан chiqadi; aks holда branch resolve."""
    if float(cash_amount or 0) <= 0:
        return None
    if not dual_write_enabled(db):
        return None
    if till_id is not None:
        till, _err = _ti.get_till(db, emp.company_id, till_id)
        if till is None:
            return None
        shift_id = _open_cash_shift_id(db, emp.company_id, till)
    else:
        till, shift_id = _shift_ctx(db, emp, branch_id)
    if till is None:
        return None
    return adapters.cash_refund(db, emp, cash_account_id=till.id, source_id=return_id,
                                amount=cash_amount, origin_shift_id=shift_id, commit=False)


def on_debt_payment(db, emp, *, branch_id, payment_id, cash_amount, till_id=None):
    """§4: till_id (smenaning AYNAN kassasi) berilsa ledger AYNAN o'shanga yozadi — QAYTA
    RESOLVE QILMAYDI. Aks holda ko'p-TILL filialda hook `None` olib, legacy yozuv commit
    bo'lgani holda ledger legi JIMGINA tushib qolardi."""
    if float(cash_amount or 0) <= 0:
        return None
    till, shift_id = _shift_ctx(db, emp, branch_id, till_id=till_id)
    if till is None:
        return None
    return adapters.debt_payment(db, emp, cash_account_id=till.id, source_id=payment_id,
                                 amount=cash_amount, origin_shift_id=shift_id, commit=False)


def on_supplier_payment(db, emp, *, branch_id, payment_id, cash_amount, cash_account_id=None):
    if float(cash_amount or 0) <= 0:
        return None
    till, shift_id = _explicit_ctx(db, emp, branch_id, cash_account_id=cash_account_id)
    if till is None:
        return None
    return adapters.supplier_payment(db, emp, cash_account_id=till.id, source_id=payment_id,
                                     amount=cash_amount, origin_shift_id=shift_id, commit=False)


def _explicit_ctx(db, emp, branch_id, *, cash_account_id=None, terminal_id=None):
    """(account, cash_shift_id) — EXPLICIT hisob berilgan bo'lsa AYNAN o'sha ishlatiladi
    (TAXMIN YO'Q); aks holda eski `_shift_ctx` (pre-T0 legacy moslik)."""
    if cash_account_id is not None:
        if not dual_write_enabled(db):
            return None, None
        from app.models.cash import CashAccount as _CA
        acc = db.get(_CA, cash_account_id)
        if acc is None or str(acc.tenant_id) != str(emp.company_id) or str(acc.status) != "ACTIVE":
            return None, None
        return acc, _open_cash_shift_id(db, emp.company_id, acc)
    return _shift_ctx(db, emp, branch_id, terminal_id=terminal_id)


def on_cash_purchase(db, emp, *, branch_id, purchase_id, cash_amount, cash_account_id=None):
    """XARID NAQD to'lansa -> OUT·PURCHASE_OUT. Bu — asosiy off-ledger teshigini yopadi (§07)."""
    if float(cash_amount or 0) <= 0:
        return None
    till, shift_id = _explicit_ctx(db, emp, branch_id, cash_account_id=cash_account_id)
    if till is None:
        return None
    return adapters.cash_purchase(db, emp, cash_account_id=till.id, source_id=purchase_id,
                                  amount=cash_amount, origin_shift_id=shift_id, commit=False)


def on_purchase_return(db, emp, *, branch_id, purchase_id, purchase_return_id, cash_amount,
                       cash_account_id=None):
    """NAQD xarid qaytarilsa (received xarid kamaytirish/bekor) -> IN·PURCHASE_RETURN.
    source_id = PurchaseReturn HODISASI id'si (asl purchase_id EMAS) — create leg'i bilan
    to'qnashmaydi, bir xariddan ko'p qaytarish mustaqil ([[PURCHASE_RETURN_identity]]).

    FAQAT create'да HAQIQATAN OUT·PURCHASE_OUT post qilingan xarid uchun qaytaradi: aks holда
    (mobil `receiving` naqd xaridi on_cash_purchase CHAQIRMAYDI; yoki parallel-run'да cash
    aktivlashuvidan OLDIN yaratilган xarid) mos OUT leg yo'q -> qaytarish PHANTOM naqd IN
    yaratardi. OUT leg bo'lmasa -> qaytariladigan naqd yo'q -> skip (kassa buzilmaydi)."""
    if float(cash_amount or 0) <= 0:
        return None
    till, shift_id = _explicit_ctx(db, emp, branch_id, cash_account_id=cash_account_id)
    if till is None:
        return None
    # Create'даги OUT·PURCHASE_OUT (PURCHASE·purchase_id·0) mavjudligini tekshir — reversal EMAS,
    # faqat haqiqatан chiqqan naqdni qaytaramiz (kontrakt: qaytarish OUT'ning aksi bo'lсин).
    orig = repo.get_entry_by_business_key(db, emp.company_id, CashSourceType.PURCHASE.value, purchase_id, 0)
    if orig is None:
        return None
    return adapters.purchase_return(db, emp, cash_account_id=till.id, source_id=purchase_return_id,
                                    amount=cash_amount, origin_shift_id=shift_id, commit=False)


def on_cash_purchase_increase(db, emp, *, branch_id, purchase_id, extra_amount,
                              cash_account_id=None):
    """NAQD (received) xarid create'даги OUT·PURCHASE_OUT (leg-0)'дан KEYIN summasi OSHIRILса, faqat
    QO'SHIMCHA fizik naqd chiqishini yozadi -> OUT·PURCHASE_OUT. Asl leg-0'ни O'ZGARTIRMAYDI (immutable):
    source_type=PURCHASE, source_id=purchase_id (asl bilan bir xil), leg_index=KEYINGI bo'sh (>=1) —
    cle_uq_business leg-0 bilan TO'QNASHMAYDI, append-only. Original xaridni IKKI marta hisoblamaydi
    (leg-0 asl summada qoladi; bu leg faqat DELTA'ni tutadi).

    Gate (on_purchase_return bilan simmetrik): asl OUT·PURCHASE_OUT (leg-0) MAVJUD bo'lса post qiladi;
    aks holда (mobil receiving naqd xaridi leg-0 yozmaган, yoki parallel-run'да cash aktivlashuvidan
    OLDIN yaratilган xarid) SKIP — backfill current_total (oshirilган summani O'Z ICHIGA olgan) orqali
    net'ni tiklaydi, shu bois phantom qo'shimcha OUT yozmaymiz."""
    if float(extra_amount or 0) <= 0:
        return None
    till, shift_id = _explicit_ctx(db, emp, branch_id, cash_account_id=cash_account_id)
    if till is None:
        return None
    orig = repo.get_entry_by_business_key(db, emp.company_id, CashSourceType.PURCHASE.value, purchase_id, 0)
    if orig is None:
        return None
    next_idx = repo.next_leg_index(db, emp.company_id, CashSourceType.PURCHASE.value, purchase_id)
    return adapters.cash_purchase(db, emp, cash_account_id=till.id, source_id=purchase_id,
                                  amount=extra_amount, origin_shift_id=shift_id, leg_index=next_idx,
                                  commit=False)


# CashMovement turlari (legacy) -> ledger. payout ("Naqd topshirish") — MANUAL kassa drain:
# OUT·CASH_OUT (collection/inkassa bilan bir buket; source_id=movement.id noyob -> identity to'qnashmaydi).
# DIQQAT: refund/supplier/debt SOYA payout/payin'lari BU YO'LDAN o'tmaydi (ular biznes-endpoint'да
# to'g'ridan-to'g'ri CashMovement sifatida yoziladi, on_cash_op CHAQIRILMAYDI) -> ikki marta post yo'q.
_CASHOP_MAP = {
    "payin": ("manual_cash_in",),         # IN·CASH_IN
    "payout": ("manual_cash_out",),        # OUT·CASH_OUT — manual naqd topshirish (kassa drain)
    "expense": ("expense",),               # OUT·EXPENSE
    # DIQQAT: "collection" (inkassa) bu yerda YO'Q — u TILL->SAFE JUFT TRANSFER (on_cash_collection).
    # Ilgari `manual_cash_out` edi: bir oyoqli OUT, ya'ni seyfga o'tgan naqd LEDGER'DAN YO'QOLARDI.
}


def on_cash_collection(db, emp, *, from_till_id, to_safe_id, amount, movement_id, commit=False):
    """§4 INKASSA = TILL -> SAFE ICHKI TRANSFER (ikki oyoq, bitta transfer_group).

    Naqd do'kon custody'sidan CHIQMAYDI — u shunchaki kassadan seyfga ko'chadi. Shu bois bir oyoqli
    OUT·CASH_OUT MOLIYAVIY JIHATDAN NOTO'G'RI edi (kompaniya jami fizik naqdi kamayib ketardi).
    Ikkala oyoq: bir xil tenant/filial/valyuta/summa, bir xil transfer_group, immutable, idempotent
    (source_id = CashMovement.id -> qayta yuborishда dublikat yozilmaydi)."""
    if not cash_enabled(db) or float(amount or 0) <= 0:
        return None
    if from_till_id is None or to_safe_id is None:
        return None                 # pre-T0 legacy (till/safe yo'q) -> guarded no-op, TAXMIN YO'Q
    return adapters.transfer(db, emp, from_account_id=from_till_id, to_account_id=to_safe_id,
                        amount=amount, source_id=movement_id, commit=commit)


def on_bank_deposit(db, emp, *, from_safe_id, amount, movement_id, commit=False):
    """SAFE -> BANK: YAGONA OUT·BANK_DEPOSIT (transfer header YO'Q — pul kompaniya fizik
    custody'sidan HAQIQATAN chiqadi). Soxta "BANK" cash account YARATILMAYDI."""
    if not cash_enabled(db) or float(amount or 0) <= 0:
        return None
    return adapters.bank_deposit(db, emp, cash_account_id=from_safe_id, source_id=movement_id,
                            amount=amount, commit=commit)


def on_cash_op(db, emp, *, branch_id, kind, amount, movement_id, terminal_id=None, till_id=None):
    """Legacy CashMovement (payin/payout/expense/collection) -> mos ledger legи. terminal_id (smena
    terminal_id) -> ko'p-TILL branch'да EXACT fizik drawer."""
    fn = {"payin": adapters.manual_cash_in, "payout": adapters.manual_cash_out,
          "expense": adapters.expense, "collection": adapters.manual_cash_out}.get(kind)
    if fn is None or float(amount or 0) <= 0:
        return None
    till, shift_id = _shift_ctx(db, emp, branch_id, terminal_id=terminal_id, till_id=till_id)
    if till is None:
        return None
    return fn(db, emp, cash_account_id=till.id, source_id=movement_id, amount=amount,
             origin_shift_id=shift_id, commit=False)
