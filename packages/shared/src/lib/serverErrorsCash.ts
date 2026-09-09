// Naqd (cash ledger) xatolari — QO'LDA yuritiladi.
//
// NEGA ALOHIDA FAYL: `serverErrors.ts` AVTO-GENERATSIYA qilinadi (sarlavhasida "qo'lda
// tahrirlamang" deb yozilgan) va uning generatori repoda yo'q. Naqd xatolari kod-prefiksli
// (`CASH_CUSTODY_...: matn`) bo'lgani uchun ular avto-lug'atdagi ANIQ MATN qidiruviga tushmaydi.
// Shu bois ular shu yerda, PREFIKS bo'yicha tarjima qilinadi va avto-generatsiya fayliga
// TEGILMAYDI (qayta generatsiya bu tarjimalarni o'chirmaydi).
//
// Tarjimasiz nima bo'lardi: kirill/rus tilidagi do'kon egasi lotin-o'zbekcha texnik matn
// ko'rardi — masalan "CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER: 'debt_payment': T0'dan
// keyin naqd manbai/manzili AYNAN ko'rsatilishi SHART". Bu do'kon egasi uchun tushunarsiz.

import { useLang } from "@/store/lang";

interface Tr { ru: string; uzc: string; uz: string }

// Kod -> odam tilida tushunarli xabar (SABABI + NIMA QILISH kerakligi).
const CASH: Record<string, Tr> = {
  CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER: {
    uz: "Naqd qabul qilish uchun smena ochiq bo'lishi kerak. Kassir smenani ochsin va to'lovni kassada qabul qilsin.",
    ru: "Для приёма наличных должна быть открыта смена. Пусть кассир откроет смену и примет оплату на кассе.",
    uzc: "Нақд қабул қилиш учун смена очиқ бўлиши керак. Кассир сменани очсин ва тўловни кассада қабул қилсин.",
  },
  CASH_CUSTODY_ACCOUNT_INVALID: {
    uz: "Tanlangan kassa yaroqsiz (faol emas, boshqa filial yoki boshqa do'kon).",
    ru: "Выбранная касса недействительна (неактивна, другой филиал или другой магазин).",
    uzc: "Танланган касса яроқсиз (фаол эмас, бошқа филиал ёки бошқа дўкон).",
  },
  CASH_LEDGER_UNAVAILABLE: {
    uz: "Naqd hisobi vaqtincha ishlamayapti — amal BAJARILMADI (pul hisobsiz qolmasligi uchun). Administratorga xabar bering.",
    ru: "Учёт наличных временно недоступен — операция НЕ выполнена (чтобы деньги не остались без учёта). Сообщите администратору.",
    uzc: "Нақд ҳисоби вақтинча ишламаяпти — амал БАЖАРИЛМАДИ (пул ҳисобсиз қолмаслиги учун). Администраторга хабар беринг.",
  },
  TILL_REQUIRED_AFTER_CUTOVER: {
    uz: "Kassa (TILL) tanlanmagan. Smenani aynan kassa tanlab oching.",
    ru: "Касса (TILL) не выбрана. Откройте смену, выбрав конкретную кассу.",
    uzc: "Касса (TILL) танланмаган. Сменани айнан касса танлаб очинг.",
  },
  TILL_INVALID_AFTER_CUTOVER: {
    uz: "Kassa yaroqsiz (faol emas yoki boshqa filialga tegishli).",
    ru: "Касса недействительна (неактивна или относится к другому филиалу).",
    uzc: "Касса яроқсиз (фаол эмас ёки бошқа филиалга тегишли).",
  },
  TILL_DOES_NOT_MATCH_SHIFT_AFTER_CUTOVER: {
    uz: "Bu amal ochiq smena kassasiga mos emas. Smena o'rtasida kassa almashtirilmaydi.",
    ru: "Операция не соответствует кассе открытой смены. Касса не меняется в середине смены.",
    uzc: "Бу амал очиқ смена кассасига мос эмас. Смена ўртасида касса алмаштирилмайди.",
  },
  LEGACY_SHIFT_REQUIRES_TILL_AFTER_CUTOVER: {
    uz: "Bu smena eski (kassasiz) ochilgan. Uni yopib, kassa tanlab yangi smena oching.",
    ru: "Эта смена открыта по-старому (без кассы). Закройте её и откройте новую, выбрав кассу.",
    uzc: "Бу смена эски (кассасиз) очилган. Уни ёпиб, касса танлаб янги смена очинг.",
  },
  CLOSED_SHIFT_CASH_REPLAY_REQUIRES_RECOVERY: {
    uz: "Bu chek yopilgan smenaga tegishli — avtomatik qabul qilinmaydi. Administrator tekshirishi kerak.",
    ru: "Этот чек относится к закрытой смене — автоматически не принимается. Требуется проверка администратора.",
    uzc: "Бу чек ёпилган сменага тегишли — автоматик қабул қилинмайди. Администратор текшириши керак.",
  },
};

/** Naqd xato kodini foydalanuvchi tiliga o'giradi. Kod topilmasa `null` — chaqiruvchi
 *  odatiy (avto-generatsiya) lug'atga o'tadi. */
export function translateCashError(msg: string): string | null {
  if (!msg || typeof msg !== "string") return null;
  // Format: "KOD: batafsil texnik matn" — biz FAQAT kodga qaraymiz.
  const code = msg.split(":", 1)[0].trim();
  const tr = CASH[code];
  if (!tr) return null;
  let lang: string;
  try { lang = useLang.getState().lang; } catch { return tr.uz; }
  if (lang === "uzc") return tr.uzc;
  if (lang === "ru" || lang === "ky") return tr.ru;   // ky -> ru (Qirg'iziston)
  return tr.uz;
}
