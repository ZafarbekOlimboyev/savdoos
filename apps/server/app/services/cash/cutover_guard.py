# -*- coding: utf-8 -*-
"""Cash · T0 CUTOVER GUARD — post-T0 fizik naqd amallari uchun MARKAZIY darvoza.

MUAMMO (audit): `cutover_reached` FAQAT 2 joyda tekshirilardi (smena ochish + onlayn naqd savdo), va
onlayn savdo guard'i `/sync/push` orqali BUTUNLAY chetlab o'tilardi. Qolgan 12 ta fizik-naqd kirish
nuqtasi T0'dan keyin ham TILL'siz naqd qabul qilaverardi.

QOIDA: T0'dan KEYIN har qanday FIZIK NAQD mutatsiya AYNAN joriy fizik custody hisobini (TILL yoki
SAFE) talab qiladi. TAXMIN YO'Q: filial-default, kassir-default, "branch'da bitta TILL", "branch'da
bitta SAFE", mutable terminal — hech biri YARAMAYDI.

═══ §6 ISHONCHLI (TRUSTED) MAJBURLASH VAQTI ════════════════════════════════
IKKI VAQT QAT'IY AJRATILADI:

  BUXGALTERIYA VAQTI (accounting time): `device_occurred_at` / `sold_at` — hodisa QACHON sodir
      bo'lgani. Bu ledger'da avtoritet bo'lib QOLADI (o'zgarmaydi).
  MAJBURLASH VAQTI (enforcement time): SERVER hodisani QABUL QILGAN payt (server_received_at).

Majburlash QAROR'I FAQAT SERVER vaqti bo'yicha qabul qilinadi. Sabab: `sold_at` mijozdan keladi,
imzolanmagan va SOXTALASHTIRILISHI mumkin — agar u T0 darvozasini ochsa, har qanday POS eski sana
yozib post-T0 naqdni TILL'siz kiritaverardi. Endi:

    Server hodisani T0'DAN KEYIN qabul qilsa -> AYNAN custody identity SHART
    (klient `sold_at` qanday bo'lishidan QAT'I NAZAR).

Haqiqiy pre-T0 offline hodisalar uchun yechim — vaqtga ishonish EMAS, balki §7 SINXRONIZATSIYA
BARYERI: T0 O'RNATISHDAN OLDIN barcha POS navbatlari bo'shatiladi (pending offline cash = 0).
Kelajakda kechikkan pre-T0 replay kerak bo'lsa — alohida, server-attested batch mexanizmi kerak;
`sold_at`ga SOXTA ISHONCH bu yerda QURILMAYDI.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import ShiftStatus
from app.services.cash import cutover as _cut
from app.services.cash import till_identity as _ti

# BARQAROR xato kodlari (operator/POS ular bo'yicha ishlov beradi)
ERR_LEGACY_SHIFT_NEEDS_TILL = "LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER"
ERR_TILL_REQUIRED = "TILL_REQUIRED_AFTER_CUTOVER"
ERR_TILL_INVALID = "TILL_INVALID_AFTER_CUTOVER"
ERR_TILL_SHIFT_MISMATCH = "TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER"
ERR_CUSTODY_REQUIRED = "CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER"
ERR_CUSTODY_INVALID = "CASH_CUSTODY_ACCOUNT_INVALID"
ERR_LEDGER_UNAVAILABLE = "CASH_LEDGER_UNAVAILABLE"
ERR_CLOSED_SHIFT_REPLAY = "CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY"


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _fail(code: str, msg: str):
    raise HTTPException(400, f"{code}: {msg}")


def enforcement_active(db: Session, company_id, **_ignored) -> bool:
    """§6: majburlash rejimi FAOL mi — FAQAT SERVER qabul vaqti bo'yicha.

    Klient bergan `sold_at`/`device_occurred_at` bu qarorga TA'SIR QILMAYDI (ular buxgalteriya
    vaqti). `**_ignored` — eski chaqiruvchilar occurred_at/proven uzatsa ham xato bermasin, lekin
    ular QARORGA KIRMAYDI."""
    t0 = _cut.cutover_at(db, company_id)
    if t0 is None:
        return False                                  # T0 belgilanmagan -> legacy rejim (butun tenant)
    return _aware(datetime.now(timezone.utc)) >= t0   # SERVER qabul vaqti — ishonchli


def reject_closed_shift_replay(db: Session, *, company_id, shift, operation: str):
    """§9: YOPILGAN/yarashtirilgan smenaga oddiy POS replay'i naqd o'zgartirmasin.

    Smena qayta OCHILMAYDI, reconciliation YANGILANMAYDI, boshqa smenaga AVTOMATIK biriktirilmaydi,
    jimgina smenadan tashqarida post QILINMAYDI. Kelajakdagi ANIQ recovery oqimi (operator tasdig'i +
    aniq custody dalili + LATE_SYNC + reconciliation exception) alohida quriladi."""
    if shift is None or not enforcement_active(db, company_id):
        return
    st = getattr(shift, "status", None)
    st = st.value if hasattr(st, "value") else str(st)
    if st == ShiftStatus.closed.value or getattr(shift, "closed_at", None) is not None:
        _fail(ERR_CLOSED_SHIFT_REPLAY,
              f"'{operation}': YOPILGAN smenaga naqd yozib bo'lmaydi (smena {getattr(shift, 'id', '?')} "
              "yopilgan/yarashtirilgan). Smena qayta ochilmaydi va hisob-kitob o'zgartirilmaydi — "
              "bu holat ANIQ recovery oqimini talab qiladi.")


def require_ledger_writable(db: Session, company_id, operation: str) -> None:
    """§1 YAGONA MARKAZIY INVARIANT: ledger-native do'konda ledger YOZIB BO'LMASA, fizik naqd
    amali BIZNES QATORI COMMIT QILINISHIDAN OLDIN baland RAD etiladi.

    NEGA MARKAZIY: `enforcement_active` FAQAT cutover_at ni o'qiydi, dual-write esa
    cash_enabled + mode ga bog'liq — ikki HAR XIL shart. Ular ajralса, gardlar o'tar, ledger legi
    yozilmasdi. Tekshiruvni har endpointga sochib qo'ymaymiz: BARCHA fizik naqd yo'llari
    require_post_t0_till yoki require_custody_account dan o'tadi, shu bois invariant SHU IKKI
    ildizda turadi (shifts, cashops, sales, customers, purchases, receiving — hammasi qamraladi).

    NAQD BO'LMAGAN amallar bu yo'ldan O'TMAYDI, shu bois ular hech qachon bloklanmaydi.
    SQLite/dev ATAYLAB tegilmaydi (u yerda cash quyi tizimi umuman kutilmaydi)."""
    from app.services.cash import tenant as _tn
    try:
        _tn.require_ledger_writable(db, company_id)
    except _tn.LedgerUnavailable as e:
        _fail(ERR_LEDGER_UNAVAILABLE, f"'{operation}': {e}")


def require_custody_account(db: Session, *, company_id, branch_id, account_id, operation: str,
                            expect_type: str | None = None, currency: str | None = None):
    """§1B/§3: SMENASIZ naqd uchun EXPLICIT custody hisobi (TILL yoki SAFE) validatsiyasi.

    TAXMIN YO'Q: filial-default, birinchi TILL, yagona-TILL, yagona-SAFE — hech biri.
    Tekshiriladi: mavjud + type (TILL|SAFE) + ACTIVE + tenant + FILIAL + (berilsa) valyuta."""
    require_ledger_writable(db, company_id, operation)
    from app.models.cash import CashAccount
    if account_id is None:
        _fail(ERR_CUSTODY_REQUIRED,
              f"'{operation}': T0'dan keyin naqd manbai/manzili AYNAN ko'rsatilishi SHART "
              "(kassa TILL yoki seyf SAFE). Filial/kassir bo'yicha TAXMIN QILINMAYDI.")
    acc = db.get(CashAccount, account_id)
    if acc is None:
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': naqd hisob topilmadi ({account_id}).")
    if str(acc.tenant_id) != str(company_id):
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': naqd hisob boshqa do'konga tegishli.")
    if str(acc.status) != "ACTIVE":
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': naqd hisob faol emas ({acc.status}).")
    if expect_type is not None and str(acc.type) != expect_type:
        _fail(ERR_CUSTODY_INVALID,
              f"'{operation}': hisob turi {acc.type}, kutilgan {expect_type}.")
    if str(acc.type) not in ("TILL", "SAFE"):
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': fizik custody hisobi TILL yoki SAFE bo'lishi kerak.")
    if branch_id is not None and str(acc.branch_id) != str(branch_id):
        _fail(ERR_CUSTODY_INVALID,
              f"'{operation}': hisob boshqa filialga tegishli ({acc.branch_id} != {branch_id}).")
    if currency is not None and str(acc.currency) != str(currency):
        _fail(ERR_CUSTODY_INVALID,
              f"'{operation}': valyuta mos emas ({acc.currency} != {currency}).")
    return acc


def require_post_t0_till(db: Session, *, company_id, branch_id, operation: str,
                         shift=None, till_id=None, occurred_at=None,
                         occurred_at_proven: bool = True):
    """§1A: SMENAGA BOG'LANGAN naqd uchun AYNAN `shift.till_id` talab qiladi va validatsiya qiladi.

    Qaytaradi: (CashAccount|None, enforced: bool).
      - enforced=False -> pre-T0 SERVER qabuli: legacy moslik; TILL TALAB QILINMAYDI va O'YLAB
        TOPILMAYDI.
      - enforced=True  -> qaytarilgan TILL tasdiqlangan: mavjud, type=TILL, ACTIVE, shu tenant,
        shu filial, va (smena berilgan bo'lsa) smenaning till_id'si bilan MOS.

    DIQQAT (§6): `occurred_at`/`occurred_at_proven` QARORGA TA'SIR QILMAYDI — faqat imzo mosligi
    uchun qoldirilgan. Majburlash SERVER qabul vaqti bo'yicha."""
    require_ledger_writable(db, company_id, operation)
    if not enforcement_active(db, company_id):
        return None, False

    # §9: yopilgan smenaga replay — custody tekshiruvidan OLDIN rad etiladi
    reject_closed_shift_replay(db, company_id=company_id, shift=shift, operation=operation)

    # §3/§11 LEGACY OCHIQ SMENA T0'NI KESIB O'TDI: smena bor, lekin till_id YO'Q -> QAT'IY RAD.
    if shift is not None and getattr(shift, "till_id", None) is None:
        _fail(ERR_LEGACY_SHIFT_NEEDS_TILL,
              f"T0 (cutover)'dan keyin '{operation}' amali kassasi (TILL) aniqlanmagan LEGACY smenada "
              "bajarilmaydi. Smenani YOPING va aniq kassa (TILL) bilan yangi smena oching. "
              "Kassa avtomatik biriktirilmaydi.")

    eff = till_id if till_id is not None else getattr(shift, "till_id", None)
    if eff is None:
        _fail(ERR_TILL_REQUIRED,
              f"T0 (cutover)'dan keyin '{operation}' amali AYNAN kassa (TILL) talab qiladi. "
              "Filial/kassir bo'yicha TAXMIN QILINMAYDI — kassani tanlang yoki sozlang.")

    acc, why = _ti.get_till(db, company_id, eff)       # tenant + type=TILL + ACTIVE
    if acc is None:
        _fail(ERR_TILL_INVALID,
              f"'{operation}': kassa (TILL) yaroqsiz ({why}). Faol (ACTIVE) va shu do'konga tegishli "
              "kassa bo'lishi SHART.")
    if branch_id is not None and str(acc.branch_id) != str(branch_id):
        _fail(ERR_TILL_INVALID,
              f"'{operation}': kassa boshqa filialga tegishli (till branch={acc.branch_id} != "
              f"{branch_id}).")
    if shift is not None and till_id is not None and str(shift.till_id) != str(till_id):
        _fail(ERR_TILL_SHIFT_MISMATCH,
              f"'{operation}': berilgan kassa smenaning kassasi bilan mos emas "
              f"(shift.till={shift.till_id} != {till_id}).")
    return acc, True


def cutover_open_shift_gate(db: Session, *, company_id, shift, operation: str,
                            occurred_at=None, occurred_at_proven: bool = True):
    """§11: T0'ni KESIB O'TGAN legacy ochiq smena uchun darvoza (smena-doirasidagi o'ram).

    Pre-T0 server qabuli: legacy xatti-harakat saqlanadi. Post-T0: till_id=NULL smena orqali HAR
    QANDAY fizik naqd mutatsiya QAT'IY rad etiladi; YOPILGAN smenaga replay ham rad etiladi.
    T0'da HECH NARSA avtomatik o'zgartirilmaydi."""
    return require_post_t0_till(db, company_id=company_id,
                                branch_id=getattr(shift, "branch_id", None),
                                operation=operation, shift=shift)


def resolve_cash_custody(db: Session, *, company_id, branch_id, operation, shift=None,
                         cash_account_id=None, currency=None):
    """§2 CUSTODY REZOLYUTSIYA QOIDASI (smenali va smenasiz naqd uchun YAGONA joy).

        Ochiq smena BOR   -> custody = shift.till_id
        Ochiq smena YO'Q  -> custody = so'rovdagi EXPLICIT cash_account_id (TILL yoki SAFE)

    HECH QACHON: filial-default, birinchi ACTIVE TILL, yagona TILL, kassir-default,
    terminal inference, implicit SAFE.

    Qaytaradi (account|None, enforced: bool):
      * account berilgan bo'lsa — u TO'LIQ validatsiyadan o'tgan (mavjud, TILL|SAFE, ACTIVE,
        shu tenant, shu filial, valyuta mos).
      * (None, False) — pre-T0 VA hech qanday explicit hisob berilmagan: legacy moslik,
        chaqiruvchi eski xatti-harakatini davom ettiradi (TAXMIN QILINMAYDI).

    DIQQAT: explicit hisob berilgan bo'lsa u T0'gacha ham VALIDATSIYA qilinadi va ISHLATILADI —
    noto'g'ri hisobni "pre-T0" deb jimgina qabul qilish XATO bo'lardi."""
    enforced = enforcement_active(db, company_id)

    # §9: yopilgan smenaga replay — custody tanlashdan OLDIN rad etiladi
    reject_closed_shift_replay(db, company_id=company_id, shift=shift, operation=operation)

    shift_till = getattr(shift, "till_id", None) if shift is not None else None

    if shift is not None and shift_till is not None:
        # SMENAGA BOG'LANGAN: drawer smenadan keladi; chaqiruvchi override QILA OLMAYDI.
        if cash_account_id is not None and str(cash_account_id) != str(shift_till):
            _fail(ERR_TILL_SHIFT_MISMATCH,
                  f"'{operation}': berilgan naqd hisob ochiq smenaning kassasi bilan mos emas "
                  f"(shift.till={shift_till} != {cash_account_id}). Smenaga bog'langan naqd uchun "
                  "kassani almashtirib bo'lmaydi.")
        if not enforced and cash_account_id is None:
            # PRE-T0 LEGACY MOSLIK: smenaning till'i yaroqsiz bo'lsa (masalan ARCHIVED) eski
            # xatti-harakat — GUARDED SKIP (jimgina 400 EMAS). Post-T0 da esa QAT'IY validatsiya.
            try:
                acc = require_custody_account(db, company_id=company_id, branch_id=branch_id,
                                              account_id=shift_till, operation=operation,
                                              expect_type="TILL", currency=currency)
            except HTTPException:
                return None, False
            return acc, False
        acc = require_custody_account(db, company_id=company_id, branch_id=branch_id,
                                      account_id=shift_till, operation=operation,
                                      expect_type="TILL", currency=currency)
        return acc, True

    if shift is not None and enforced:
        # Smena bor, lekin till_id YO'Q va T0 o'tgan -> legacy smena T0'ni kesib o'tdi
        _fail(ERR_LEGACY_SHIFT_NEEDS_TILL,
              f"T0 (cutover)'dan keyin '{operation}' amali kassasi (TILL) aniqlanmagan LEGACY smenada "
              "bajarilmaydi. Smenani YOPING va aniq kassa (TILL) bilan yangi smena oching.")

    # SMENASIZ: explicit hisob SHART (post-T0), pre-T0 esa berilgan bo'lsa ISHLATILADI.
    if cash_account_id is None:
        if not enforced:
            return None, False              # pre-T0 legacy: eski xatti-harakat, TAXMIN YO'Q
        _fail(ERR_CUSTODY_REQUIRED,
              f"'{operation}': T0 (cutover)'dan keyin smenasiz naqd amali uchun naqd hisob (kassa TILL "
              "yoki seyf SAFE) AYNAN ko'rsatilishi SHART — `cash_account_id` yuboring. "
              "Filial/kassir bo'yicha TAXMIN QILINMAYDI.")
    acc = require_custody_account(db, company_id=company_id, branch_id=branch_id,
                                  account_id=cash_account_id, operation=operation,
                                  currency=currency)
    return acc, True
