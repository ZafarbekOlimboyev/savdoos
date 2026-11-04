# -*- coding: utf-8 -*-
"""BARQAROR XATO KODLARI — partiya yo'lidagi ichki nomuvofiqliklar.

NEGA KOD MATNGA QO'SHILMAYDI
============================
`detail` — operatorga ko'rsatiladigan MATN va ayni paytda tarjima lug'atining
KALITI (`packages/shared/src/lib/serverErrorsLots.ts`). «LOT_...: matn» prefiksi
o'rnatilgan eski POS/Manager'da kod tokenini ekranga chiqarardi va lug'at
qidiruvini buzardi. Shu bois kod QO'SHIMCHA va MATNDAN TASHQARIDA yuradi:

  · javob sarlavhasi `X-Error-Code` (`main.py` CORS `expose_headers` da ochilgan —
    aks holda Electron renderer uni o'qiy olmasdi);
  · `/sync/push` natijasidagi `code` maydoni;
  · server jurnali — har doim.

⚠️  KOD QIYMATI O'ZGARMAYDI: mijoz va qo'llab-quvvatlash unga tayanadi. Yangi
    holat — yangi konstanta; eskisini qayta nomlash EMAS.

⚠️  HTTP HOLATI KODDAN KELIB CHIQMAYDI. Bu yerdagi hamma holat 409 bo'lib
    qoladi: `/sync/push` 409 ni TRANZIENT deb biladi (pul olingan offline chek
    outbox'da qoladi), POS esa sotuvdagi 409 da katalogni yangilaydi.
"""

HEADER = "X-Error-Code"

# Partiya/qoldiq YAKUNIY DARVOZASI buzildi: sotuv, hisobdan chiqarish, sanoq,
# kuzatuvni yoqish, kirim, qaytarish.
LOT_INVARIANT_BROKEN = "LOT_INVARIANT_BROKEN"
# Qaytarish yozgan qatorlar partiya/qarz chegarasidan oshardi (`lot_return.assert_caps`).
LOT_RETURN_CAPS_VIOLATED = "LOT_RETURN_CAPS_VIOLATED"
# Qaytarish rejasida taxminiy partiya ulushi aniq summadan katta — DASTURIY invariant.
LOT_COST_BASIS_INCONSISTENT = "LOT_COST_BASIS_INCONSISTENT"
# Chek partiya kuzatuvi YOQILISHIDAN OLDIN sotilgan — omborga qaytarish (restock) rad
# etildi (`lot_return.pre_activation_line`). Restock'siz qaytarish RUXSAT etiladi.
LOT_RETURN_PRE_ACTIVATION = "LOT_RETURN_PRE_ACTIVATION"
# Qarzni yopishning yakuniy darvozasi buzildi.
LOT_RESOLVE_INVARIANT_BROKEN = "LOT_RESOLVE_INVARIANT_BROKEN"
# Kuzatuvni yoqish darvozasi: BAZA sxemasi tayyor emas (yaxlitlik, idempotentlik
# indekslari yoki uuid ustun tipi). Ma'lumot BUZILMAGAN — yangi partiya tarixi
# shunchaki tug'ilmaydi; operator `/health/ready` ni yashil qilgach qayta uradi.
LOT_SCHEMA_NOT_READY = "LOT_SCHEMA_NOT_READY"

# ══ QABULNI TUZATISH (Phase 5D) ═════════════════════════════════════════════
#
# ⚠️  HAMMASI 409: bular ma'lumot xatosi emas, HOLAT ziddiyati — operator
#     hujjatni yoki javonni o'zgartirmaguncha so'rov qayta yuborilsa ham AYNI
#     javob qaytadi. Shakl xatolari (noto'g'ri partiya, ortiqcha kasr xona)
#     avvalgidek 400 bo'lib qoladi va ularning barqaror kodi YO'Q.

# Qabul hujjati partiya TUG'DIRMAGAN — tuzatiladigan kogorta yo'q. Operator
# oddiy kirim tahririga (`PATCH /purchases/{id}`) yo'naltiriladi.
LOT_CORRECTION_NOT_TRACKED = "LOT_CORRECTION_NOT_TRACKED"
# Partiya TEGILGAN (sotilgan / qaytarilgan / harakatga tushgan) — uning
# IDENTIFIKATSIYASINI (narx, muddat, partiya raqami) tuzatib bo'lmaydi: tarixiy
# COGS surati o'sha lahzada muzlatilgan va qayta yozilmaydi.
LOT_CORRECTION_CONSUMED = "LOT_CORRECTION_CONSUMED"
# Teskari qilinayotgan miqdor partiya qoldig'idan katta — jismoniy partiya
# MANFIYGA tushmaydi.
LOT_CORRECTION_EXCEEDS_REMAINING = "LOT_CORRECTION_EXCEEDS_REMAINING"
# Mahsulotda YOPILMAGAN atributsiya qarzi bor (`lot_shortfalls`): qaysi partiya
# ketgani hali noma'lum, shu bois hujjat kogortalarini tuzatish qarzni jimgina
# boshqa partiyaga surib qo'yardi.
LOT_CORRECTION_SHORTFALL_OPEN = "LOT_CORRECTION_SHORTFALL_OPEN"
# Naqd hujjat summasi o'zgardi, lekin kassa ledgeriga oyoq YOZILMADI (legacy
# tenant / mos OUT leg yo'q). Kassa tegilmagan holda «bajarildi» deb javob
# berish MUMKIN EMAS — amal butunlay bekor qilinadi.
LOT_CORRECTION_CASH_UNPOSTABLE = "LOT_CORRECTION_CASH_UNPOSTABLE"
# Ayni `client_uuid` BOSHQA mazmun bilan keldi — bu takror emas, mijoz xatosi.
LOT_CORRECTION_REPLAY_CONFLICT = "LOT_CORRECTION_REPLAY_CONFLICT"
# Hujjatda tuzatish bor — eski kirim tahriri (`PATCH /purchases/{id}`) jamini
# `purchase_items` dan QAYTA hisoblaydi va tuzatishni JIMGINA teskari qilardi.
LOT_CORRECTION_DOC_LOCKED = "LOT_CORRECTION_DOC_LOCKED"


def headers(code: str) -> dict:
    """`HTTPException(409, "<matn>", headers=headers(KOD))` uchun."""
    return {HEADER: code}


# ══ PHASE 5G — SHAKL XATOLARIGA BARQAROR KOD (mobil ilova uchun) ═════════════
#
# ⚠️  Phase 5G.1 dan boshlab QABULNI TUZATISH yo'li (`/receiving/{id}/corrections`)
#     ham shakl kodlarini `X-Error-Code` da beradi (`lot_correction` ilgari
#     `LotSelectionError.code` / `LotPayloadError.code` ni tashlab yuborardi va
#     zona 409 kodsiz edi). MATN va HTTP HOLATI o'zgarmagan — Phase 5D
#     shartnomasining o'sha qismi saqlanadi; faqat sarlavha qo'shildi. Mobil ilova
#     (`apps/mobile`) serverning o'zbekcha matnini ru/ky/uzc ga tarjima qilishi
#     kerak va matnni regex bilan o'qish mo'rt: shu bois quyidagi yo'llar kodni
#     QO'SHIMCHA beradi.
#
# ⚠️  MATN VA HTTP HOLATI O'ZGARMAYDI. 400 — 400 bo'lib, 409 — 409 bo'lib qoladi;
#     kod faqat `X-Error-Code` sarlavhasiga qo'shiladi. Desktop (`api.ts`) matn
#     bo'yicha tarjima qilishda davom etadi va bu sarlavhani e'tiborsiz qoldiradi.
#
# Qo'llanadigan yo'llar: `POST /receiving/commit`, `POST /inventory/count`,
# `POST /inventory/writeoff`, `POST /inventory/transfer` va `require`/`require_any`.

# Kuzatuvli mahsulot qatori/amali partiyasiz keldi (kirim `lots`, hisobdan
# chiqarish `lots`, sanoq `lots`/`new_lots`).
LOT_LINES_REQUIRED = "LOT_LINES_REQUIRED"
# Kuzatuvsiz mahsulotga partiya yuborildi.
LOT_LINES_FORBIDDEN = "LOT_LINES_FORBIDDEN"
# Kirim: partiyalar yig'indisi qator miqdoriga TENG EMAS; hisobdan chiqarish:
# partiyalar yig'indisi umumiy miqdorga TENG EMAS.
LOT_QTY_SUM_MISMATCH = "LOT_QTY_SUM_MISMATCH"
# Miqdorda uchtadan ORTIQ kasr xonasi (NUMERIC(14,3)); jimgina yaxlitlanmaydi.
LOT_QTY_PRECISION = "LOT_QTY_PRECISION"
# Muddat kuzatiladigan mahsulot partiyasida `expiry_date` yo'q.
LOT_EXPIRY_REQUIRED = "LOT_EXPIRY_REQUIRED"
# Muddat KUZATILMAYDIGAN mahsulot partiyasida `expiry_date` bor.
LOT_EXPIRY_FORBIDDEN = "LOT_EXPIRY_FORBIDDEN"
# Kirimdagi muddat filial biznes sanasidan OLDIN.
LOT_EXPIRED = "LOT_EXPIRED"
# Filial vaqt zonasi TASDIQLANMAGAN (409, holat ziddiyati).
LOT_TZ_NOT_CONFIRMED = "LOT_TZ_NOT_CONFIRMED"
# Hisobdan chiqarish/sanoqda ko'rsatilgan partiya yaroqsiz: topilmadi, ikki marta,
# boshqa mahsulot/filial, holati miqdor tashimaydi, miqdor musbat emas.
LOT_SELECTION_INVALID = "LOT_SELECTION_INVALID"
# Partiyadan uning qoldig'idan KO'P ayirilmoqda.
LOT_INSUFFICIENT_REMAINING = "LOT_INSUFFICIENT_REMAINING"
# Sanoq: tegilmagan + sanalgan + yangi partiyalar e'lon qilingan jamiga TENG EMAS.
LOT_COUNT_SUM_MISMATCH = "LOT_COUNT_SUM_MISMATCH"
# Filiallararo ko'chirish kuzatuvli mahsulotni qo'llab-quvvatlamaydi (409).
TRANSFER_TRACKED_UNSUPPORTED = "TRANSFER_TRACKED_UNSUPPORTED"
# `require`/`require_any` darvozasi rad etdi (403). Matn: «Ruxsat yo'q: <kod>».
PERMISSION_DENIED = "PERMISSION_DENIED"
# Naqd amal ochiq smenani talab qiladi, smena esa yo'q (400): inkassa
# (`POST /cash/ops`) va `force_shift` yoqilgan do'kondagi naqd qarz to'lovi.
# `GET /cash/custody-preview` ham BLOCKED holatida `reason` sifatida shu kodni beradi.
OPEN_SHIFT_REQUIRED = "OPEN_SHIFT_REQUIRED"

# P9: kassa SOATI offline savdo uchun ishonchsiz — `GET /shifts/offline-sale-policy` shu
# sabab bilan BLOCKED qaytaradi. Ochiq smena BOR, lekin qurilma soati chek vaqtini smena
# oynasidan tashqariga chiqaradi (orqada) yoki `sync.py::_clamp_sold_at` oynasidan oldinga
# o'tib ketadi — replay 400 olardi. PUL OLINISHIDAN OLDIN to'siladi.
DEVICE_CLOCK_UNRELIABLE = "DEVICE_CLOCK_UNRELIABLE"

# ══ P9 KRITIK TUZATISH 1 ═════════════════════════════════════════════════════

# P9-01: `/sync/push` yozuvida BARDOSHLI idempotentlik kaliti yo'q (400, DOIMIY).
#
# ⚠️  NEGA DOIMIY (400, `retry:false`). Kalitsiz chekni qayta yuborishning ma'nosi
#     YO'Q: server uni hech qachon takror deb taniy olmaydi, shu bois har urinish
#     YANGI sotuv va YANGI stok chiqimi yozardi. Retry qilish nuqsonni ko'paytiradi.
#     Klient uni dead-letter'ga qo'yadi va kassir ko'radi.
#
# ⚠️  ONLAYN `/sales` BU KODNI BERMAYDI. U yerda kalit ixtiyoriy bo'lib qoladi
#     (eski POS/mobil/panel yo'llari) — javob yo'qolishi xavfi faqat offline
#     navbatga tegishli, chunki AYNAN u qayta yuboradi.
SYNC_IDEMPOTENCY_KEY_REQUIRED = "SYNC_IDEMPOTENCY_KEY_REQUIRED"

# R6.8 P0-1: shu filialda AYNI mahsulot/miqdor/sabab bilan chiqarish JUDA
# YAQINDA yozilgan, lekin BOSHQA `client_uuid` bilan (409).
#
# ⚠️  BU DEDUP EMAS. Amal jimgina yutilmaydi va «ok» ham deyilmaydi: mijoz
#     operatorga oldingi chiqarishni KO'RSATADI va u TASDIQLASA
#     (`confirm_duplicate=true`) ikkinchi yozuv BAJARILADI. Bir xil
#     mahsulot/miqdor/sabab bilan ikkita HAQIQIY, alohida chiqarish qonuniy
#     bo'lishi mumkin — shu bois qaror OPERATORDA, serverda emas.
#
# ⚠️  NEGA KERAK. Ikki marta yozishga qarshi yagona to'siq mijozdagi muzlagan
#     `client_uuid` edi va u widget `State` ichida yashardi: 401, qulf, crash
#     yoki fonda o'ldirish uni yo'q qilardi, operator amalni qaytadan
#     kiritardi va YANGI tasodifiy kalit serverda YANGI, qabul qilinadigan
#     write-off bo'lardi — qoldiq va tannarx IKKI MARTA chiqardi.
WRITEOFF_DUPLICATE_SUSPECTED = "WRITEOFF_DUPLICATE_SUSPECTED"

# Idempotentlik kaliti (`client_uuid`) BOSHQA amal uchun qayta ishlatilgan (409).
#
# ⚠️  Bu «dublikat» EMAS. Ayni kalit bilan kelgan so'rovning MODDIY maydonlari
#     (tur, summa, izoh; POS yo'lida SMENA ham) saqlangan amalnikidan farq qilsa,
#     bu TAKROR emas — yangi amal. U YOZILMAYDI (kalit band) va «ok» ham DEYILMAYDI:
#     aks holda kassir pulni yozildi deb o'ylardi, holbuki hech narsa yozilmagan.
#     Mijoz yangi kalit bilan qaytadan yuborishi kerak.
IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
# Kassa amali baza cheklovi tufayli YOZILMADI (409) — «dublikat» deb aytib bo'lmaydi,
# chunki bu do'konda shu kalitli qator YO'Q (masalan boshqa tenantning kaliti bilan
# global noyoblik to'qnashuvi). Jurnalga `log_cash_failure` yoziladi.
CASH_OP_WRITE_FAILED = "CASH_OP_WRITE_FAILED"

# ══ PHASE 5G.1 — XATO GIGIYENASI ═════════════════════════════════════════════
#
# Nakladnoy skanini AI o'qiy olmadi (`POST /receiving/scan`, 502). Yuqori oqim
# (provayder/kutubxona) matni operatorga UZATILMAYDI — u jurnalda; mijoz kod + «qayta
# urinib ko'ring yoki qo'lda kiriting» jumlasini oladi.
AI_SCAN_FAILED = "AI_SCAN_FAILED"
# Nakladnoy rasmi TASHQI AI ga yuboriladi, lekin do'kon bunga hali ROZILIK
# BERMAGAN — yoki rozilik BOSHQA provayder/oshkor etish versiyasi uchun berilgan
# (CH-16). FAIL-CLOSED: rozilik yo'q bo'lsa rasm chiqmaydi va operator qo'lda
# kirim yo'li bilan ishlashda davom etadi.
AI_CONSENT_REQUIRED = "AI_CONSENT_REQUIRED"
# Mijoz dialogda KO'RSATGAN AI talabi (provayder / oshkor etish hujjati va uning
# reviziyasi) server holati bilan MOS KELMADI — konfiguratsiya GET va POST
# orasida o'zgargan (R7.1). FAIL-CLOSED: rozilik BOSHQA talab uchun
# YOZILMAYDI va rasm uzatilmaydi; mijoz talabni qayta o'qib, yangi matnni
# ko'rsatadi. Mobil klient bu kod uchun tarjimani ALLAQACHON olib yuradi
# (`apps/mobile/lib/errors.dart`).
AI_REQUIREMENT_CHANGED = "AI_REQUIREMENT_CHANGED"
# Rasm darvozadan o'tmadi: tur BAYTLAR bo'yicha aniqlanmadi/qo'llanmaydi, yoki
# o'lcham/hajm chegarasidan chiqdi (`services/image_guard.py`). Shakl xatosi -> 400.
AI_IMAGE_REJECTED = "AI_IMAGE_REJECTED"
# 1C/katalog importi baza xatosi bilan yiqildi (500). SQLAlchemy matni (SQL +
# PARAMETRLAR) na operatorga, na `import_jobs.error` ustuniga tushadi — u jurnalда
# (`log.exception`), mijozда esa barqaror jumla + shu kod. Yozuv QISMAN QOLMAYDI.
CATALOG_IMPORT_FAILED = "CATALOG_IMPORT_FAILED"
# ══ KATALOG v2 / RESET — «NAQD OILASI» konvensiyasi ══════════════════════════
#
# Bu uchtasi `detail = "KOD: matn"` shaklida yuradi (kassa gardi naqshi), chunki matn
# QO'LDA yozilgan OPERATOR TASHXISI: snapshot hash'lari, job id, «reset tokeni BOSHQA
# do'konga tegishli», «mazmun: …» va yana bir necha xil aniq sabab. Auditoriya —
# vendor-admin (`require_vendor`), do'kon egasi EMAS.
#
# ⚠️  ILGARI BU UCHALASI BIRORTA REGISTRDA YO'Q EDI (na bu fayl, na
#     `cutover_guard.ERROR_CODES`) va sarlavha ham berilmasdi — ya'ni mijoz kodni
#     dasturiy taniy olmasdi. Endi ro'yxatda va `X-Error-Code` da ham yuradi.
# ⚠️  QIYMAT O'ZGARMAYDI (yuqoridagi qoida): mijoz va qo'llab-quvvatlash shu tokenga
#     tayanadi, mavjud testlar ham shu substringni talab qiladi.
SNAPSHOT_CONFLICT = "SNAPSHOT_CONFLICT"
IMPORT_IN_PROGRESS = "IMPORT_IN_PROGRESS"
RESET_TOKEN_STALE = "RESET_TOKEN_STALE"
#
# Kassa gardi kodlari (`CASH_CUSTODY_*`, `TILL_*`, `LEGACY_SHIFT_*`, `CASH_LEDGER_UNAVAILABLE`,
# `CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY`) `services/cash/cutover_guard.ERROR_CODES` da
# turadi (matn prefiksi — eski mijozlar uchun) va 5G.1 dan `X-Error-Code` da HAM yuradi.
