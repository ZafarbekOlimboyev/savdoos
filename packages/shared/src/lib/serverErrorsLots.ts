// Partiya / muddat / inventarizatsiya xatolari — QO'LDA yuritiladi.
//
// NEGA ALOHIDA FAYL: `serverErrors.ts` AVTO-GENERATSIYA qilinadi va uning generatori
// repoda YO'Q (`serverErrorsCash.ts` sarlavhasida ham shu yozilgan). Phase 4B ekranlari
// ishlatadigan ~30 ta xato o'sha lug'atga tushmagan — ularsiz kirill/rus tilidagi do'kon
// egasi lotin-o'zbekcha texnik matn ko'rardi. Qayta generatsiya bu faylga TEGMAYDI.
//
// ⚠️  MATNLAR SERVER MATNIGA AYNAN MOS BO'LISHI SHART. Backend xabari o'zgarsa bu yerda
//     ham o'zgartiring — aks holda tarjima jimgina tushib qoladi (xato ko'rinaveradi,
//     faqat asl tilda). Shu bois `apps/server/tests/test_lot_error_texts.py` matnlarni
//     manba kodi bilan solishtirib turadi.
import { useLang } from "@/store/lang";

interface Tr { ru: string; uzc: string }

// Aniq (statik) matnlar
const STATIC: Record<string, Tr> = {
  "Bu mahsulotda partiya kuzatuvi yoqilmagan — partiya ko'rsatib bo'lmaydi": {
    ru: "Для этого товара учёт партий не включён — партию указать нельзя",
    uzc: "Бу маҳсулотда партия кузатуви ёқилмаган — партия кўрсатиб бўлмайди",
  },
  "Kuzatuvli mahsulot uchun partiyalarni ANIQ ko'rsating — tizim qaysi jismoniy partiya chiqarilayotganini TAXMIN QILMAYDI.": {
    ru: "Для товара с учётом партий укажите партии ТОЧНО — система не угадывает, какая физическая партия списывается.",
    uzc: "Кузатувли маҳсулот учун партияларни АНИҚ кўрсатинг — тизим қайси жисмоний партия чиқарилаётганини ТАХМИН ҚИЛМАЙДИ.",
  },
  "Kuzatuvli mahsulotda partiyalarni sanang — umumiy farqni tizim partiyalarga TAQSIMLAMAYDI.": {
    ru: "У товара с учётом партий пересчитайте партии — общую разницу система по партиям НЕ РАСПРЕДЕЛЯЕТ.",
    uzc: "Кузатувли маҳсулотда партияларни сананг — умумий фарқни тизим партияларга ТАҚСИМЛАМАЙДИ.",
  },
  "Yangi partiya miqdori musbat bo'lishi kerak.": {
    ru: "Количество новой партии должно быть положительным.",
    uzc: "Янги партия миқдори мусбат бўлиши керак.",
  },
  "Yangi partiya tannarxi manfiy bo'lishi mumkin emas.": {
    ru: "Себестоимость новой партии не может быть отрицательной.",
    uzc: "Янги партия таннархи манфий бўлиши мумкин эмас.",
  },
  "Mavjud qoldiq bor: `opening_lots` bering yoki `legacy_unit_cost` ni ANIQ ko'rsating. Mahsulotning joriy olish narxi JIMGINA ishlatilmaydi.": {
    ru: "Есть текущий остаток: передайте начальные партии или ТОЧНО укажите себестоимость остатка. Текущая закупочная цена товара молча не используется.",
    uzc: "Мавжуд қолдиқ бор: бошланғич партияларни беринг ёки таннархни АНИҚ кўрсатинг. Маҳсулотнинг жорий олиш нархи ЖИМГИНА ишлатилмайди.",
  },
  "Qarz topilmadi": { ru: "Долг не найден", uzc: "Қарз топилмади" },
  "Partiya topilmadi": { ru: "Партия не найдена", uzc: "Партия топилмади" },
};

// Dinamik matnlar ($1, $2 — regex guruhlari)
const DYNAMIC: { re: RegExp; ru: string; uzc: string }[] = [
  { re: /^Partiya ikki marta ko'rsatilgan: (.+)$/, ru: "Партия указана дважды: $1", uzc: "Партия икки марта кўрсатилган: $1" },
  { re: /^Partiya ikki marta sanalgan: (.+)$/, ru: "Партия пересчитана дважды: $1", uzc: "Партия икки марта саналган: $1" },
  { re: /^Partiya miqdori musbat bo'lishi kerak: (.+)$/, ru: "Количество партии должно быть положительным: $1", uzc: "Партия миқдори мусбат бўлиши керак: $1" },
  { re: /^Sanoq manfiy bo'lishi mumkin emas: (.+)$/, ru: "Пересчёт не может быть отрицательным: $1", uzc: "Саноқ манфий бўлиши мумкин эмас: $1" },
  { re: /^Partiya topilmadi: (.+)$/, ru: "Партия не найдена: $1", uzc: "Партия топилмади: $1" },
  { re: /^Partiya boshqa mahsulot yoki filialga tegishli: (.+)$/, ru: "Партия относится к другому товару или филиалу: $1", uzc: "Партия бошқа маҳсулот ёки филиалга тегишли: $1" },
  { re: /^Partiya holati '(.+)' — undan miqdor ayirib bo'lmaydi: (.+)$/, ru: "Статус партии «$1» — списать с неё количество нельзя: $2", uzc: "Партия ҳолати «$1» — ундан миқдор айириб бўлмайди: $2" },
  { re: /^Partiya holati '(.+)' — uni sanab bo'lmaydi: (.+)$/, ru: "Статус партии «$1» — её нельзя пересчитать: $2", uzc: "Партия ҳолати «$1» — уни санаб бўлмайди: $2" },
  { re: /^Partiyada yetarli qoldiq yo'q \((.+) < (.+)\): (.+) — jismoniy partiya MANFIYGA tushmaydi$/, ru: "В партии недостаточно остатка ($1 < $2): $3 — физическая партия не уходит в минус", uzc: "Партияда етарли қолдиқ йўқ ($1 < $2): $3 — жисмоний партия МАНФИЙГА тушмайди" },
  { re: /^Partiyalar yig'indisi \((.+)\) umumiy miqdorga \((.+)\) mos emas\. Farqni tizim TAQSIMLAMAYDI — qaysi partiya ekanini operator aytishi shart\.$/, ru: "Сумма партий ($1) не совпадает с общим количеством ($2). Разницу система НЕ РАСПРЕДЕЛЯЕТ — какая это партия, должен указать оператор.", uzc: "Партиялар йиғиндиси ($1) умумий миқдорга ($2) мос эмас. Фарқни тизим ТАҚСИМЛАМАЙДИ — қайси партия эканини оператор айтиши шарт." },
  { re: /^Partiyalar yig'indisi \((.+)\) e'lon qilingan umumiy sanoqqa \((.+)\) mos emas\. Sanalmagan partiyalar TEGILMAYDI \((.+)\); farqni tizim TAQSIMLAMAYDI\.$/, ru: "Сумма партий ($1) не совпадает с заявленным итогом пересчёта ($2). Непересчитанные партии НЕ ТРОГАЮТСЯ ($3); разницу система НЕ РАСПРЕДЕЛЯЕТ.", uzc: "Партиялар йиғиндиси ($1) эълон қилинган умумий саноққа ($2) мос эмас. Саналмаган партиялар ТЕГИЛМАЙДИ ($3); фарқни тизим ТАҚСИМЛАМАЙДИ." },
  { re: /^'(.+)' muddat bo'yicha kuzatiladi — yangi partiyada `expiry_date` MAJBURIY\. Noma'lum muddat jimgina qabul qilinmaydi\.$/, ru: "«$1» отслеживается по сроку годности — у новой партии срок ОБЯЗАТЕЛЕН. Неизвестный срок молча не принимается.", uzc: "«$1» муддат бўйича кузатилади — янги партияда муддат МАЖБУРИЙ. Номаълум муддат жимгина қабул қилинмайди." },
  { re: /^Ochilish partiyalari yig'indisi (.+) joriy qoldiq (.+) ga TENG EMAS\. Miqdor taxmin qilinmaydi\.$/, ru: "Сумма начальных партий $1 НЕ РАВНА текущему остатку $2. Количество не угадывается.", uzc: "Бошланғич партиялар йиғиндиси $1 жорий қолдиқ $2 га ТЕНГ ЭМАС. Миқдор тахмин қилинмайди." },
  { re: /^Kuzatuvni yoqib bo'lmadi — miqdor invarianti buzilgan bo'lardi: (.+)$/, ru: "Не удалось включить учёт — был бы нарушен инвариант количества: $1", uzc: "Кузатувни ёқиб бўлмади — миқдор инварианти бузилган бўларди: $1" },
  { re: /^Hisobdan chiqarib bo'lmadi — invariant buzilardi: (.+)$/, ru: "Списать не удалось — был бы нарушен инвариант: $1", uzc: "Ҳисобдан чиқариб бўлмади — инвариант бузиларди: $1" },
  { re: /^Inventarizatsiyani yozib bo'lmadi — invariant buzilardi: (.+)$/, ru: "Пересчёт не записан — был бы нарушен инвариант: $1", uzc: "Инвентаризацияни ёзиб бўлмади — инвариант бузиларди: $1" },
  { re: /^'(.+)' allaqachon partiya bo'yicha kuzatiladi$/, ru: "«$1» уже отслеживается по партиям", uzc: "«$1» аллақачон партия бўйича кузатилади" },
  { re: /^Noma'lum guruh: (.+)$/, ru: "Неизвестная группа: $1", uzc: "Номаълум гуруҳ: $1" },
  { re: /^Noma'lum tartib: (.+)$/, ru: "Неизвестная сортировка: $1", uzc: "Номаълум тартиб: $1" },
  { re: /^Noma'lum holat: (.+)$/, ru: "Неизвестный статус: $1", uzc: "Номаълум ҳолат: $1" },
];

function look(msg: string, lang: string): string | null {
  const s = STATIC[msg];
  if (s) return lang === "uzc" ? s.uzc : s.ru;
  for (const d of DYNAMIC) {
    const m = msg.match(d.re);
    if (m) {
      const tpl = lang === "uzc" ? d.uzc : d.ru;
      return tpl.replace(/\$(\d)/g, (_, i) => m[+i] ?? "");
    }
  }
  return null;
}

/** Partiya xatosini foydalanuvchi tiliga o'giradi; lug'atda bo'lmasa `null`
 *  (chaqiruvchi avto-generatsiya lug'atiga o'tadi).
 *
 *  ⚠️  Inventarizatsiya/hisobdan chiqarish xatolari serverda MAHSULOT NOMI bilan
 *      oldindan belgilanadi (`f"{prod.name}: {e}"`). Nom tarjima QILINMAYDI —
 *      shuning uchun prefiks ajratilib, qolgani tarjima qilinadi va nom
 *      o'z holicha qaytariladi. */
export function translateLotError(msg: string): string | null {
  if (!msg || typeof msg !== "string") return null;
  let lang: string;
  try { lang = useLang.getState().lang; } catch { return null; }
  if (lang === "uz") return null;          // asl matn allaqachon o'zbekcha
  if (lang === "ky") lang = "ru";          // Qirg'iziston — ruscha
  const direct = look(msg, lang);
  if (direct) return direct;
  const i = msg.indexOf(": ");
  if (i > 0) {
    const rest = look(msg.slice(i + 2), lang);
    if (rest) return msg.slice(0, i + 2) + rest;
  }
  return null;
}
