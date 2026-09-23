/**
 * Tarozi etiketkasi (vaznli EAN-13, prefiks "2") — POS kassasi va server `GET /products/scan`
 * uchun YAGONA qoida.
 *
 * FORMAT: 13 raqam, birinchisi "2":  2 + PLU(6) + gramm(5) + nazorat(1).
 *  - Nazorat raqami TEKSHIRILMAYDI (POS xulqi o'zgarmaydi).
 *  - Gramm 0 bo'lsa etiketka VAZNLI deb qabul QILINMAYDI (POS ilgari ham `grams > 0` talab qilardi).
 *  - PLU mahsulotning `plu_code` i bilan `parseInt(String(plu_code), 10)` orqali solishtiriladi.
 *
 * ⚠️  SERVER NUSXASI: `apps/server/app/services/scale_barcode.py`. Ikkalasi BITTA vektor fayli bilan
 *     tekshiriladi — `tests/fixtures/scale_barcodes.json` (vitest `tests/scale-barcode.test.ts` va
 *     pytest `apps/server/tests/test_scale_barcodes.py`). Qoida o'zgarsa uchalasi birga o'zgaradi.
 */

export interface ScaleLabel {
  /** Etiketkadagi PLU (yetakchi nollarsiz son). */
  plu: number;
  /** Vazn, gramm (> 0). */
  grams: number;
}

/** Faqat ASCII raqamlar — yetakchi nollar saqlanadi. */
export function scaleDigits(raw: string): string {
  return String(raw ?? "").replace(/\D/g, "");
}

/** Vaznli etiketka bo'lsa `{plu, grams}`, aks holda `null`. */
export function parseScaleBarcode(raw: string): ScaleLabel | null {
  const digits = scaleDigits(raw);
  if (digits.length !== 13 || digits[0] !== "2") return null;
  const plu = parseInt(digits.slice(1, 7), 10);
  const grams = parseInt(digits.slice(7, 12), 10);
  if (!(grams > 0)) return null;
  return { plu, grams };
}

/** Mahsulotning `plu_code` i etiketkadagi PLU ga mosmi (POS: `p.plu_code && parseInt(...) === plu`). */
export function pluMatches(pluCode: unknown, plu: number): boolean {
  return !!pluCode && parseInt(String(pluCode), 10) === plu;
}

/** Kilogramm — AYNAN 3 kasr xonali satr (float EMAS): 1234 -> "1.234". */
export function scaleQty(grams: number): string {
  return `${Math.floor(grams / 1000)}.${String(grams % 1000).padStart(3, "0")}`;
}
