/**
 * Tarozi etiketkasi (vaznli EAN-13) — POS kassasi va server `GET /products/scan`
 * uchun YAGONA qoida.
 *
 * FORMAT (Fayzan do'konidan olingan REAL etiketkalar bilan tasdiqlangan):
 *
 *     27 + PLU(5) + GRAMM(5) + EAN-13 nazorat(1)   = 13 raqam
 *
 *  - Prefiks AYNAN "27" (ikki raqam). Oldin faqat birinchi raqam ("2") tekshirilardi —
 *    u holda prefiksning ikkinchi raqami PLU maydoniga oqib kirib, PLU 700000 ga surilardi.
 *  - PLU — 5 xonali SATR, yetakchi nollar SAQLANADI: "00537". Songa AYLANTIRILMAYDI
 *    (`parseInt` yetakchi nolni yo'qotadi va "12a" kabi axlatni ham qabul qilardi).
 *  - GRAMM maydoni (8–12-raqamlar) — VAZN, narx EMAS. Real etiketka dalili:
 *      2700537004264 → 0.426 kg × 350 so'm = 149.10 (etiketkada AYNAN shu summa)
 *      2700349000560 → 0.056 kg × 580 so'm =  32.48 (etiketkada AYNAN shu summa)
 *  - Gramm 0 bo'lsa etiketka VAZNLI deb qabul QILINMAYDI.
 *  - Nazorat raqami TEKSHIRILADI: mos kelmasa — bu tarozi etiketkasi emas (null).
 *
 * ETIKETKADAGI KOD ↔ BARKOD PLU ↔ BinOS `plu_code` (muhim, chalkashmasin):
 *
 *     etiketkada bosilgan KOD   000537   (6 xona, tarozi shunday chop etadi)
 *     barkod ichidagi PLU       00537    (5 xona — kanonik shakl, shu modul qaytaradi)
 *     BinOS `products.plu_code` 537      (yetakchi nolsiz — QA PC-013 qarori, DB da shunday)
 *
 * Uchalasi BITTA tarozi tovarini bildiradi. Solishtirish `pluMatches` orqali, ikkala
 * tomonni 5 xonaga to'ldirib bajariladi — ya'ni DB dagi "537" etiketkadagi "00537" ga mos keladi.
 *
 * ⚠️  SERVER NUSXASI: `apps/server/app/services/scale_barcode.py`. Ikkalasi BITTA vektor fayli bilan
 *     tekshiriladi — `tests/fixtures/scale_barcodes.json` (vitest `tests/scale-barcode.test.ts` va
 *     pytest `apps/server/tests/test_scale_barcodes.py`). Qoida o'zgarsa uchalasi birga o'zgaradi.
 */

/** Etiketka prefiksi — AYNAN shu ikki raqam. */
export const SCALE_PREFIX = "27";

/** Kanonik PLU uzunligi (barkod ichidagi maydon). */
export const PLU_DIGITS = 5;

export interface ScaleLabel {
  /** Prefiks — doim `SCALE_PREFIX`. */
  prefix: string;
  /** Kanonik PLU: AYNAN 5 belgili satr, yetakchi nollar saqlanadi ("00537"). */
  plu: string;
  /** Vazn, gramm (> 0). */
  grams: number;
  /** EAN-13 nazorat raqami (tekshirilgan, 0–9). */
  checksum: number;
}

/** Faqat ASCII raqamlar — yetakchi nollar saqlanadi. */
export function scaleDigits(raw: string): string {
  return String(raw ?? "").replace(/\D/g, "");
}

/**
 * EAN-13 nazorat raqami: 12 raqamli tanadan hisoblanadi.
 * Og'irliklar chapdan o'nga 1,3,1,3…; natija `(10 - sum % 10) % 10`.
 */
export function ean13Checksum(body12: string): number {
  let sum = 0;
  for (let i = 0; i < 12; i++) sum += (body12.charCodeAt(i) - 48) * (i % 2 === 0 ? 1 : 3);
  return (10 - (sum % 10)) % 10;
}

/**
 * PLU ni kanonik shaklga keltiradi: faqat raqamlar, 5 xonaga to'ldiriladi.
 * "537" → "00537" · "00537" → "00537" · "12a" → "00012" · "" / 6+ xona → `null`.
 *
 * ⚠️  6 xonali kiritma ATAYLAB rad etiladi (`null`), etiketkada bosilgan 6 xonali KOD
 *     (000537) bilan chalkashmasin: barkod maydoni 5 xonali va BinOS shuni saqlaydi.
 */
export function normalizePlu(raw: unknown): string | null {
  const d = scaleDigits(raw as string);
  if (!d || d.length > PLU_DIGITS) return null;
  return d.padStart(PLU_DIGITS, "0");
}

/**
 * Kod TAROZI NOM FAZOSIDAMI: 13 raqam va prefiks `27`. Nazorat raqami TEKSHIRILMAYDI.
 *
 * ⚠️  NEGA ALOHIDA: `parseScaleBarcode` buzuq etiketkada `null` qaytaradi va chaqiruvchi uni
 *     "oddiy shtrix-kod" deb qayta talqin qilishi mumkin edi. Agar katalogda tasodifan AYNAN
 *     shu 13 raqamli kod barkod sifatida yotgan bo'lsa, bitta raqami noto'g'ri o'qilgan tarozi
 *     yorlig'i BOSHQA tovarni sotib yuborardi. `27` bilan boshlanadigan 13 raqamli kod —
 *     TAROZI hujjati; u yerda xato bo'lsa javob "qayta skanerlang", "boshqa tovar" emas.
 */
export function looksLikeScaleLabel(raw: string): boolean {
  const d = scaleDigits(raw);
  return d.length === 13 && d.slice(0, 2) === SCALE_PREFIX;
}

/** Vaznli etiketka bo'lsa `ScaleLabel`, aks holda `null`. */
export function parseScaleBarcode(raw: string): ScaleLabel | null {
  const digits = scaleDigits(raw);
  if (digits.length !== 13) return null;
  if (digits.slice(0, 2) !== SCALE_PREFIX) return null;
  const checksum = digits.charCodeAt(12) - 48;
  if (ean13Checksum(digits.slice(0, 12)) !== checksum) return null;
  const grams = parseInt(digits.slice(7, 12), 10);
  if (!(grams > 0)) return null;
  return { prefix: SCALE_PREFIX, plu: digits.slice(2, 7), grams, checksum };
}

/**
 * Mahsulotning `plu_code` i etiketkadagi PLU ga mosmi.
 * Ikkala tomon 5 xonaga to'ldiriladi — DB dagi "537" etiketkadagi "00537" ga MOS keladi.
 */
export function pluMatches(pluCode: unknown, plu: string | number): boolean {
  const a = normalizePlu(pluCode);
  const b = normalizePlu(plu);
  return a !== null && b !== null && a === b;
}

/** Kilogramm — AYNAN 3 kasr xonali satr (float EMAS): 1234 -> "1.234". */
export function scaleQty(grams: number): string {
  return `${Math.floor(grams / 1000)}.${String(grams % 1000).padStart(3, "0")}`;
}
