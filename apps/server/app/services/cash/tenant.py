# -*- coding: utf-8 -*-
"""Cash — TENANT TURI va ONBOARDING HOLATI (fresh vs legacy).

═══ UCH YO'L, ARALASHTIRILMAYDI ═════════════════════════════════════════════

  LEGACY / MIGRATION tenant — YANGI ledger arxitekturasidan OLDIN yaratilgan. Naqd tarixi
      bo'lishi mumkin, uning drawer identity'si dalilsiz bo'lishi mumkin (HISTORICAL_TILL_UNKNOWN).
      Yo'l: discover -> provision -> readiness -> T0 -> backfill -> verify (migration marosimi).

  FRESH / LEDGER-NATIVE tenant — YANGI arxitektura ishga tushgandan KEYIN yaratilgan. Legacy naqd
      tarixi YO'Q, shu bois backfill ham, tarixiy TILL rekonstruksiyasi ham, T0 marosimi ham
      KERAK EMAS. U BIRINCHI fizik naqd hodisasidanoq aniq custody bilan ishlaydi.

  HISTORICAL_BUILD (demo-tarix qurilishi) — DEMO/TEST tenant uchun VAQTINCHALIK va TUGAYDIGAN
      holat: `cash` Setting qatori BOR, lekin unda `ledger_native` ham, `cutover_at` ham YO'Q.
      Shakli LEGACY tenantga TENG (T0 belgilanmagan), shu bois imtiyozli tarixiy yozuv yuzasi
      (`POST /historical/events`) ochiq bo'ladi va kanonik yozuvchilar AYNAN o'zlari isbotlangan
      rejimda ishlaydi. FINALIZE bu holatni BIR qulflangan tranzaksiyada FRESH yo'liga o'tkazadi:
      `ledger_native` + `cutover_at` BIRGA yoziladi, `historical_build` olib tashlanadi — va
      o'sha lahzadan tarixiy yuza O'ZI yopiladi (`historical.assert_demo_tenant` 4-sharti).
      HAQIQIY do'konga HECH QACHON qo'llanilmaydi: faqat 'test'/'demo' kodli tenant, faqat
      vendor identity, faqat non-production muhit.

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
hali ma'noga ega. Bu bayroqni YOZADIGAN joy AYNAN IKKITA: yangi kompaniya yaratilishi
(`mark_ledger_native`) va demo-tarix qurilishining YAKUNLANISHI
(`finalize_historical_build`). Uchinchi yo'l YO'Q.
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


def is_ledger_authoritative(db: Session, company_id) -> bool:
    """HISOBOT RAQAMLARI uchun ledger AVTORITETMI (o'qish yo'llari uchun yagona predikat).

    IKKI shart birga:
      1. tenant `ledger_native` — ANIQ bayroq (`Setting(key='cash').value.ledger_native is True`),
         kompaniya yaratilishida yoziladi va o'zgarmaydi. Bunday do'konda naqd xarid FAQAT
         ledgerga yoziladi (`CashMovement` YO'Q), ya'ni o'sha son uchun boshqa manba MAVJUD EMAS.
      2. dialekt Postgres — cash quyi tizimi ATAYLAB faqat Postgres'da bor
         (`require_ledger_writable` bilan AYNI qamrov: SQLite/dev'da ledger KUTILMAYDI, shu bois
         u yerda hisobot legacy shaklida qoladi va dev oqimlari bezovta bo'lmaydi).

    ⚠️  Bu `retrofit.cash_enabled()` EMAS: u — INFRA darvozasi (sxema bor/yo'q), avtoritet emas.
        Va bu `mode.cash_mode()` ham emas: rejim butun deploy uchun, avtoritet esa TENANT uchun.
        Ledger-native do'konda rejim `LEGACY_ONLY` bo'lsa ledger avtoritet BO'LIB QOLADI, lekin
        yozilmaydi — bu BALAND xato holati (`require_ledger_writable`), jimgina legacy EMAS.
    """
    if not is_ledger_native(db, company_id):
        return False
    return db.get_bind().dialect.name == "postgresql"


def mark_ledger_native(db: Session, company_id, *, at: datetime | None = None) -> dict:
    """Kompaniya YARATILISHIDA chaqiriladi: fresh tenant sifatida belgilaydi va cutover_at ni
    SHU lahzaga qo'yadi. commit QILMAYDI — chaqiruvchi tranzaksiyasida qoladi.

    IDEMPOTENT: mavjud `cash` Setting bo'lsa TEGILMAYDI — shart AYNAN qator BORLIGI,
    uning ICHIDAGI kalitlar TEKSHIRILMAYDI (legacy tenantning T0'sini yoki demo-tarix
    qurilishi holatini tasodifan qayta yozmaslik uchun). Kod ataylab o'z tavsifidan
    QAT'IYROQ: `cutover_at` yo'q qatorni ham tegmasdan qaytaradi."""
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


# ── DEMO-TARIX QURILISHI (HISTORICAL_BUILD) ─────────────────────────
#  VAQTINCHALIK, TUGAYDIGAN holat. Faqat demo/test tenant, faqat vendor identity.
HISTORICAL_BUILD_FLAG = "historical_build"


class HistoricalBuildConflict(RuntimeError):
    """Demo-tarix lifecycle o'tishi BAJARILMAYDI — holat mos emas (jim o'tkazilmaydi)."""


def _iso_aware(raw) -> datetime | None:
    """ISO matndan timezone-aware UTC. Yaroqsiz bo'lsa None.

    ⚠️  `cutover.cutover_at` bilan AYNI fail-open semantikasi: bu yerda ham yaroqsiz
        qiymat `None` bo'ladi. Lekin lifecycle qarorlari T0 YO'QLIGIGA emas,
        `historical_build` BAYROG'IGA tayanadi — shu bois buzuq qiymat holatni
        "qurilish" deb ko'rsatib yubormaydi."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def is_historical_build(db: Session, company_id) -> bool:
    """Tenant HISTORICAL_BUILD holatidami. ANIQ bayroq — taxmin YO'Q.

    ⚠️  Bu `cutover_at is None` BILAN BIR XIL EMAS. T0 yo'qligi legacy tenantda ham,
        BUZUQ `cash` qiymatida ham ro'y beradi (`cutover.cutover_at` yaroqsiz ISO'da
        `None` qaytaradi — FAIL-OPEN). Shu bois lifecycle qarorlari SHU bayroqqa
        tayanadi: buzuq T0 haqiqiy do'konni "qurilish holatida" deb ko'rsatolmaydi."""
    return bool(cash_config(db, company_id).get(HISTORICAL_BUILD_FLAG) is True)


def mark_historical_build(db: Session, company_id, *, at: datetime | None = None,
                          plan_id: str | None = None) -> dict:
    """Imtiyozli demo-tarix provisioning'da, kompaniya YARATILISHIDA chaqiriladi.
    commit QILMAYDI — chaqiruvchi tranzaksiyasida qoladi.

    FAQAT INSERT: `cash` Setting ALLAQACHON bo'lsa — RAD ETILADI. `mark_ledger_native` dagi
    "mavjud bo'lsa jim qaytaramiz" xulqi BU YERDA XATO bo'lardi: u yerda maqsad mavjud
    tenantning T0'sini SAQLASH, bu yerda esa chaqiruvchi YANGI kompaniya yaratayotganini
    DA'VO qiladi — qator borligi da'voni yolg'onga chiqaradi (mavjud do'konni "qurilish"
    holatiga tortib kiritish aynan shu yerdan boshlanardi).

    `ledger_native` ham, `cutover_at` ham ATAYLAB YOZILMAYDI — ikkisi FINALIZE'da BIRGA
    yoziladi. NEGA: `ledger_native=true` + `cutover_at=NULL` juftligi ZARARLI. Hisobot
    tomonida `is_ledger_authoritative` (yuqorida) `cutover_at` ni UMUMAN o'qimaydi, ya'ni
    ledger AVTORITET deb e'lon qilinadi; yozuv tomonida esa T0 yo'qligi
    `cutover_guard.enforcement_active` ni False qoldiradi va smenasiz naqd xaridning ledger
    legi JIMGINA tushib qoladi. Natija — hisobot "kassada"ni KO'P ko'rsatadi."""
    from app.models.settings import Setting
    stamp = (at or datetime.now(timezone.utc))
    iso = stamp.isoformat() if isinstance(stamp, datetime) else str(stamp)
    if _cash_setting(db, company_id) is not None:
        raise HistoricalBuildConflict(
            "Bu do'konda `cash` sozlamasi ALLAQACHON bor — demo-tarix qurilishi FAQAT yangi "
            "yaratilgan kompaniyaga qo'yiladi (mavjud do'konni qurilish holatiga o'tkazish "
            "ATAYLAB taqiqlangan).")
    val = {HISTORICAL_BUILD_FLAG: True, "build_started_at": iso, "build_plan_id": plan_id}
    db.add(Setting(company_id=company_id, branch_id=None, key=CASH_SETTING_KEY, value=val))
    return val


def finalize_historical_build(db: Session, company_id, *, t0: datetime) -> tuple[dict, bool]:
    """HISTORICAL_BUILD -> LIVE_DEMO. BIR QULFLANGAN read-modify-write. commit QILMAYDI.

    Qaytaradi `(qiymat, created)`. `created=False` — allaqachon AYNAN SHU T0 bilan
    yakunlangan (idempotent takror). Boshqa T0 bilan takror -> `HistoricalBuildConflict`.

    `ledger_native` va `cutover_at` BIR vaqtda yoziladi — oraliq holat KO'RINMAYDI.
    FAQAT T0 QO'YADI: bu funksiya `cutover_at` ni hech qachon tozalamaydi/qaytarmaydi."""
    from app.models.settings import Setting
    if not isinstance(t0, datetime) or t0.tzinfo is None:
        raise HistoricalBuildConflict("T0 timezone-aware datetime bo'lishi SHART (kanonik UTC).")
    t0 = t0.astimezone(timezone.utc)
    # ⚠️  AVVAL FLUSH. Sessiya `autoflush=False`: shu tranzaksiyada qatorga yozilgan, hali
    #     yuborilmagan o'zgarishni `populate_existing` bazadagi qiymat bilan USTIDAN yozib
    #     yo'qotardi (`catalog_import_v2._write_catalog` qayd etgan nuqson sinfi).
    db.flush()
    # `populate_existing` SHART: sessiya qatorni oldinroq yuklab, identity map'da ESKI
    # nusxasini ushlab turgan bo'lishi mumkin — usiz qulf olinsa ham qaror eskirgan qiymat
    # ustida qabul qilinardi. Qulfning o'zi READ COMMITTED da yo'qolgan yozuvni to'sadi:
    # qulfsiz ikki parallel finalize biri ikkinchisining T0'sini jimgina o'chirardi.
    row = (db.query(Setting)
           .filter(Setting.company_id == company_id, Setting.branch_id.is_(None),
                   Setting.key == CASH_SETTING_KEY)
           .with_for_update().populate_existing().first())
    if row is None:
        raise HistoricalBuildConflict(
            "`cash` sozlamasi topilmadi — bu do'kon demo-tarix qurilishi holatida emas.")
    cur = dict(row.value or {})
    if cur.get(HISTORICAL_BUILD_FLAG) is not True:
        # IDEMPOTENTLIK SHU YERDA. Takror chaqiruv AYNI T0 ni qayta hisoblaydi (journal
        # qatorlari o'zgarmas va yuza yopilgan), shu bois "yo'qolgan javob" uchun retry
        # xavfsiz: 409 EMAS, `duplicate`.
        if cur.get("historical_build_finalized_at") and cur.get("ledger_native") is True:
            mavjud = _iso_aware(cur.get("cutover_at"))
            if mavjud is not None and mavjud == t0:
                return cur, False
            raise HistoricalBuildConflict(
                "Bu do'kon ALLAQACHON yakunlangan, lekin BOSHQA T0 bilan "
                f"(mavjud={cur.get('cutover_at')!r}, so'ralgan={t0.isoformat()!r}) — "
                "yakunlangan T0 QAYTA YOZILMAYDI.")
        raise HistoricalBuildConflict(
            "Bu do'kon HISTORICAL_BUILD holatida emas — yakunlash BAJARILMAYDI.")
    # Qurilish holatida T0 yoki ledger_native bo'lishi MUMKIN EMAS (`mark_historical_build`
    # ikkisini ham yozmaydi). Bo'lsa — holat buzilgan; jim tuzatmaymiz.
    if cur.get("cutover_at") or cur.get("ledger_native") is True:
        raise HistoricalBuildConflict(
            "Buzilgan holat: qurilish bayrog'i bilan birga `cutover_at`/`ledger_native` "
            f"topildi ({cur!r}) — qo'lda tekshirish talab qiladi.")
    boshlangan = cur.get("build_started_at")
    if not boshlangan or _iso_aware(boshlangan) is None:
        # Fail-closed: `onboarded_at` ni jimgina T0 bilan to'ldirish audit yolg'oni bo'lardi.
        raise HistoricalBuildConflict(
            f"`build_started_at` yaroqsiz ({boshlangan!r}) — `onboarded_at` ni taxmin "
            "qilmaymiz.")
    yangi = {"ledger_native": True,
             "onboarded_at": boshlangan,
             "cutover_at": t0.isoformat(),
             "historical_build_finalized_at": datetime.now(timezone.utc).isoformat()}
    row.value = yangi            # YANGI dict — JSON ustunida o'rnida o'zgartirish kuzatilmaydi
    db.add(row)
    return yangi, True


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


def onboarding_state(db: Session, company_id, *, branch_ids=None) -> dict:
    """Kompaniya darajasidagi onboarding holati — Manager sozlash ekrani uchun.

    `branch_ids` — chaqiruvchining KO'RISH doirasi (`visible_branches`; None = cheklovsiz). Berilsa
    filiallar ro'yxati VA umumiy holat (`state`/`cash_setup_complete`) faqat shu filiallar bo'yicha:
    bitta filial xodimi boshqa filialning sozlanmaganini "sizda kassa yo'q" deb ko'rmasin.
    Doira SHU funksiyada emas, chaqiruvchida hal qilinadi — xizmat HTTP xodimini bilmaydi."""
    from app.models.org import Branch
    q = (db.query(Branch)
         .filter(Branch.company_id == company_id, Branch.deleted_at.is_(None),
                 Branch.is_active.is_(True)))
    if branch_ids is not None:
        q = q.filter(Branch.id.in_(list(branch_ids)))
    # id — teng created_at (bitta tranzaksiyada yaratilgan filiallar) uchun barqaror tartib.
    branches = q.order_by(Branch.created_at, Branch.id).all()
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
