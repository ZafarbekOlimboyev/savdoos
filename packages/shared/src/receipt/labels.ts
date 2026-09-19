// Chek yorliqlari — 4 til. `i18n.ts` dan ALOHIDA: bu modul Electron main'da ham ishlaydi
// (zustand `useLang` yo'q) va chek tili ekran tilidan farq qilishi mumkin (template.lang).
//
// Yozuv: uz — lotin (repo odati bo'yicha ASCII apostrof), uzc — o'zbek kirill, ky — qirg'iz, ru — rus.
// Termal printerda yo'q harflar (қ ғ ҳ ң ө ү) ESC/POS kodlovchisida transliteratsiya qilinadi.
import type { ReceiptLang } from "./types";

export interface Labels {
  receipt: string;
  returnTitle: string;
  date: string;
  cashier: string;
  till: string;
  branch: string;
  stir: string;
  subtotal: string;
  /** Chek (hujjat) darajasidagi chegirma. */
  discount: string;
  /** Tovar qatori chegirmasi (va ularning yig'indisi). */
  lineDiscount: string;
  rounding: string;
  total: string;
  returnTotal: string;
  paymentTitle: string;
  method_cash: string;
  method_card: string;
  method_qr: string;
  method_credit: string;
  given: string;
  change: string;
  customer: string;
  original: string;
  refunded: string;
  copy: string;
  testTitle: string;
  testSub: string;
  offlineTitle: string;
  offlineSub: string;
  footerDefault: string;
  items: string;
}

const TEST_TITLE = "*** TEST PRINT ***";

export const RECEIPT_LABELS: Readonly<Record<ReceiptLang, Readonly<Labels>>> = Object.freeze({
  uz: Object.freeze({
    receipt: "Chek",
    returnTitle: "QAYTARISH CHEKI",
    date: "Sana",
    cashier: "Kassir",
    till: "Kassa",
    branch: "Filial",
    stir: "STIR",
    subtotal: "Oraliq jami",
    discount: "Chek chegirmasi",
    lineDiscount: "Chegirma",
    rounding: "Yaxlitlash",
    total: "JAMI",
    returnTotal: "QAYTARISH JAMI",
    paymentTitle: "To'lov",
    method_cash: "Naqd",
    method_card: "Karta",
    method_qr: "QR",
    method_credit: "Nasiya",
    given: "Berildi",
    change: "Qaytim",
    customer: "Xaridor",
    original: "Asl chek",
    refunded: "Qaytarildi",
    copy: "NUSXA",
    testTitle: TEST_TITLE,
    testSub: "sotuv emas",
    offlineTitle: "OFLAYN — VAQTINCHALIK CHEK",
    offlineSub: "Server hali tasdiqlamagan",
    footerDefault: "Xaridingiz uchun rahmat!",
    items: "Tovarlar",
  }),
  uzc: Object.freeze({
    receipt: "Чек",
    returnTitle: "ҚАЙТАРИШ ЧЕКИ",
    date: "Сана",
    cashier: "Кассир",
    till: "Касса",
    branch: "Филиал",
    stir: "СТИР",
    subtotal: "Оралиқ жами",
    discount: "Чек чегирмаси",
    lineDiscount: "Чегирма",
    rounding: "Яхлитлаш",
    total: "ЖАМИ",
    returnTotal: "ҚАЙТАРИШ ЖАМИ",
    paymentTitle: "Тўлов",
    method_cash: "Нақд",
    method_card: "Карта",
    method_qr: "QR",
    method_credit: "Насия",
    given: "Берилди",
    change: "Қайтим",
    customer: "Харидор",
    original: "Асл чек",
    refunded: "Қайтарилди",
    copy: "НУСХА",
    testTitle: TEST_TITLE,
    testSub: "сотув эмас",
    offlineTitle: "ОФЛАЙН — ВАҚТИНЧАЛИК ЧЕК",
    offlineSub: "Сервер ҳали тасдиқламаган",
    footerDefault: "Харидингиз учун раҳмат!",
    items: "Товарлар",
  }),
  ru: Object.freeze({
    receipt: "Чек",
    returnTitle: "ЧЕК ВОЗВРАТА",
    date: "Дата",
    cashier: "Кассир",
    till: "Касса",
    branch: "Филиал",
    stir: "ИНН",
    subtotal: "Подытог",
    discount: "Скидка на чек",
    lineDiscount: "Скидка",
    rounding: "Округление",
    total: "ИТОГО",
    returnTotal: "ИТОГО ВОЗВРАТ",
    paymentTitle: "Оплата",
    method_cash: "Наличные",
    method_card: "Карта",
    method_qr: "QR",
    method_credit: "В долг",
    given: "Внесено",
    change: "Сдача",
    customer: "Покупатель",
    original: "Исходный чек",
    refunded: "Возвращено",
    copy: "КОПИЯ",
    testTitle: TEST_TITLE,
    testSub: "не продажа",
    offlineTitle: "ОФЛАЙН — ПРЕДВАРИТЕЛЬНЫЙ ЧЕК",
    offlineSub: "Ещё не подтверждён сервером",
    footerDefault: "Спасибо за покупку!",
    items: "Товары",
  }),
  ky: Object.freeze({
    receipt: "Чек",
    returnTitle: "КАЙТАРУУ ЧЕГИ",
    date: "Күнү",
    cashier: "Кассир",
    till: "Касса",
    branch: "Филиал",
    stir: "ИНН",
    subtotal: "Аралык сумма",
    discount: "Чекке арзандатуу",
    lineDiscount: "Арзандатуу",
    rounding: "Тегеректөө",
    total: "ЖЫЙЫНТЫК",
    returnTotal: "КАЙТАРУУ ЖЫЙЫНТЫГЫ",
    paymentTitle: "Төлөм",
    method_cash: "Накталай",
    method_card: "Карта",
    method_qr: "QR",
    method_credit: "Насыя",
    given: "Берилди",
    change: "Кайтарым",
    customer: "Кардар",
    original: "Баштапкы чек",
    refunded: "Кайтарылды",
    copy: "КӨЧҮРМӨ",
    testTitle: TEST_TITLE,
    testSub: "сатуу эмес",
    offlineTitle: "ОФЛАЙН — УБАКТЫЛУУ ЧЕК",
    offlineSub: "Сервер азырынча ырастай элек",
    footerDefault: "Сатып алганыңыз үчүн рахмат!",
    items: "Товарлар",
  }),
});

/** Noma'lum til → ru (ilova standarti `store/lang.ts` bilan bir xil); noto'g'ri qiymatga chidamli. */
export function labelsFor(lang: ReceiptLang | string | null | undefined): Readonly<Labels> {
  return (lang && (RECEIPT_LABELS as Record<string, Labels>)[lang]) || RECEIPT_LABELS.ru;
}

export function methodLabel(L: Readonly<Labels>, method: string): string {
  switch (method) {
    case "cash":
      return L.method_cash;
    case "card":
      return L.method_card;
    case "qr":
      return L.method_qr;
    case "credit":
      return L.method_credit;
    default:
      return method; // noma'lum kod — xom holda (layout baribir tozalaydi)
  }
}
