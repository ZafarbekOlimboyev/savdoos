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

═══ XATO GIGIYENASI (Phase 5G.1) ═══════════════════════════════════════════
Rad etish matni OPERATOR uchun: kod prefiksi + o'zi bajara oladigan jumla. Bazadan o'qilgan
id'lar (smena, kassa, hisob, filial) MATNGA YOZILMAYDI — ular `_fail` ning strukturali
kwarg'lari orqali FAQAT kuzatuv jurnaliga (`savdoos.cash`) tushadi. Sabab: javob tanasi
proksi/Railway loglariga, brauzer devtools'iga, HAR qanday mijozga boradi; jurnal esa faqat
operatorga. Kod `X-Error-Code` sarlavhasida HAM yuradi (`main.py` CORS ochgan) — prefiks
eski mijozlar uchun qoladi.
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import error_codes as EC
from app.services.cash import observability as _obs

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

# YAGONA LUG'AT. `code_of` kodni AYNAN shu to'plamdan taniydi — ro'yxatdan tashqari
# prefiks kod deb qabul QILINMAYDI (aks holda oddiy ikki nuqtali xato matni "kod"
# bo'lib ketardi). Yangi ERR_* qo'shilsa — shu yerga ham qo'shiladi.
ERROR_CODES = (ERR_LEGACY_SHIFT_NEEDS_TILL, ERR_TILL_REQUIRED, ERR_TILL_INVALID,
               ERR_TILL_SHIFT_MISMATCH, ERR_CUSTODY_REQUIRED, ERR_CUSTODY_INVALID,
               ERR_LEDGER_UNAVAILABLE, ERR_CLOSED_SHIFT_REPLAY)

# §7 IDEMPOTENTLIK KONFLIKTI — AYNI kalit (`client_uuid`) BOSHQA custody hisobi bilan qayta
# kelganda uchala yozuvchi (`customers.pay_credit`, `purchases.create_purchase`,
# `purchases.pay_supplier`) uchun BITTA matn (`cashops.KEY_REUSED_TEXT` naqshi). Saqlangan
# hisob id'i — mijoz bu so'rovda YUBORMAGAN id — MATNGA EMAS, jurnalga
# (`key_account_conflict`).
# ⚠️  AYNAN `purchases.KEY_ACCOUNT_CONFLICT_TEXT` bilan BIR XIL jumla (B2 paketi bilan
#     kelishilgan) — o'zgartirsangiz ikkalasini birga o'zgartiring.
KEY_ACCOUNT_CONFLICT_TEXT = (
    f"{ERR_CUSTODY_INVALID}: bu amal allaqachon BOSHQA naqd hisob bilan yozilgan — "
    "qayta yuborishda hisobni o'zgartirib bo'lmaydi. Avval to'lovlar ro'yxatini tekshiring."
)

# QURUQ YURISH bayrog'i (`preview_cash_custody`). ContextVar — thread/task bo'yicha
# ajratilgan: FastAPI sinxron endpoint'ni threadpool'da chaqiradi va parallel
# so'rovlar bir-birining bayrog'ini ko'rmasligi SHART.
_PREVIEW: ContextVar[bool] = ContextVar("cash_custody_preview", default=False)


def code_of(detail) -> str | None:
    """Rad etish matnidan BARQAROR kodni ajratadi (`"<KOD>: matn"` prefiksi) yoki None.

    NEGA PREFIKS. Kassa rad etishlari ATAYLAB kodni MATN ICHIDA olib yuradi va
    mijoz (`serverErrorsCash.ts`) ham AYNAN shu prefiks bo'yicha tarjima qiladi.
    Bu yerda o'sha YAGONA konvensiya teskari o'qiladi — ikkinchi mexanizm o'ylab
    topilmaydi."""
    head = str(detail or "").split(":", 1)[0].strip()
    return head if head in ERROR_CODES else None


def preview_cash_custody(db: Session, *, company_id, branch_id, operation, shift=None,
                         cash_account_id=None, currency=None):
    """QURUQ YURISH: `resolve_cash_custody` NING O'ZINI chaqiradi, rad etishni kodga o'giradi.

    Qaytaradi `(account|None, enforced: bool, code|None)` — `code` None bo'lsa qaror
    MUVAFFAQIYATLI (yozuvchi ham aynan shu hisobni olardi).

    ⚠️  BU IKKINCHI DARVOZA EMAS. Bu yerda birorta qoida QAYTA YOZILMAYDI: o'qish yo'li
        (Manager ekrani «qaysi kassadan?» deb ko'rsatishi uchun) yozuvchi bilan AYNI
        funksiyani bajaradi, shu bois ular prinsipial ravishda ajralib keta olmaydi.
        Ikki joyda ikki xil hisob operatorga «mumkin» deb ko'rsatib, server 400
        berardi (`purchases._correction_view` izohidagi AYNI dars).

    ⚠️  HECH NARSA YOZMAYDI: `resolve_cash_custody` ning o'zi ham faqat `Setting`,
        `Shift` va `CashAccount` ni O'QIYDI (qulf ham olmaydi). Yagona farq —
        kuzatuv jurnaliga `cash_failure` qatori TUSHMAYDI (`_fail` izohi).
    """
    res, code = dry_run(resolve_cash_custody, db, company_id=company_id, branch_id=branch_id,
                        operation=operation, shift=shift, cash_account_id=cash_account_id,
                        currency=currency)
    if code is not None:
        return None, True, code
    acc, enforced = res
    return acc, enforced, None


def dry_run(fn, *args, **kwargs):
    """QURUQ YURISH — istalgan kassa gardini (`resolve_cash_custody`,
    `require_custody_account`, `cutover_open_shift_gate`, ...) AYNAN o'zini chaqiradi.

    Qaytaradi `(natija, None)` yoki `(None, code)`.

    ⚠️  Gard QAYTA YOZILMAYDI — o'qish yo'li (`custody_preview`) yozuvchi bilan AYNI
        funksiyani bajaradi. Yagona farq: `_fail` kuzatuv jurnaliga `cash_failure`
        yozmaydi (`_fail` izohi). Gardlar faqat O'QIYDI (qulf ham olmaydi)."""
    tok = _PREVIEW.set(True)
    try:
        return fn(*args, **kwargs), None
    except HTTPException as e:
        # Kodsiz rad etish bu yo'lda bo'lishi mumkin emas (hamma `_fail` kod bilan
        # yozadi), lekin bo'lsa ham NOMSIZ qoldirilmaydi: nomlanmagan kassa rad
        # etishi — quyi tizim ishlatib bo'lmasligi bilan BIR XIL yakun.
        return None, (code_of(e.detail) or ERR_LEDGER_UNAVAILABLE)
    finally:
        _PREVIEW.reset(tok)


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _fail(code: str, msg: str, *, detail: str | None = None, company_id=None, branch_id=None,
          shift_id=None, account_id=None, till_id=None, operation: str | None = None,
          status: int = 400):
    """Gard xatosi — ko'tarilishdan OLDIN strukturali log yoziladi.

    `msg` — OPERATOR jumlasi: barqaror, ID'SIZ, tarjima qilinadigan (mijoz kodga qaraydi,
    lekin eski mijoz matnni ham ko'rsatishi mumkin). `detail` va id-kwarg'lar
    (`company_id`, `branch_id`, `shift_id`, `account_id`, `till_id`) — ICHKI: FAQAT
    jurnalga, javobga HECH QACHON tushmaydi. Kod `X-Error-Code` sarlavhasida ham yuradi.

    NEGA: ilgari naqd amali gardga urilib rad etilganda hech narsa logga tushmasdi — xato
    faqat kassir ekraniga chiqardi. Production'da "qaysi do'konda, qaysi filialda, qaysi
    sababdan naqd o'tmadi?" degan savolga javob beradigan iz QOLMASDI. Keyin id'lar
    diagnostika uchun MATNGA yozilgan edi — endi ular strukturali maydonda (`jq` bilan
    `select(.account_id=="…")`), matn esa toza.

    ⚠️  QURUQ YURISH (`preview_cash_custody`) LOGGA YOZMAYDI. Ekran har ochilganda
        AYNI qaror o'qish uchun qayta hisoblanadi; u yozgan `cash_failure` qatorlari
        HAQIQIY rad etishlar bilan aralashib, yuqoridagi savolning javobini
        BO'G'IB qo'yardi (bir operator bir hujjatni o'n marta ochsa — o'nta soxta
        "naqd o'tmadi"). Qaror yo'li AYNAN o'sha: faqat kuzatuv yozuvi yozilmaydi."""
    if not _PREVIEW.get():
        _obs.log_cash_failure(code, operation=operation, company_id=company_id,
                              branch_id=branch_id, shift_id=shift_id, account_id=account_id,
                              till_id=till_id, detail=(detail or msg))
    raise HTTPException(status, f"{code}: {msg}", headers=EC.headers(code))


def key_account_conflict(*, company_id, operation: str, stored_account_id, requested_account_id,
                         branch_id=None) -> HTTPException:
    """§7: AYNI kalit BOSHQA custody hisobi bilan qayta yuborildi — 409, HECH NARSA yozilmaydi.

    Qaytaradi (ko'tarmaydi) — chaqiruvchi `raise key_account_conflict(...)` deb yozadi, oqim
    o'qiganga ochiq bo'lsin. Saqlangan hisob id'i mijoz bu so'rovda YUBORMAGAN id: u faqat
    jurnalga (`account_id`), so'ralgan hisob esa `detail` ga."""
    _obs.log_cash_failure(ERR_CUSTODY_INVALID, operation=operation, company_id=company_id,
                          branch_id=branch_id, account_id=stored_account_id,
                          detail=f"idempotency key reused with another cash account; "
                                 f"requested={requested_account_id}")
    return HTTPException(409, KEY_ACCOUNT_CONFLICT_TEXT, headers=EC.headers(ERR_CUSTODY_INVALID))


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
              f"'{operation}': yopilgan smenaga naqd yozib bo'lmaydi — smena yopilgan yoki "
              "yarashtirilgan. Smena qayta ochilmaydi va hisob-kitob o'zgartirilmaydi; "
              "administrator tekshirsin.",
              company_id=company_id, branch_id=getattr(shift, "branch_id", None),
              shift_id=getattr(shift, "id", None), operation=operation,
              detail=f"shift status={st}, closed_at={getattr(shift, 'closed_at', None)}")


def require_ledger_writable(db: Session, company_id, operation: str, *, status: int = 400) -> None:
    """§1 YAGONA MARKAZIY INVARIANT: ledger-native do'konda ledger YOZIB BO'LMASA, fizik naqd
    amali BIZNES QATORI COMMIT QILINISHIDAN OLDIN baland RAD etiladi.

    NEGA MARKAZIY: `enforcement_active` FAQAT cutover_at ni o'qiydi, dual-write esa
    cash_enabled + mode ga bog'liq — ikki HAR XIL shart. Ular ajralса, gardlar o'tar, ledger legi
    yozilmasdi. Tekshiruvni har endpointga sochib qo'ymaymiz: BARCHA fizik naqd yo'llari
    require_post_t0_till yoki require_custody_account dan o'tadi, shu bois invariant SHU IKKI
    ildizda turadi (shifts, cashops, sales, customers, purchases, receiving — hammasi qamraladi).

    NAQD BO'LMAGAN amallar bu yo'ldan O'TMAYDI, shu bois ular hech qachon bloklanmaydi.
    SQLite/dev ATAYLAB tegilmaydi (u yerda cash quyi tizimi umuman kutilmaydi).

    `status` — naqd savdo yo'li (`services/sales.py`) buni 503 (vaqtinchalik) deb beradi;
    kod, matn va sarlavha AYNI. Ichki sabab (`cash` sxemasi yo'q / rejim LEGACY_ONLY) FAQAT
    jurnalda — operator uchun bu «naqd hisobi hozir yozilmaydi», boshqa hech narsa."""
    from app.services.cash import tenant as _tn
    try:
        _tn.require_ledger_writable(db, company_id)
    except _tn.LedgerUnavailable as e:
        _fail(ERR_LEDGER_UNAVAILABLE,
              f"'{operation}': LEDGER-NATIVE do'kon — naqd hisobi (ledger) hozir yozilmaydi, "
              "naqd amal BAJARILMADI (pul hisobsiz qolmasligi uchun). Administratorga xabar "
              "bering.",
              detail=str(e), company_id=company_id, operation=operation, status=status)


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
              "(kassa TILL yoki seyf SAFE). Filial/kassir bo'yicha TAXMIN QILINMAYDI.",
              company_id=company_id, branch_id=branch_id, operation=operation)
    acc = db.get(CashAccount, account_id)
    if acc is None:
        # ⚠️  `account_id` smenaning `till_id` idan kelgan bo'lishi mumkin (mijoz uni yubormagan)
        #     — matnga EMAS, jurnalga.
        _fail(ERR_CUSTODY_INVALID,
              f"'{operation}': naqd hisob topilmadi. Ro'yxatni yangilab, hisobni qayta tanlang.",
              company_id=company_id, branch_id=branch_id, account_id=account_id,
              operation=operation)
    if str(acc.tenant_id) != str(company_id):
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': naqd hisob boshqa do'konga tegishli.",
              company_id=company_id, branch_id=branch_id, account_id=acc.id, operation=operation,
              detail="account belongs to another tenant")
    if str(acc.status) != "ACTIVE":
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': naqd hisob faol emas ({acc.status}).",
              company_id=company_id, branch_id=branch_id, account_id=acc.id, operation=operation)
    if expect_type is not None and str(acc.type) != expect_type:
        _fail(ERR_CUSTODY_INVALID,
              f"'{operation}': hisob turi {acc.type}, kutilgan {expect_type}.",
              company_id=company_id, branch_id=branch_id, account_id=acc.id, operation=operation)
    if str(acc.type) not in ("TILL", "SAFE"):
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': fizik custody hisobi TILL yoki SAFE bo'lishi kerak.",
              company_id=company_id, branch_id=branch_id, account_id=acc.id, operation=operation)
    if branch_id is not None and str(acc.branch_id) != str(branch_id):
        _fail(ERR_CUSTODY_INVALID, f"'{operation}': naqd hisob boshqa filialga tegishli.",
              company_id=company_id, branch_id=acc.branch_id, account_id=acc.id,
              operation=operation, detail=f"requested branch={branch_id}")
    if currency is not None and str(acc.currency) != str(currency):
        _fail(ERR_CUSTODY_INVALID,
              f"'{operation}': valyuta mos emas ({acc.currency} != {currency}).",
              company_id=company_id, branch_id=branch_id, account_id=acc.id, operation=operation)
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
    sid = getattr(shift, "id", None)

    # §3/§11 LEGACY OCHIQ SMENA T0'NI KESIB O'TDI: smena bor, lekin till_id YO'Q -> QAT'IY RAD.
    if shift is not None and getattr(shift, "till_id", None) is None:
        _fail(ERR_LEGACY_SHIFT_NEEDS_TILL,
              f"T0 (cutover)'dan keyin '{operation}' amali kassasi (TILL) aniqlanmagan LEGACY smenada "
              "bajarilmaydi. Smenani YOPING va aniq kassa (TILL) bilan yangi smena oching. "
              "Kassa avtomatik biriktirilmaydi.",
              company_id=company_id, branch_id=branch_id, shift_id=sid, operation=operation)

    eff = till_id if till_id is not None else getattr(shift, "till_id", None)
    if eff is None:
        _fail(ERR_TILL_REQUIRED,
              f"T0 (cutover)'dan keyin '{operation}' amali AYNAN kassa (TILL) talab qiladi. "
              "Filial/kassir bo'yicha TAXMIN QILINMAYDI — kassani tanlang yoki sozlang.",
              company_id=company_id, branch_id=branch_id, shift_id=sid, operation=operation)

    acc, why = _ti.get_till(db, company_id, eff)       # tenant + type=TILL + ACTIVE
    if acc is None:
        _fail(ERR_TILL_INVALID,
              f"'{operation}': kassa (TILL) yaroqsiz ({why}). Faol (ACTIVE) va shu do'konga tegishli "
              "kassa bo'lishi SHART.",
              company_id=company_id, branch_id=branch_id, shift_id=sid, till_id=eff,
              operation=operation)
    if branch_id is not None and str(acc.branch_id) != str(branch_id):
        _fail(ERR_TILL_INVALID, f"'{operation}': kassa (TILL) boshqa filialga tegishli.",
              company_id=company_id, branch_id=acc.branch_id, shift_id=sid, till_id=acc.id,
              operation=operation, detail=f"requested branch={branch_id}")
    if shift is not None and till_id is not None and str(shift.till_id) != str(till_id):
        _fail(ERR_TILL_SHIFT_MISMATCH,
              f"'{operation}': berilgan kassa ochiq smenaning kassasiga mos emas. Smena "
              "o'rtasida kassa almashtirilmaydi.",
              company_id=company_id, branch_id=branch_id, shift_id=sid, till_id=till_id,
              operation=operation, detail=f"shift.till_id={shift.till_id}")
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
    sid = getattr(shift, "id", None) if shift is not None else None

    if shift is not None and shift_till is not None:
        # SMENAGA BOG'LANGAN: drawer smenadan keladi; chaqiruvchi override QILA OLMAYDI.
        if cash_account_id is not None and str(cash_account_id) != str(shift_till):
            _fail(ERR_TILL_SHIFT_MISMATCH,
                  f"'{operation}': berilgan naqd hisob ochiq smenaning kassasiga mos emas. "
                  "Smenaga bog'langan naqd uchun kassani almashtirib bo'lmaydi.",
                  company_id=company_id, branch_id=branch_id, shift_id=sid, till_id=shift_till,
                  account_id=cash_account_id, operation=operation)
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
              "bajarilmaydi. Smenani YOPING va aniq kassa (TILL) bilan yangi smena oching.",
              company_id=company_id, branch_id=branch_id, shift_id=sid, operation=operation)

    # SMENASIZ: explicit hisob SHART (post-T0), pre-T0 esa berilgan bo'lsa ISHLATILADI.
    if cash_account_id is None:
        if not enforced:
            return None, False              # pre-T0 legacy: eski xatti-harakat, TAXMIN YO'Q
        _fail(ERR_CUSTODY_REQUIRED,
              f"'{operation}': T0 (cutover)'dan keyin smenasiz naqd amali uchun naqd hisob (kassa TILL "
              "yoki seyf SAFE) AYNAN ko'rsatilishi SHART — `cash_account_id` yuboring. "
              "Filial/kassir bo'yicha TAXMIN QILINMAYDI.",
              company_id=company_id, branch_id=branch_id, operation=operation)
    acc = require_custody_account(db, company_id=company_id, branch_id=branch_id,
                                  account_id=cash_account_id, operation=operation,
                                  currency=currency)
    return acc, True
