# -*- coding: utf-8 -*-
"""Cash — TENANT TURI va ONBOARDING HOLATI (fresh vs legacy).

═══ IKKI YO'L, ARALASHTIRILMAYDI ════════════════════════════════════════════

  LEGACY / MIGRATION tenant — YANGI ledger arxitekturasidan OLDIN yaratilgan. Naqd tarixi
      bo'lishi mumkin, uning drawer identity'si dalilsiz bo'lishi mumkin (HISTORICAL_TILL_UNKNOWN).
      Yo'l: discover -> provision -> readiness -> T0 -> backfill -> verify (migration marosimi).

  FRESH / LEDGER-NATIVE tenant — YANGI arxitektura ishga tushgandan KEYIN yaratilgan. Legacy naqd
      tarixi YO'Q, shu bois backfill ham, tarixiy TILL rekonstruksiyasi ham, T0 marosimi ham
      KERAK EMAS. U BIRINCHI fizik naqd hodisasidanoq aniq custody bilan ishlaydi.

═══ AJRATISH: TAXMIN EMAS, ANIQ HOLAT ══════════════════════════════════════
Tenant turi tranzaksiya sonidan TAXMIN QILINMAYDI (bo'sh legacy tenant ham 0 ta qatorli bo'lishi
mumkin). Manba — kompaniya YARATILISHIDA yoziladigan ANIQ bayroq:

    Setting(company_id, branch_id=NULL, key='cash').value = {
        "ledger_native": true,          # FRESH: legacy naqd tarixi YO'Q (o'zgarmas fakt)
        "onboarded_at":  "<ISO>",       # qachon shu yo'lga kirgani (audit)
        "cutover_at":    "<ISO>",       # = onboarded_at -> post-T0 gardlar BIRINCHI daqiqadan FAOL
    }

`cutover_at` ni onboarding lahzasiga qo'yish ATAYLAB: u YAGONA per-company avtoritet kalitidir
(`cutover.cutover_reached`), va uni o'rnatish FRESH tenant uchun HECH QANDAY tarixni "kesib
o'tmaydi" — kesiladigan tarix YO'Q. Natijada fresh tenant HECH QACHON pre-T0 moslik
fallback'lariga tayanmaydi: kassa TAXMIN QILINMAYDI, har naqd hodisa AYNAN TILL/SAFE talab qiladi.

DIQQAT: `ledger_native` LEGACY tenantga HECH QACHON qo'yilmaydi — u yerda backfill/attestatsiya
hali ma'noga ega. Bu bayroq faqat yangi yaratilgan kompaniyaga yoziladi.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

CASH_SETTING_KEY = "cash"

# Onboarding holatlari (kuzatiladigan ma'lumotdan HOSIL qilinadi — alohida holat mashinasi saqlanmaydi,
# shu bois u haqiqat bilan hech qachon ajralib ketmaydi).
COMPANY_CREATED = "COMPANY_CREATED"          # kompaniya bor, filial yo'q (amalda bo'lmaydi — F01 avto)
CASH_SETUP_REQUIRED = "CASH_SETUP_REQUIRED"  # naqd bilan ishlaydigan filialda ACTIVE TILL YO'Q
POS_READY = "POS_READY"                      # kamida bitta ACTIVE TILL — POS ishlashi mumkin


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cash_setting(db: Session, company_id):
    from app.models.settings import Setting
    return (db.query(Setting)
            .filter(Setting.company_id == company_id, Setting.key == CASH_SETTING_KEY,
                    Setting.branch_id.is_(None))
            .first())


def cash_config(db: Session, company_id) -> dict:
    row = _cash_setting(db, company_id)
    return ((row.value if row else None) or {})


def is_ledger_native(db: Session, company_id) -> bool:
    """FRESH (ledger-native) tenantmi. ANIQ bayroq — taxmin YO'Q."""
    return bool(cash_config(db, company_id).get("ledger_native") is True)


def mark_ledger_native(db: Session, company_id, *, at: datetime | None = None) -> dict:
    """Kompaniya YARATILISHIDA chaqiriladi: fresh tenant sifatida belgilaydi va cutover_at ni
    SHU lahzaga qo'yadi. commit QILMAYDI — chaqiruvchi tranzaksiyasida qoladi.

    IDEMPOTENT: mavjud `cash` Setting bo'lsa va unda allaqachon cutover_at bo'lsa TEGILMAYDI
    (legacy tenantning T0'sini tasodifan qayta yozmaslik uchun)."""
    from app.models.settings import Setting
    stamp = (at or datetime.now(timezone.utc))
    iso = stamp.isoformat() if isinstance(stamp, datetime) else str(stamp)
    row = _cash_setting(db, company_id)
    if row is not None:
        # HIMOYA: `cash` Setting ALLAQACHON mavjud bo'lsa — bu YANGI kompaniya EMAS (yangi
        # kompaniyada bunday qator bo'lishi mumkin emas). Legacy/migration tenantni tasodifan
        # "ledger-native" deb belgilab, uning backfill/attestatsiya yo'lini buzib qo'ymaymiz.
        # Idempotentlik: mavjud qiymat O'ZGARTIRILMASDAN qaytariladi.
        return dict(row.value or {})
    val = {"ledger_native": True, "onboarded_at": iso, "cutover_at": iso}
    db.add(Setting(company_id=company_id, branch_id=None, key=CASH_SETTING_KEY, value=val))
    return val


# ── Onboarding holati (Manager UI uchun) ────────────────────────────────────
def branch_cash_state(db: Session, company_id, branch_id) -> dict:
    """Bitta filialning naqd sozlanish holati. SOXTA/placeholder TILL YARATILMAYDI —
    faqat mavjud holat qaytariladi."""
    from app.models.cash import CashAccount

    def _n(kind):
        return int(db.query(CashAccount).filter(
            CashAccount.tenant_id == company_id, CashAccount.branch_id == branch_id,
            CashAccount.type == kind, CashAccount.status == "ACTIVE").count())

    tills, safes = _n("TILL"), _n("SAFE")
    return {"branch_id": str(branch_id), "active_tills": tills, "active_safes": safes,
            "state": (POS_READY if tills else CASH_SETUP_REQUIRED),
            "can_open_cash_shift": tills > 0,
            # §14: SAFE'siz inkassa MUMKIN EMAS — UI uni yashirsin/o'chirsin, jimgina bir oyoqli
            # OUT yozilmasin. SAFE MAJBURIY EMAS: u faqat inkassa uchun kerak.
            "collection_available": safes > 0}


def onboarding_state(db: Session, company_id) -> dict:
    """Kompaniya darajasidagi onboarding holati — Manager sozlash ekrani uchun."""
    from app.models.org import Branch
    branches = (db.query(Branch)
                .filter(Branch.company_id == company_id, Branch.deleted_at.is_(None),
                        Branch.is_active.is_(True))
                .order_by(Branch.created_at).all())
    if not branches:
        return {"state": COMPANY_CREATED, "ledger_native": is_ledger_native(db, company_id),
                "branches": [], "cash_setup_complete": False}
    rows = [dict(branch_cash_state(db, company_id, b.id), code=b.code, name=b.name)
            for b in branches]
    ready = all(r["active_tills"] > 0 for r in rows)
    return {
        "state": (POS_READY if ready else CASH_SETUP_REQUIRED),
        "ledger_native": is_ledger_native(db, company_id),
        "cash_setup_complete": ready,
        "branches": rows,
        # Operatorga KO'RSATILADIGAN yagona savol — tizim javobni TAXMIN QILA OLMAYDI.
        "question": ("Har filialda BUGUN nechta REAL fizik kassa (yashik) bor? "
                     "Har biri uchun alohida kassa yarating."),
    }


# ── Jimgina degradatsiyaga QARSHI qo'riqchi ─────────────────────────────────
class LedgerUnavailable(RuntimeError):
    """Ledger-native tenant uchun ledger YOZIB BO'LMAYDI — bu JIM o'tkazilmaydi."""


def require_ledger_writable(db: Session, company_id) -> None:
    """Ledger-native tenantda ledger YOZILA OLISHI SHART.

    NEGA: `cutover_guard.enforcement_active()` FAQAT `cutover_at` ni o'qiydi, dual-write esa
    `cash_enabled(db) AND mode != LEGACY_ONLY` ga bog'liq. Bu IKKI HAR XIL shart. Ular ajralib
    ketsa (cash sxemasi yo'q, yoki global SAVDOOS_CASH_MODE=LEGACY_ONLY), gardlar O'TAVERADI,
    lekin ledger legi YOZILMAYDI — ya'ni ledger-native do'kon jimgina eski (identity'siz) holatga
    tushardi. Aynan shu holat migratsiya bartaraf etmoqchi bo'lgan holat.

    Shu bois: ledger-native tenantda ledger yozib bo'lmasa — BALAND XATO. Legacy/migration
    tenantga TEGMAYDI (ular uchun bu holat qonuniy)."""
    if not is_ledger_native(db, company_id):
        return                                   # legacy/migration tenant — eski xulq
    from app.services.cash import mode as _mode
    from app.services.cash import retrofit as _cr
    # QAMROV: cash quyi tizimi ATAYLAB faqat Postgres'da mavjud (SQLite/dev'da TILL tushunchasi
    # umuman yo'q — u yerda ledger KUTILMAYDI). Shu bois qo'riqchi FAQAT Postgres'da ishlaydi:
    # o'sha yerda ledger yozilishi KUTILADI, va kutilgani bajarilmasa — bu JIM o'tkazilmaydi.
    # SQLite'da xato ko'tarish dev/demo oqimlarini bezovta qilardi va HECH QANDAY prod xavfini
    # kamaytirmasdi (production Postgres).
    if db.get_bind().dialect.name != "postgresql":
        return
    if not _cr.cash_enabled(db):
        raise LedgerUnavailable(
            "LEDGER-NATIVE do'kon: Postgres'da `cash` sxemasi TOPILMADI — ledger yozilmaydi. "
            "Fizik naqd amali BAJARILMAYDI (aks holda naqd identity'siz yozilib ketardi).")
    if not _mode.dual_write_active():
        raise LedgerUnavailable(
            "LEDGER-NATIVE do'kon: cash rejimi LEGACY_ONLY — ledger yozilmaydi. "
            "Fizik naqd amali BAJARILMAYDI.")


def ledger_expected_shift_cash(db: Session, company_id, shift_id, till_id=None,
                               opening_cash=None):
    """Ledger-native tenant uchun smenaning KUTILGAN fizik naqdi (Decimal) yoki None.

    §16 O'QISH AVTORITETI: legacy formula (opening + naqd savdo + payin - payout/expense/inkassa)
    FAQAT SalePayment va CashMovement ni sanaydi. NAQD XARID esa ledgerga OUT·PURCHASE_OUT yozadi,
    lekin CashMovement YOZMAYDI — natijada Z-hisobot xarid summasiga TENG SOXTA KAMOMAD ko'rsatardi.
    Ledger ON_SHIFT legilari BARCHA fizik harakatni qamraydi (ochilish float, savdo, qaytarish,
    payin/payout/xarajat, inkassa OUT, NAQD XARID), shu bois ledger-native do'konda kutilgan naqd
    AYNAN shundan hisoblanadi. None -> chaqiruvchi eski formulani ishlatadi (legacy tenant)."""
    if not is_ledger_native(db, company_id):
        return None
    from app.services.cash import mode as _mode
    from app.services.cash import repositories as _repo
    from app.services.cash import retrofit as _cr
    # Ledgerni AVTORITET sifatida o'qish uchun u YOZILAYOTGAN ham bo'lishi kerak. LEGACY_ONLY
    # rejimda yangi leg yozilmaydi — balans muzlab qoladi, uni "kutilgan naqd" deb ko'rsatish
    # NOTO'G'RI bo'lardi. Bu `require_ledger_writable` bilan bir xil shart (yozish/o'qish izchil).
    if not _cr.cash_enabled(db) or not _mode.dual_write_active() or till_id is None:
        return None
    if opening_cash is None:
        return None
    # OCHILISH-ANKORLI MODEL:
    #     kutilgan = SMENA OCHILISHIDAGI SANOQ + shu smenaning ledger HARAKATLARI
    #
    # NEGA yashik BALANSI EMAS: o'tgan smenada haqiqiy kamomad bo'lsa (kassir ledgerdan kam
    # sanagan), balans FIZIK haqiqatdan yuqori bo'lib qoladi — farqni KITOBGA olish `ADJUSTMENT`
    # bo'lib, u ATAYLAB menejer+ ruxsatini talab qiladi (§18: kassir o'zi kam sanab naqdni
    # hisobdan chiqara olmasin). Balansga ankor qilsak, o'sha BITTA yo'qotish HAR KEYINGI smenaga
    # qayta-qayta kamomad bo'lib yozilardi va YANGI kassir eski yo'qotish uchun javob berardi.
    # Ochilish sanog'iga ankor qilish buni to'xtatadi: har smena FAQAT O'Z oynasi uchun javob
    # beradi. Hal qilinmagan farq ledgerda KO'RINIB turadi (balans != ochilish sanog'i) va uni
    # faqat menejer ADJUSTMENT bilan yopadi — jimgina yutilmaydi.
    #
    # OPENING legi chiqariladi (shift_movement_total): u FAQAT farqni tutadi, ochilish sanog'i
    # esa allaqachon ankorda — aks holda yashikka qo'shilgan pul IKKI MARTA hisoblanardi.
    from decimal import Decimal as _Dec
    return _Dec(str(opening_cash or 0)) + _repo.shift_movement_total(db, company_id, shift_id)
