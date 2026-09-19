// Chek / logo / chop etish xatolari (Phase 5F) — QO'LDA yuritiladi.
//
// NEGA ALOHIDA FAYL: `serverErrors.ts` avto-generatsiya qilinadi va generatori repoda yo'q.
// Backend matnlari `apps/server/app/services/receipt/errors.py` da E'LON QILINGAN va
// `tests/test_receipt_error_texts.py` har bir matn shu lug'atda borligini tekshiradi —
// server matni o'zgarsa, test qizaradi (rus/kirill do'konda xom lotin matn chiqmasin).
//
// Kalit — backend `detail` matnining O'ZI (aniq moslik) yoki pastdagi REGEX'lar.

import { useLang } from "@/store/lang";

interface Tr { uz: string; ru: string; uzc: string }

export const RECEIPT_ERRORS: Record<string, Tr> = {
  "Ruxsat yo'q: kompaniya chek shablonini faqat barcha filiallarga kirish huquqi bor xodim o'zgartiradi": {
    uz: "Ruxsat yo'q: kompaniya chek shablonini faqat barcha filiallarga kirish huquqi bor xodim o'zgartiradi",
    ru: "Нет доступа: шаблон чека компании может менять только сотрудник с доступом ко всем филиалам",
    uzc: "Рухсат йўқ: компания чек шаблонини фақат барча филиалларга кириш ҳуқуқи бор ходим ўзгартиради",
  },
  "Logo topilmadi": { uz: "Logo topilmadi", ru: "Логотип не найден", uzc: "Логотип топилмади" },
  "Logo fayli juda katta (ko'pi bilan 2 MB)": {
    uz: "Logo fayli juda katta (ko'pi bilan 2 MB)",
    ru: "Файл логотипа слишком большой (не более 2 МБ)",
    uzc: "Логотип файли жуда катта (кўпи билан 2 МБ)",
  },
  "Logo faqat PNG, JPEG yoki WebP bo'lishi mumkin": {
    uz: "Logo faqat PNG, JPEG yoki WebP bo'lishi mumkin",
    ru: "Логотип может быть только PNG, JPEG или WebP",
    uzc: "Логотип фақат PNG, JPEG ёки WebP бўлиши мумкин",
  },
  "Logo rasmi o'qilmadi yoki buzilgan": {
    uz: "Logo rasmi o'qilmadi yoki buzilgan",
    ru: "Изображение логотипа не читается или повреждено",
    uzc: "Логотип расми ўқилмади ёки бузилган",
  },
  "Logo o'lchami juda katta (ko'pi bilan 4096×4096 piksel)": {
    uz: "Logo o'lchami juda katta (ko'pi bilan 4096×4096 piksel)",
    ru: "Размер логотипа слишком большой (не более 4096×4096 пикселей)",
    uzc: "Логотип ўлчами жуда катта (кўпи билан 4096×4096 пиксел)",
  },
  "Logo juda kichik (kamida 16×16 piksel)": {
    uz: "Logo juda kichik (kamida 16×16 piksel)",
    ru: "Логотип слишком маленький (не менее 16×16 пикселей)",
    uzc: "Логотип жуда кичик (камида 16×16 пиксел)",
  },
  "Animatsiyali rasm logo sifatida qabul qilinmaydi": {
    uz: "Animatsiyali rasm logo sifatida qabul qilinmaydi",
    ru: "Анимированное изображение нельзя использовать как логотип",
    uzc: "Анимацияли расм логотип сифатида қабул қилинмайди",
  },
  "Qaytarish topilmadi": { uz: "Qaytarish topilmadi", ru: "Возврат не найден", uzc: "Қайтариш топилмади" },
  "Bu hujjatning asl cheki allaqachon chop etilgan — nusxa chop eting": {
    uz: "Bu hujjatning asl cheki allaqachon chop etilgan — nusxa chop eting",
    ru: "Оригинал чека по этому документу уже напечатан — печатайте копию",
    uzc: "Бу ҳужжатнинг асл чеки аллақачон чоп этилган — нусха чоп этинг",
  },
  "Chop etish holati yakunlangan — o'zgartirib bo'lmaydi": {
    uz: "Chop etish holati yakunlangan — o'zgartirib bo'lmaydi",
    ru: "Статус печати уже окончательный — изменить нельзя",
    uzc: "Чоп этиш ҳолати якунланган — ўзгартириб бўлмайди",
  },
  "Chop etish so'rovi noto'g'ri": {
    uz: "Chop etish so'rovi noto'g'ri",
    ru: "Некорректный запрос печати",
    uzc: "Чоп этиш сўрови нотўғри",
  },
};

// Dinamik matnlar: "Chek sozlamasi noto'g'ri: <maydon>" va eski validator "receipt: noma'lum maydon '<f>'".
const RECEIPT_RE: { re: RegExp; uz: string; ru: string; uzc: string }[] = [
  {
    re: /^Chek sozlamasi noto'g'ri: (.+)$/,
    uz: "Chek sozlamasi noto'g'ri: $1",
    ru: "Неверная настройка чека: $1",
    uzc: "Чек созламаси нотўғри: $1",
  },
  {
    re: /^receipt: noma'lum maydon '(.+)'$/,
    uz: "Chek sozlamasida noma'lum maydon: $1",
    ru: "Неизвестное поле настройки чека: $1",
    uzc: "Чек созламасида номаълум майдон: $1",
  },
];

function pick(tr: Tr): string {
  let lang: string;
  try { lang = useLang.getState().lang; } catch { return tr.uz; }
  if (lang === "uzc") return tr.uzc;
  if (lang === "ru" || lang === "ky") return tr.ru;   // ky -> ru (boshqa server lug'atlaridagidek)
  return tr.uz;
}

export function translateReceiptError(msg: string): string | null {
  if (!msg || typeof msg !== "string") return null;
  const hit = RECEIPT_ERRORS[msg];
  if (hit) return pick(hit);
  for (const r of RECEIPT_RE) {
    const m = msg.match(r.re);
    if (m) return pick({ uz: msg.replace(r.re, r.uz), ru: msg.replace(r.re, r.ru), uzc: msg.replace(r.re, r.uzc) });
  }
  return null;
}
