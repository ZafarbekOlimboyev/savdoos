/// Operator-facing error messages.
///
/// The server answers in Uzbek-Latin technical text, sometimes with a stable
/// code (`X-Error-Code` header, a `CASH_*:` prefix or a dict `detail.error`).
/// [userMessage] turns ANY error into one short localized sentence:
///
///  1. transport / auth / 422 / 5xx failures get fixed messages (a 422 never
///     shows raw JSON, a 5xx never shows a stack trace);
///  2. cash codes win over their technical text;
///  3. known server texts (ported from the desktop dictionaries
///     `serverErrorsLots.ts` / `serverErrorsCash.ts` / `serverErrors.ts`, only
///     the ones the mobile flows can hit) are translated, keeping data such as
///     product names and quantities; a `"<product>: "` prefix is preserved;
///  4. other stable codes (LOT_*, LOT_CORRECTION_*, PRINT_*, RECEIPT_*,
///     PERMISSION_DENIED, cash posting codes) get their own message;
///  5. unknown business text is shown only after removing UUIDs, and anything
///     that looks like an internal failure (Traceback, SQL, psycopg,
///     sqlalchemy, stock_invariant) becomes a generic message.
///
/// ⚠️  Server texts below must match the backend EXACTLY (they are copied from
///     `apps/server/app/**`); a changed backend text silently falls back to
///     step 5 (shown untranslated, never raw JSON).
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'api.dart';
import 'l10n.dart';
import 'permissions.dart' show permissionLabel;

// ── Fixed messages (tr keys) ────────────────────────────────────────────────
const String _kNetwork = 'Server bilan aloqa yo‘q. Internetni tekshirib, qayta urinib ko‘ring.';
const String _kTimeout = 'Server o‘z vaqtida javob bermadi. Aloqani tekshirib, qayta urinib ko‘ring.';
const String _kAuth = 'Sessiya tugadi — qayta kiring';
const String _kValidation = 'Ma’lumotlar noto‘g‘ri to‘ldirilgan — maydonlarni tekshirib, qayta urinib ko‘ring.';
const String _kServer = 'Serverda vaqtincha nosozlik. Birozdan so‘ng qayta urinib ko‘ring.';
const String _kBadResponse = 'Serverdan kutilmagan javob keldi — internet ulanishini tekshiring.';
const String _kPermission = 'Bu amal uchun ruxsatingiz yo‘q.';
const String _kUnexpected = 'Kutilmagan xatolik yuz berdi. Qayta urinib ko‘ring.';
const String _kStatus = 'Xatolik ({status}). Qayta urinib ko‘ring.';
const String _kWrongCurrentServer = "Joriy kredensial noto'g'ri";
const String _kWrongCurrent = 'Joriy parol (yoki PIN) noto‘g‘ri.';

/// Stable code -> Uzbek message (tr key). Codes whose server text is technical.
const Map<String, String> codeMessages = {
  // ── Lot shape gates (Phase 5G, X-Error-Code) ──
  'LOT_LINES_REQUIRED':
      'Partiya bo‘yicha kuzatiladigan mahsulot uchun har qatorga partiyalarni kiriting.',
  'LOT_LINES_FORBIDDEN': 'Bu mahsulot partiya bo‘yicha kuzatilmaydi — partiya kiritib bo‘lmaydi.',
  'LOT_QTY_SUM_MISMATCH': 'Partiyalar yig‘indisi qator miqdoriga teng emas.',
  'LOT_QTY_PRECISION': 'Miqdor 0,001 aniqlikda kiritiladi — uchtadan ortiq kasr xona bo‘lmasin.',
  'LOT_EXPIRY_REQUIRED': 'Bu mahsulot muddat bo‘yicha kuzatiladi — har partiyaga yaroqlilik muddatini kiriting.',
  'LOT_EXPIRY_FORBIDDEN': 'Bu mahsulot muddat bo‘yicha kuzatilmaydi — muddat kiritib bo‘lmaydi.',
  'LOT_EXPIRED': 'Muddati o‘tgan tovar qabul qilinmaydi — muddat bugungi ish kunidan oldin.',
  'LOT_TZ_NOT_CONFIRMED':
      'Filial vaqt zonasi tasdiqlanmagan — muddatli partiyalarni yozib bo‘lmaydi. Administrator zonani tasdiqlasin.',
  'LOT_SELECTION_INVALID':
      'Tanlangan partiya yaroqsiz (boshqa mahsulot yoki filialga tegishli yoki yopilgan). Ro‘yxatni yangilab, qayta tanlang.',
  'LOT_INSUFFICIENT_REMAINING': 'Partiyada yetarli qoldiq yo‘q — miqdorni kamaytiring yoki ro‘yxatni yangilang.',
  'LOT_COUNT_SUM_MISMATCH': 'Partiyalar bo‘yicha sanoq yig‘indisi umumiy sanoqqa teng emas.',
  'TRANSFER_TRACKED_UNSUPPORTED': 'Partiya bo‘yicha kuzatiladigan mahsulotni filiallararo ko‘chirib bo‘lmaydi.',
  'PERMISSION_DENIED': _kPermission,
  // ── Lot invariants (409) ──
  'LOT_INVARIANT_BROKEN':
      'Partiya va qoldiq mos kelmadi — amal BAJARILMADI. Qo‘llab-quvvatlashga murojaat qiling.',
  'LOT_RETURN_CAPS_VIOLATED': 'Qaytarish partiya chegarasidan oshardi — amal bajarilmadi.',
  'LOT_COST_BASIS_INCONSISTENT': 'Partiya tannarxi mos kelmadi — amal bajarilmadi. Qo‘llab-quvvatlashga murojaat qiling.',
  'LOT_RETURN_PRE_ACTIVATION': 'Bu tovar partiya hisobi yoqilishidan oldin sotilgan — omborga qaytarmasdan qaytaring.',
  'LOT_RESOLVE_INVARIANT_BROKEN': 'Qarzni yopib bo‘lmadi — partiya va qoldiq mos kelmadi. Qo‘llab-quvvatlashga murojaat qiling.',
  'LOT_SCHEMA_NOT_READY': 'Server partiya hisobiga hali tayyor emas — administratorga xabar bering.',
  // ── Receiving corrections (Phase 5D, 409) ──
  'LOT_CORRECTION_NOT_TRACKED': 'Bu qabul partiya yaratmagan — tuzatish faqat partiyali qabul uchun.',
  'LOT_CORRECTION_CONSUMED':
      'Partiyadan tovar allaqachon harakatlangan — uning raqami, muddati va narxini tuzatib bo‘lmaydi; faqat miqdorni qaytarish mumkin.',
  'LOT_CORRECTION_EXCEEDS_REMAINING': 'Qaytarilayotgan miqdor partiya qoldig‘idan katta.',
  'LOT_CORRECTION_SHORTFALL_OPEN': 'Mahsulotda yopilmagan partiya qarzi bor — avval qarzni partiyaga bog‘lang.',
  'LOT_CORRECTION_CASH_UNPOSTABLE':
      'Kassa yozuvini yozib bo‘lmadi — tuzatish BEKOR qilindi. Qo‘llab-quvvatlashga murojaat qiling.',
  'LOT_CORRECTION_REPLAY_CONFLICT':
      'Bu so‘rov avval boshqa mazmun bilan yuborilgan. Hujjatni yangilab, tuzatishni qayta yuboring.',
  'LOT_CORRECTION_DOC_LOCKED': 'Hujjat tuzatilgan — uni faqat yangi tuzatish orqali o‘zgartirish mumkin.',
  // ── Cash cutover guard ("CODE: text", 400/409) ──
  'CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER':
      'Naqd amal uchun pul manbaini (kassa yoki seyf) tanlang. Kassirda ochiq smena bo‘lsa, manba o‘sha smenaning kassasi bo‘ladi.',
  'CASH_CUSTODY_ACCOUNT_INVALID':
      'Naqd hisob bu amalga to‘g‘ri kelmaydi: u faol emas yoki boshqa filialga tegishli. Ochiq smenangiz boshqa filialda bo‘lsa — smenani yoping yoki hujjatni o‘sha filial xodimi rasmiylashtirsin.',
  'CASH_LEDGER_UNAVAILABLE':
      'Naqd hisobi vaqtincha ishlamayapti — amal BAJARILMADI. Administratorga xabar bering.',
  'TILL_REQUIRED_AFTER_CUTOVER': 'Kassa tanlanmagan. Smenani aniq kassa tanlab oching.',
  'TILL_INVALID_AFTER_CUTOVER': 'Kassa yaroqsiz (faol emas yoki boshqa filialga tegishli).',
  'TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER':
      'Bu amal ochiq smena kassasiga mos emas. Smena o‘rtasida kassa almashtirilmaydi.',
  'LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER':
      'Smena eski usulda (kassasiz) ochilgan. Uni yopib, kassa tanlab yangi smena oching.',
  'CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY':
      'Bu amal yopilgan smenaga tegishli — avtomatik qabul qilinmaydi. Administrator tekshirsin.',
  'OPEN_SHIFT_REQUIRED': 'Bu naqd amal uchun kassada ochiq smena kerak — avval smenani oching.',
  'CUSTODY_UNKNOWN_MODE':
      'Naqd hisob holatini aniqlab bo‘lmadi — amal to‘xtatildi. Ilovani yangilang yoki administratorga xabar bering.',
  'CASH_OP_WRITE_FAILED': 'Kassa amali yozilmadi. Qayta urinib ko‘ring; takrorlansa administratorga xabar bering.',
  // Kalit boshqa amal uchun ishlatilgan: BU AMAL YOZILMADI (server 409). Operator
  // ro'yxatni tekshirib, amalni QAYTADAN kiritadi — ayni tanani qayta yuborish
  // foydasiz (kalit band).
  'IDEMPOTENCY_KEY_REUSED':
      'Bu amal yozilmadi — so‘rov kaliti boshqa amalga ishlatilgan. Ro‘yxatni tekshiring va amalni qaytadan kiriting.',
  // ── Cash posting service (dict detail {error, message}) ──
  'INSUFFICIENT_CASH': 'Kassada yetarli naqd pul yo‘q.',
  'NEGATIVE_APPROVAL_REQUIRED': 'Amal kassani manfiyga tushiradi — administrator tasdig‘i kerak.',
  'ACCOUNT_ARCHIVED': 'Naqd hisob arxivlangan — boshqa hisobni tanlang.',
  'ACCOUNT_NOT_FOUND': 'Naqd hisob topilmadi — ro‘yxatni yangilang.',
  'CURRENCY_MISMATCH': 'Hisob valyutasi amal valyutasiga mos emas.',
  'SHIFT_NOT_OPEN': 'Smena ochiq emas.',
  'UNAUTHORIZED_OPERATION': 'Bu naqd amal uchun ruxsatingiz yo‘q.',
  'TENANT_MISMATCH': 'Naqd hisob bu do‘konga tegishli emas — ro‘yxatni yangilang.',
  'INVALID_TIMESTAMP': 'Amal vaqti noto‘g‘ri — telefondagi sana va vaqtni tekshiring.',
  'SHIFT_NOT_FOUND': 'Smena topilmadi — ma’lumotlarni yangilang.',
  'SHIFT_NOT_BELONG_TO_ACCOUNT': 'Smena tanlangan kassaga tegishli emas.',
  'ALREADY_REVERSED': 'Bu naqd amal allaqachon bekor qilingan.',
  'INVALID_REVERSAL': 'Bu naqd amalni bekor qilib bo‘lmaydi.',
  'INVALID_TRANSFER': 'Pul o‘tkazmasi noto‘g‘ri — manba va qabul qiluvchi hisobni tekshiring.',
  'INVALID_ACCOUNT_TYPE': 'Bu amal uchun bunday turdagi naqd hisobni ishlatib bo‘lmaydi.',
  'INVALID_INPUT': 'Naqd amal ma’lumotlari noto‘g‘ri — summani tekshiring.',
  'DUPLICATE_REQUEST': 'Bu naqd amal allaqachon yozilgan — ro‘yxatni yangilang.',
  'DUPLICATE_BUSINESS_LEG': 'Bu naqd amal allaqachon yozilgan — ro‘yxatni yangilang.',
  // ── Receipts / printing (Phase 5F) ──
  'RECEIPT_SCOPE_COMPANY_FORBIDDEN':
      'Kompaniya chek shablonini faqat barcha filiallarga kirishi bor xodim o‘zgartiradi.',
  'PRINT_ORIGINAL_EXISTS': 'Bu hujjatning asl cheki allaqachon chop etilgan — nusxa chop eting.',
  'PRINT_JOB_FINAL': 'Chop etish holati yakunlangan — o‘zgartirib bo‘lmaydi.',
  'PRINT_JOB_INVALID': 'Chop etish so‘rovi noto‘g‘ri.',
  'PRINT_JOB_BUSY': 'Bu chek hozir boshqa qurilmada chop etilmoqda — nusxa chop eting.',
};

/// Codes whose server TEXT is technical: the code message is shown first.
bool _codeFirst(String code) =>
    ApiException.prefixCodes.contains(code) ||
    code.startsWith('CASH_') ||
    const {
      'INSUFFICIENT_CASH',
      'NEGATIVE_APPROVAL_REQUIRED',
      'ACCOUNT_ARCHIVED',
      'ACCOUNT_NOT_FOUND',
      'CURRENCY_MISMATCH',
      'SHIFT_NOT_OPEN',
      'UNAUTHORIZED_OPERATION',
      'TENANT_MISMATCH',
      'INVALID_TIMESTAMP',
      'SHIFT_NOT_FOUND',
      'SHIFT_NOT_BELONG_TO_ACCOUNT',
      'ALREADY_REVERSED',
      'INVALID_REVERSAL',
      'INVALID_TRANSFER',
      'INVALID_ACCOUNT_TYPE',
      'INVALID_INPUT',
      'DUPLICATE_REQUEST',
      'DUPLICATE_BUSINESS_LEG',
      'LOT_CORRECTION_REPLAY_CONFLICT',
    }.contains(code);

/// Exact backend texts -> Uzbek message (tr key).
const Map<String, String> _static = {
  // Framework defaults (route missing on an older server).
  'Not Found': 'Server bu so‘rovni tanimadi — server yangilanishi kerak bo‘lishi mumkin.',
  'Method Not Allowed': 'Server bu so‘rovni tanimadi — server yangilanishi kerak bo‘lishi mumkin.',
  // Auth / scope
  'Sessiya tugadi — qayta kiring': _kAuth,
  "Do'kon vaqtincha to'xtatilgan. Vendor bilan bog'laning.":
      'Do‘kon vaqtincha to‘xtatilgan. Xizmat ko‘rsatuvchi bilan bog‘laning.',
  'Filial topilmadi': 'Filial topilmadi',
  'filial topilmadi': 'Filial topilmadi',
  "Filial nofaol — amal bajarib bo'lmaydi": 'Filial nofaol — amalni bajarib bo‘lmaydi',
  "Ruxsat yo'q: bu filial sizga biriktirilmagan": 'Bu filial sizga biriktirilmagan',
  "Ruxsat yo'q: manba filial sizga biriktirilmagan": 'Manba filial sizga biriktirilmagan',
  'Bir xil filial tanlandi': 'Bir xil filial tanlandi — boshqa filialni tanlang',
  'Kamida bitta mahsulot kerak': 'Kamida bitta mahsulot kerak',
  // Busy (retry)
  'Ombor band — sanoqni qayta yuboring': 'Ombor band — sanoqni qayta yuboring',
  "Ko'chirish band — qayta urinib ko'ring": 'Ko‘chirish band — qayta urinib ko‘ring',
  "Qabul hujjati band — qayta urinib ko'ring": 'Qabul hujjati band — qayta urinib ko‘ring',
  "Xarid hujjati band — qayta urinib ko'ring": 'Xarid hujjati band — qayta urinib ko‘ring',
  "Kassa band — qayta urinib ko'ring": 'Kassa band — qayta urinib ko‘ring',
  // Cash ops
  "Ochiq smena yo'q — avval kassada smena oching": 'Ochiq smena yo‘q — avval kassada smena oching',
  "Inkassa: manba va manzil bir xil hisob bo'lishi mumkin emas":
      'Inkassatsiya: manba va manzil bir xil hisob bo‘lishi mumkin emas',
  // Common validation (`app/core/validate.py`, `sales.py`)
  "Telefon raqami noto'g'ri. Masalan: +996 700 123 456": 'Telefon raqami noto‘g‘ri. Masalan: +996 700 123 456',
  "Bo'sh so'rov": 'So‘rov bo‘sh — qidiruv matnini kiriting.',
  // Own password (`POST /auth/password`)
  "Parolni o'zingiz o'rnata olmaysiz — administratorga murojaat qiling":
      'Parolni o‘zingiz o‘rnata olmaysiz — administratorga murojaat qiling.',
  "Parol o'rnatish uchun avval telefon (login) qo'shilishi kerak":
      'Parol o‘rnatish uchun avval telefon (login) qo‘shilishi kerak.',
  'Bu telefon boshqa akkauntda band': 'Bu telefon raqami boshqa akkauntda band.',
  // Customers
  'Mijoz topilmadi': 'Mijoz topilmadi',
  "Bu telefon do'konda allaqachon band": 'Bu telefon raqami do‘konda allaqachon band',
  "Mijoz yaratishda to'qnashuv — qayta urining": 'Mijoz yaratishda to‘qnashuv — qayta urinib ko‘ring',
  "Hisob-kitobi ochiq (qarz yoki avans) mijozni o'chirib bo'lmaydi":
      'Hisob-kitobi ochiq (qarz yoki avans) mijozni o‘chirib bo‘lmaydi',
  "Summa noto'g'ri": 'Summa noto‘g‘ri',
  "Qarz yo'q": 'Qarz yo‘q',
  "Naqd qarz to'lovi uchun ochiq smena kerak — avval smenani oching":
      'Naqd qarz to‘lovi uchun ochiq smena kerak — avval smenani oching',
  // Suppliers / purchases
  'Yetkazib beruvchi topilmadi': 'Yetkazib beruvchi topilmadi',
  "Balansi bor yetkazib beruvchini o'chirib bo'lmaydi — avval qarzni yoping":
      'Balansi bor yetkazib beruvchini o‘chirib bo‘lmaydi — avval qarzni yoping',
  "Bu yetkazib beruvchiga qarz yo'q": 'Bu yetkazib beruvchiga qarz yo‘q',
  'Kirim topilmadi': 'Kirim topilmadi',
  // Receiving
  'Mahsulot yoki yangi nom kerak': 'Mahsulotni tanlang yoki yangi nom kiriting',
  "PLU kodi 1-5 raqam bo'lishi kerak": 'PLU kodi 1–5 raqamdan iborat bo‘lsin',
  'Qabul topilmadi': 'Qabul topilmadi',
  "Partiya va qoldiq mos kelmadi — kirim BEKOR qilindi. Qo'llab-quvvatlashga murojaat qiling.":
      'Partiya va qoldiq mos kelmadi — kirim BEKOR qilindi. Qo‘llab-quvvatlashga murojaat qiling.',
  // Receipts / sales
  'Chek topilmadi': 'Chek topilmadi',
  'Qaytarish topilmadi': 'Qaytarish topilmadi',
  // Lots
  "Bu mahsulotda partiya kuzatuvi yoqilmagan — partiya ko'rsatib bo'lmaydi":
      'Bu mahsulotda partiya kuzatuvi yoqilmagan — partiya ko‘rsatib bo‘lmaydi',
  "Kuzatuvli mahsulot uchun partiyalarni ANIQ ko'rsating — tizim qaysi jismoniy partiya chiqarilayotganini TAXMIN QILMAYDI.":
      'Partiyali mahsulot uchun partiyalarni aniq ko‘rsating — tizim qaysi partiya chiqarilayotganini taxmin qilmaydi.',
  'Kuzatuvli mahsulotda partiyalarni sanang — umumiy farqni tizim partiyalarga TAQSIMLAMAYDI.':
      'Partiyali mahsulotda partiyalarni sanang — umumiy farqni tizim partiyalarga taqsimlamaydi.',
  "Yangi partiya miqdori musbat bo'lishi kerak.": 'Yangi partiya miqdori noldan katta bo‘lsin.',
  "Yangi partiya tannarxi manfiy bo'lishi mumkin emas.": 'Yangi partiya tannarxi manfiy bo‘lishi mumkin emas.',
  "Bitta mahsulot bir so'rovda IKKI MARTA sanalmaydi": 'Bitta mahsulot bir sanoqda ikki marta bo‘lmasin',
  "Hisobdan chiqarib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.":
      'Hisobdan chiqarib bo‘lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo‘llab-quvvatlashga murojaat qiling.',
  "Inventarizatsiyani yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.":
      'Inventarizatsiyani yozib bo‘lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo‘llab-quvvatlashga murojaat qiling.',
  'Partiya topilmadi': 'Partiya topilmadi',
  "filial vaqt zonasi o'rnatilmagan. Muddat kuzatuvi BIZNES sanasiga tayanadi; zonasiz bir kunlik xato muddati o'tgan tovarni yaroqli ko'rsatishi mumkin.":
      'Filial vaqt zonasi o‘rnatilmagan — muddatli partiyalarni yozib bo‘lmaydi. Administrator zonani sozlasin.',
  // Receiving corrections (Phase 5D)
  "Bu qabul partiya yaratmagan — tuzatish oqimi faqat partiyali qabul uchun. Hujjatni oddiy kirim tahriri bilan o'zgartiring.":
      'Bu qabul partiya yaratmagan — tuzatish faqat partiyali qabul uchun. Hujjatni oddiy kirim tahriri bilan o‘zgartiring.',
  "Bu client_uuid BOSHQA tuzatish so'rovida ishlatilgan — takror emas. Yangi so'rov uchun yangi client_uuid bering.":
      'Bu so‘rov avval boshqa mazmun bilan yuborilgan. Hujjatni yangilab, tuzatishni qayta yuboring.',
  "Tuzatish so'rovi yakunlanmagan — qayta urinib ko'ring": 'Tuzatish so‘rovi yakunlanmagan — qayta urinib ko‘ring',
  "Tuzatishni yozib bo'lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo'llab-quvvatlashga murojaat qiling.":
      'Tuzatishni yozib bo‘lmadi — partiya va qoldiq mos kelmadi. Amal BAJARILMADI; qo‘llab-quvvatlashga murojaat qiling.',
  "Naqd hujjat summasi o'zgardi, lekin kassa yozuvini yozib bo'lmadi — tuzatish BEKOR qilindi. Kassa tegilmagan holda 'bajarildi' deb aytilmaydi; qo'llab-quvvatlashga murojaat qiling.":
      'Kassa yozuvini yozib bo‘lmadi — tuzatish BEKOR qilindi. Qo‘llab-quvvatlashga murojaat qiling.',
  "Bu kirim tuzatilgan — eski tahrir yo'li hujjat jamini qatorlardan QAYTA hisoblab, tuzatishni jimgina teskari qilardi. O'zgartirish uchun yangi tuzatish yarating.":
      'Hujjat tuzatilgan — uni faqat yangi tuzatish orqali o‘zgartirish mumkin.',
  "Xarid filiali o'chirilgan — tuzatib bo'lmaydi": 'Xarid filiali o‘chirilgan — tuzatib bo‘lmaydi',
  "Xarid filiali o'chirilgan — tuzatib bo'lmaydi.": 'Xarid filiali o‘chirilgan — tuzatib bo‘lmaydi',
  "Tuzatish hujjat jamini MANFIY qilardi — amal bajarilmadi. Hujjatni qo'llab-quvvatlash bilan ko'rib chiqing.":
      'Tuzatish hujjat jamini manfiy qilardi — amal bajarilmadi. Qo‘llab-quvvatlashga murojaat qiling.',
  'Kamida bitta qator kerak': 'Kamida bitta qator kerak',
  "Qator tannarxi manfiy bo'lishi mumkin emas": 'Qator tannarxi manfiy bo‘lishi mumkin emas',
  'Qator topilmadi': 'Qator topilmadi',
  "Bu hujjatga bog'langan qabul yo'q — tuzatish faqat qabul hujjati orqali bajariladi.":
      'Bu hujjatga bog‘langan qabul yo‘q — tuzatish faqat qabul hujjati orqali bajariladi.',
  "Bu qabul partiya yaratmagan — tuzatish oqimi faqat partiyali qabul uchun.":
      'Bu qabul partiya yaratmagan — tuzatish faqat partiyali qabul uchun.',
  "Mahsulotda yopilmagan partiya qarzi bor — avval qarzni partiyaga bog'lang, keyin bu qatorni tuzating.":
      'Mahsulotda yopilmagan partiya qarzi bor — avval qarzni partiyaga bog‘lang, keyin bu qatorni tuzating.',
  "Teskari qilingan summa juda katta — miqdor yoki narxni tekshiring":
      'Qaytarilgan summa juda katta — miqdor yoki narxni tekshiring',
  "O'rniga qo'yilgan summa juda katta — miqdor yoki narxni tekshiring":
      'Almashtirilgan summa juda katta — miqdor yoki narxni tekshiring',
  'Tuzatish summasi juda katta — miqdor yoki narxni tekshiring':
      'Tuzatish summasi juda katta — miqdor yoki narxni tekshiring',
  'Hujjat jami summasi juda katta — miqdor yoki narxni tekshiring':
      'Hujjat jami summasi juda katta — miqdor yoki narxni tekshiring',
};

/// A dynamic backend text: [pattern] -> Uzbek [template] with `{name}`
/// placeholders filled from the regex groups ([groups][i] names group i+1;
/// `null` drops the group — used for lot/row UUIDs).
class _Rule {
  const _Rule(this.pattern, this.template, [this.groups = const []]);
  final String pattern;
  final String template;
  final List<String?> groups;
}

const String _kPermsTpl = 'Bu amal uchun ruxsat yo‘q: {perms}';

const List<_Rule> _rules = [
  _Rule(r"^Ruxsat yo'q: ([a-z_]+\.[a-z_]+(?: / [a-z_]+\.[a-z_]+)*)$", _kPermsTpl, ['perms']),
  _Rule(r"^Yetarli qoldiq yo'q: (.+) \(qoldiq: (.+)\)$", 'Yetarli qoldiq yo‘q: {name} (qoldiq: {qty})', ['name', 'qty']),
  _Rule(r"^Mahsulot topilmadi: (.+)$", 'Mahsulot topilmadi', [null]),
  _Rule(r"^Filial topilmadi \((.+)\)$", 'Filial topilmadi ({name})', ['name']),
  _Rule(r"^Filial nofaol — transfer qilib bo'lmaydi \((.+)\)$", 'Filial nofaol — ko‘chirib bo‘lmaydi ({name})', ['name']),
  _Rule(r"^'(.+)' maqsad filial qoldig'i juda katta — miqdorni tekshiring$",
      '«{name}»: qabul qiluvchi filial qoldig‘i juda katta — miqdorni tekshiring', ['name']),
  _Rule(r"^Kassada yetarli naqd yo'q \(mavjud: (.+)\)$", 'Kassada yetarli naqd yo‘q (mavjud: {amount})', ['amount']),
  _Rule(r"^Noto'g'ri to'lov usuli: (.+)$", 'Noto‘g‘ri to‘lov usuli: {method}', ['method']),
  _Rule(r"^PLU (\S+) band \((.+)\) — boshqa PLU kiriting: (.+)$",
      'PLU {plu} band ({other}) — «{name}» uchun boshqa PLU kiriting', ['plu', 'other', 'name']),
  _Rule(r"^AI o'qishda xato: (.+)$", 'Rasmni o‘qib bo‘lmadi — qayta urinib ko‘ring yoki qo‘lda kiriting', [null]),
  _Rule(r"^Ombor qoldig'i yetarli emas: (.+) \(qoldiq (.+)\)$", 'Ombor qoldig‘i yetarli emas: {name} (qoldiq {qty})',
      ['name', 'qty']),
  // Lot selection (write-off / count), keys are lot UUIDs -> dropped.
  _Rule(r"^Partiya ikki marta ko'rsatilgan: (.+)$", 'Partiya ikki marta ko‘rsatilgan', [null]),
  _Rule(r"^Partiya ikki marta sanalgan: (.+)$", 'Partiya ikki marta sanalgan', [null]),
  _Rule(r"^Partiya miqdori musbat bo'lishi kerak: (.+)$", 'Partiya miqdori noldan katta bo‘lsin', [null]),
  _Rule(r"^Sanoq manfiy bo'lishi mumkin emas: (.+)$", 'Sanoq manfiy bo‘lishi mumkin emas', [null]),
  _Rule(r"^Partiya topilmadi: (.+)$", 'Partiya topilmadi', [null]),
  _Rule(r"^Partiya boshqa mahsulot yoki filialga tegishli: (.+)$",
      'Partiya boshqa mahsulot yoki filialga tegishli — ro‘yxatni yangilang', [null]),
  _Rule(r"^Partiya holati '(.+)' — undan miqdor ayirib bo'lmaydi: (.+)$",
      'Partiya holati «{status}» — undan miqdor ayirib bo‘lmaydi', ['status', null]),
  _Rule(r"^Partiya holati '(.+)' — uni sanab bo'lmaydi: (.+)$", 'Partiya holati «{status}» — uni sanab bo‘lmaydi',
      ['status', null]),
  _Rule(r"^Partiyada yetarli qoldiq yo'q \((.+) < (.+)\): (.+) — jismoniy partiya MANFIYGA tushmaydi$",
      'Partiyada yetarli qoldiq yo‘q ({have} < {need})', ['have', 'need', null]),
  _Rule(r"^Partiyada yetarli qoldiq yo'q \((.+) < (.+)\) — jismoniy partiya MANFIYGA tushmaydi$",
      'Partiyada yetarli qoldiq yo‘q ({have} < {need})', ['have', 'need']),
  _Rule(
      r"^Partiyalar yig'indisi \((.+)\) umumiy miqdorga \((.+)\) mos emas\. Farqni tizim TAQSIMLAMAYDI — qaysi partiya ekanini operator aytishi shart\.$",
      'Partiyalar yig‘indisi ({sum}) umumiy miqdorga ({total}) teng emas — qaysi partiya ekanini ko‘rsating.',
      ['sum', 'total']),
  _Rule(
      r"^Partiyalar yig'indisi \((.+)\) e'lon qilingan umumiy sanoqqa \((.+)\) mos emas\. Sanalmagan partiyalar TEGILMAYDI \((.+)\); farqni tizim TAQSIMLAMAYDI\.$",
      'Partiyalar yig‘indisi ({sum}) umumiy sanoqqa ({total}) teng emas. Sanalmagan partiyalar o‘zgarmaydi ({untouched}).',
      ['sum', 'total', 'untouched']),
  _Rule(
      r"^'(.+)' muddat bo'yicha kuzatiladi — yangi partiyada `expiry_date` MAJBURIY\. Noma'lum muddat jimgina qabul qilinmaydi\.$",
      '«{name}» muddat bo‘yicha kuzatiladi — yangi partiyaga yaroqlilik muddatini kiriting.', ['name']),
  _Rule(r"^Hisobdan chiqarib bo'lmadi — invariant buzilardi: (.+)$",
      'Hisobdan chiqarib bo‘lmadi — partiya va qoldiq mos kelmay qolardi. Amal bajarilmadi.', [null]),
  _Rule(r"^Inventarizatsiyani yozib bo'lmadi — invariant buzilardi: (.+)$",
      'Inventarizatsiyani yozib bo‘lmadi — partiya va qoldiq mos kelmay qolardi. Amal bajarilmadi.', [null]),
  // Receiving lot gate (`lot_receiving.py`, `receiving.py`)
  _Rule(
      r"^'(.+)' partiya bo'yicha kuzatiladi — har kirim qatori uchun `lots` MAJBURIY\. Miqdor taxmin qilinmaydi\.$",
      '«{name}» partiya bo‘yicha kuzatiladi — har kirim qatoriga partiyalarni kiriting.', ['name']),
  _Rule(r"^'(.+)' partiya bo'yicha kuzatilmaydi — `lots` berib bo'lmaydi(?:\. Avval partiya kuzatuvini yoqing\.)?$",
      '«{name}» partiya bo‘yicha kuzatilmaydi — partiya kiritib bo‘lmaydi.', ['name']),
  _Rule(
      r"^'(.+)' muddat bo'yicha kuzatiladi — har partiyada `expiry_date` MAJBURIY\. Noma'lum muddat jimgina qabul qilinmaydi\.$",
      '«{name}» muddat bo‘yicha kuzatiladi — har partiyaga yaroqlilik muddatini kiriting.', ['name']),
  _Rule(
      r"^'(.+)' muddat bo'yicha KUZATILMAYDI — yangi partiyaga `expiry_date` yozib bo'lmaydi\. Avval mahsulotda muddat kuzatuvini yoqing\.$",
      '«{name}» muddat bo‘yicha kuzatilmaydi — partiyaga muddat kiritib bo‘lmaydi.', ['name']),
  _Rule(r"^'(.+)': partiyalar yig'indisi (.+) qator miqdori (.+) ga TENG EMAS\. Yetishmagan miqdor taxmin qilinmaydi\.$",
      '«{name}»: partiyalar yig‘indisi {sum} qator miqdori {total} ga teng emas.', ['name', 'sum', 'total']),
  _Rule(r"^'(.+)': partiya miqdori musbat bo'lishi shart$", '«{name}»: partiya miqdori noldan katta bo‘lsin', ['name']),
  _Rule(
      r"^'(.+)': qator miqdori (.+) da uchtadan ORTIQ kasr xonasi bor — miqdor 0\.001 aniqligida beriladi\. Miqdor jimgina yaxlitlanmaydi\.$",
      '«{name}»: miqdor {qty} da uchtadan ortiq kasr xona bor — miqdor 0,001 aniqlikda kiritiladi.', ['name', 'qty']),
  _Rule(
      r"^'(.+)': partiya miqdori (.+) da uchtadan ORTIQ kasr xonasi bor — miqdor 0\.001 aniqligida beriladi\. Miqdor jimgina yaxlitlanmaydi\.$",
      '«{name}»: partiya miqdori {qty} da uchtadan ortiq kasr xona bor — miqdor 0,001 aniqlikda kiritiladi.',
      ['name', 'qty']),
  _Rule(
      r"^'(.+)': partiya tannarxi noma'lum\. Kirim narxi yoki partiya narxi berilishi shart — mahsulotning joriy olish narxi JIMGINA ishlatilmaydi\.$",
      '«{name}»: partiya tannarxi noma’lum — kirim narxini kiriting.', ['name']),
  _Rule(r"^'(.+)': (.+) muddati bugungi biznes sanasi \((.+)\) dan OLDIN — muddati o'tgan tovar qabul qilinmaydi\.$",
      '«{name}»: muddat {date} bugungi ish kunidan ({today}) oldin — muddati o‘tgan tovar qabul qilinmaydi.',
      ['name', 'date', 'today']),
  _Rule(r"^'(.+)' qatori summasi juda katta \(miqdor×narx (.+)\) — miqdor yoki narxni tekshiring$",
      '«{name}» qatori summasi juda katta ({amount}) — miqdor yoki narxni tekshiring', ['name', 'amount']),
  _Rule(r"^'(.+)' partiya bo'yicha kuzatiladi — kirim narxini tahrirlab bo'lmaydi.*$",
      '«{name}» partiya bo‘yicha kuzatiladi — kirim narxini tahrirlab bo‘lmaydi; tuzatish orqali o‘zgartiring.',
      ['name']),
  // Gates (`lot_policy.py`, `stock_gate.py`)
  _Rule(r"^filial vaqt zonasi \('(.+)'\) TASDIQLANMAGAN\..*$",
      'Filial vaqt zonasi ({tz}) tasdiqlanmagan — muddatli partiyalarni yozib bo‘lmaydi. Administrator zonani tasdiqlasin.',
      ['tz']),
  _Rule(r"^vaqt zonasi '(.+)' tanilmagan\..*$", 'Vaqt zonasi «{tz}» tanilmagan — administratorga xabar bering.', ['tz']),
  _Rule(r"^«(.+)» yo'li partiya kuzatuvini qo'llab-quvvatlamaydi, lekin (\d+) ta kuzatuvli mahsulot so'raldi\..*$",
      'Bu amal partiya bo‘yicha kuzatiladigan mahsulotni qo‘llab-quvvatlamaydi ({n} ta mahsulot).', [null, 'n']),
  _Rule(r"^Noma'lum (?:guruh|tartib|holat): (.+)$", 'Noma’lum filtr qiymati: {value}', ['value']),
  _Rule(r"^Bitta so'rovda (\d+) ta partiya qatori — chegara (\d+)\..*$",
      'Bir so‘rovda {n} ta partiya qatori — chegara {max}. Sanoqni bir necha qismga bo‘lib yuboring.', ['n', 'max']),
  // Receiving corrections (Phase 5D)
  _Rule(r"^Tuzatish sababi (\d+)\.\.(\d+) belgidan iborat bo'lishi shart.*$",
      'Tuzatish sababi {min}–{max} belgidan iborat bo‘lsin.', ['min', 'max']),
  _Rule(r"^Bitta so'rovda (\d+) ta qator — chegara (\d+)\..*$",
      'Bir so‘rovda {n} ta qator — chegara {max}. Tuzatishni bir necha qismga bo‘lib yuboring.', ['n', 'max']),
  _Rule(r"^Bitta qatorda (\d+) tadan ortiq partiya.*$", 'Bitta qatorda {n} tadan ortiq partiya — tuzatishni bo‘lib yuboring.',
      ['n']),
  _Rule(r"^Qator ikki marta ko'rsatilgan: (.+)$", 'Qator ikki marta ko‘rsatilgan', [null]),
  _Rule(r"^Qatorda na teskari qilish, na o'rniga qo'yish bor: (.+)$", 'Qatorda na qaytarish, na almashtirish bor', [null]),
  _Rule(r"^O'rniga qo'yiladigan partiya bor, lekin qator tannarxi berilmagan: (.+)$",
      'Almashtiriladigan partiya bor, lekin qator tannarxi kiritilmagan.', [null]),
  _Rule(r"^Tannarxni partiyasiz tuzatib bo'lmaydi: (.+)$",
      'Tannarxni partiyasiz tuzatib bo‘lmaydi — eski partiyani qaytarib, yangisini kiriting.', [null]),
  _Rule(r"^Qator topilmadi: (.+)$", 'Qator topilmadi', [null]),
  _Rule(r"^Partiya bu qabulga tegishli emas: (.+)$", 'Partiya bu qabulga tegishli emas', [null]),
  _Rule(r"^'(.+)': qoldiq qatori topilmadi — tuzatib bo'lmaydi$", '«{name}»: qoldiq qatori topilmadi — tuzatib bo‘lmaydi',
      ['name']),
  _Rule(r"^'(.+)': partiyada (.+) qoldi, (.+) teskari qilinmoqda — jismoniy partiya MANFIYGA tushmaydi\.$",
      '«{name}»: partiyada {left} qoldi, {qty} qaytarilmoqda — partiya manfiyga tushmaydi.', ['name', 'left', 'qty']),
  _Rule(r"^'(.+)': partiyadan (.+) dona allaqachon harakatlangan.*$",
      '«{name}»: partiyadan {qty} allaqachon harakatlangan — uning raqami, muddati va narxini tuzatib bo‘lmaydi; faqat miqdorni qaytarish mumkin.',
      ['name', 'qty']),
  _Rule(r"^'(.+)': yopilmagan partiya qarzi bor.*$",
      '«{name}»: yopilmagan partiya qarzi bor — avval qarzni partiyaga bog‘lang.', ['name']),
  _Rule(r"^(.+) juda katta — miqdor yoki narxni tekshiring$", 'Summa juda katta — miqdor yoki narxni tekshiring', [null]),
  // Password policy (`app/core/password_policy.py`: "Parol qabul qilinmadi: <sabab>"). The
  // minimum comes from the server text, so a changed MIN_LEN is shown correctly.
  _Rule(r"^Parol qabul qilinmadi: juda qisqa \((\d+) belgi, kamida (\d+) kerak\)$",
      _kPwShort, [null, 'n']),
  _Rule(r"^Parol qabul qilinmadi: juda uzun.*$", 'Parol juda uzun.'),
  _Rule(r"^Parol qabul qilinmadi: (?:juda ko'p uchraydigan qiymat|ma'lum arzon qiymatdan boshlanadi)$",
      'Parol juda oddiy — boshqa parol tanlang.'),
  _Rule(r"^Parol qabul qilinmadi: (?:entropiyasi past.*|bir xil belgi ketma-ket takrorlanadi)$",
      'Parolda takrorlanuvchi belgilar ko‘p — boshqa parol tanlang.'),
  _Rule(r"^Parol qabul qilinmadi: bo'sh$", 'Yangi parolni kiriting.'),
  _Rule(r"^Parol qabul qilinmadi: (.+)$", 'Parol qabul qilinmadi — boshqa parol tanlang.', [null]),
  // `clean_name(field=...)` (`app/core/validate.py`): "<field> kiritilishi kerak". The field
  // label is translated when known ([_fieldLabels]) and kept as-is otherwise. `[^:]` so a
  // "3-qator: " prefix is kept by the prefix split instead of being read as the label.
  _Rule(r"^([^:]+) kiritilishi kerak$", '{field} kiritilishi kerak', ['field']),
];

const String _kPwShort = 'Parol juda qisqa — kamida {n} belgi kerak.';

/// Field labels the server puts into "<field> kiritilishi kerak".
const Set<String> _fieldLabels = {'Mijoz nomi', 'Ism', 'Mahsulot nomi', 'Kategoriya nomi', 'Yetkazib beruvchi nomi'};

final List<(RegExp, _Rule)> _compiled = [for (final r in _rules) (RegExp(r.pattern), r)];

final RegExp _uuid = RegExp(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}');
final RegExp _internal = RegExp(r'traceback|\bsql\b|\[sql|psycopg|sqlalchemy|stock_invariant', caseSensitive: false);

String? _look(String msg) {
  final s = _static[msg];
  if (s != null) return tr(s);
  for (final (re, rule) in _compiled) {
    final m = re.firstMatch(msg);
    if (m == null) continue;
    final args = <String, Object?>{};
    for (var i = 0; i < rule.groups.length && i < m.groupCount; i++) {
      final name = rule.groups[i];
      if (name == null) continue;
      final v = m.group(i + 1) ?? '';
      args[name] = switch (name) {
        'perms' => v.split(' / ').map(permissionLabel).join(' / '),
        'field' => tr(v),
        _ => v,
      };
    }
    return trArgs(rule.template, args);
  }
  return null;
}

/// Known server text -> localized message; tries every `"<prefix>: "` split so
/// a product name (which may itself contain `": "`) is kept as-is.
String? _translateKnown(String msg) {
  final text = msg.trim();
  if (text.isEmpty) return null;
  final direct = _look(text);
  if (direct != null) return direct;
  for (var from = 0;;) {
    final i = text.indexOf(': ', from);
    if (i < 0) break;
    final rest = _look(text.substring(i + 2));
    if (rest != null) return '${text.substring(0, i + 2)}$rest';
    from = i + 2;
  }
  return null;
}

/// Removes UUIDs and internal details from an unknown server text; returns
/// the generic message key when the text looks like an internal failure.
String? _sanitize(String raw) {
  var s = raw.trim();
  if (s.isEmpty) return null;
  if (_internal.hasMatch(s)) return _kUnexpected;
  final c = ApiException.extractCode(const {}, s);
  if (c != null) s = s.substring(c.length + 1).trim(); // unknown "CODE: text" — drop the token
  s = s.replaceAll(_uuid, '');
  s = s
      .replaceAll(RegExp(r'\(\s*\)'), '')
      .replaceAll(RegExp(r'[ \t]{2,}'), ' ')
      .replaceAllMapped(RegExp(r'\s+([,.;:])'), (m) => m[1]!)
      .replaceAll(RegExp(r'[:,;]\s*$'), '')
      .trim();
  if (s.isEmpty || s.startsWith('{') || s.startsWith('[')) return null;
  if (s.length > 400) s = '${s.substring(0, 400)}…';
  return s;
}

/// Localized message for a stable [code], or `null` if the code is unknown.
String? codeMessage(String? code) {
  if (code == null) return null;
  final m = codeMessages[code.trim()];
  return m == null ? null : tr(m);
}

/// Translates a text the server returned as DATA (e.g. a purchase's
/// `correction_blocked_reason`, a custody `reason` code): a bare code, a
/// `CODE: text`, a known text, or a sanitised unknown text.
String serverText(String? raw) {
  final s = (raw ?? '').trim();
  if (s.isEmpty) return '';
  final bare = codeMessage(s);
  if (bare != null) return bare;
  final code = ApiException.extractCode(const {}, s);
  final byCode = code == null ? null : codeMessage(code);
  if (byCode != null) return byCode;
  final known = _translateKnown(s);
  if (known != null) return known;
  final clean = _sanitize(s);
  return clean == null ? tr(_kUnexpected) : tr(clean);
}

/// True when [e] is a connectivity failure (no server decision was made):
/// retrying with the same `client_uuid` is safe.
bool isConnectivityError(Object? e) {
  if (e is ApiException) return e.isConnectivity;
  return e is TimeoutException ||
      e is SocketException ||
      e is http.ClientException ||
      e is HandshakeException ||
      e is HttpException;
}

/// One localized, sanitised sentence for ANY error object. See the library doc.
String userMessage(Object? e) {
  if (e == null) return tr(_kUnexpected);
  if (e is ApiException) return _apiMessage(e);
  if (e is TimeoutException) return tr(_kTimeout);
  if (isConnectivityError(e)) return tr(_kNetwork);
  if (e is String) return serverText(e);
  return tr(_kUnexpected);
}

String _apiMessage(ApiException e) {
  switch (e.kind) {
    case ApiErrorKind.network:
      return tr(_kNetwork);
    case ApiErrorKind.timeout:
      return tr(_kTimeout);
    case ApiErrorKind.auth:
      // `POST /auth/password` answers 401 for a wrong CURRENT password (the
      // session stays valid — Api does not log out on that path).
      final t = ApiException.flatten(e.detail)?.trim();
      if (t == _kWrongCurrentServer) return tr(_kWrongCurrent);
      return tr(_kAuth);
    case ApiErrorKind.validation:
      return tr(_kValidation);
    case ApiErrorKind.server:
      return tr(e.code == 'BAD_RESPONSE' ? _kBadResponse : _kServer);
    case ApiErrorKind.permission:
    case ApiErrorKind.business:
      break;
  }
  final text = ApiException.flatten(e.detail) ?? '';
  final code = e.code;
  if (code != null && _codeFirst(code)) {
    final m = codeMessage(code);
    if (m != null) return m;
  }
  final known = _translateKnown(text);
  if (known != null) return known;
  final byCode = codeMessage(code);
  if (byCode != null) return byCode;
  if (e.kind == ApiErrorKind.permission) return tr(_kPermission);
  final clean = e.detail is String ? _sanitize(text) : null;
  if (clean != null) return tr(clean);
  return trArgs(_kStatus, {'status': e.status});
}

/// Every Uzbek message template this file can produce — the l10n test checks
/// each one has a Russian and a Kyrgyz translation.
@visibleForTesting
Set<String> debugErrorTemplates() => {
      _kNetwork,
      _kTimeout,
      _kAuth,
      _kValidation,
      _kServer,
      _kBadResponse,
      _kPermission,
      _kUnexpected,
      _kStatus,
      _kWrongCurrent,
      ..._fieldLabels,
      ...codeMessages.values,
      ..._static.values,
      for (final r in _rules) r.template,
    };
