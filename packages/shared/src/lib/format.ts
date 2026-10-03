import { currencyLabel } from "@/receipt/format";
import { useAuth } from "@/store/auth";
import { useLang } from "@/store/lang";

// ─── VALYUTA MANBASI ─────────────────────────────────────────────────────────
// Pul birligini `company.currency` (ISO-4217) belgilaydi, UI tili EMAS. Ilgari shu faylda
// `CUR[lang]` jadvali bor edi va o'zbekcha interfeys KGS tenantda ham "so'm" ko'rsatardi —
// ya'ni til pul birligini hal qilardi. Yorliq jadvali endi BITTA joyda: `@/receipt/format`
// (`receipt/` mustaqil modul bo'lgani uchun u `lib/` dan import qila olmaydi, teskarisi mumkin).
//
// Valyuta login javobidan keladi (`employee.company_currency`). Yo'q bo'lsa — eski server yoki
// eski tenant — `currencyLabel` ATAYLAB tilga asoslangan eski yorliqqa qaytadi.
export function companyCurrency(): string | null | undefined {
  try {
    return useAuth.getState().employee?.company_currency;
  } catch {
    return undefined;
  }
}

/**
 * Joriy pul BIRLIGI (yorliq): do'kon valyutasi + UI tili.
 *
 * Matn ichiga birlik qo'yish kerak bo'lganda SHU ishlatiladi — tarjima satriga
 * birlikni YOZIB QO'YISH (masalan «0 so'm») kontraktni buzadi, chunki u holda
 * birlikni TIL hal qilardi.
 */
export function currencyUnit(): string {
  return currencyLabel(companyCurrency(), useLang.getState().lang);
}

export function fmt(n: number): string {
  // IEEE-754 float underflow tuzatish: tarozi qatorining ANIQ .5 qiymati (masalan 0.102kg × 1250)
  // float'da .4999… ga tushadi; oddiy Math.round uni PASTGA yaxlitlar edi va POSKassa payTotal
  // (Math.round(subtotal + 1e-6)) bilan 1 som farq qilardi — ekranda "qator/oraliq-jami" Total'dan
  // past ko'rinardi (QA CART-01). payTotal bilan AYNAN bir xil epsilon → butun displey izchil.
  const x = n || 0;
  const v = Math.round(x + (x >= 0 ? 1e-6 : -1e-6));
  const cur = currencyLabel(companyCurrency(), useLang.getState().lang);
  return new Intl.NumberFormat("ru-RU").format(v).replace(/,/g, " ") + " " + cur;
}

export function fmtShort(n: number): string {
  const lang = useLang.getState().lang;
  const mln = lang === "uz" ? "mln" : "млн";
  const ming = lang === "ru" ? "тыс" : lang === "ky" ? "миң" : lang === "uzc" ? "минг" : "ming";
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(".", ",") + " " + mln;
  if (n >= 1e3) return Math.round(n / 1e3) + " " + ming;
  return String(Math.round(n || 0));
}

// Server UTC vaqtini mahalliy Date'ga keltiradi. SQLite (dev) tz belgisisiz UTC string
// berishi mumkin — 'Z' qo'shamiz (prod'da '+00:00' keladi). Yaroqsiz bo'lsa null.
export function parseServerTime(s: string | null | undefined): Date | null {
  if (!s) return null;
  const d = new Date(/[Z+]|[+-]\d\d:\d\d$/.test(s.slice(10)) ? s : s + "Z");
  return isNaN(d.getTime()) ? null : d;
}
