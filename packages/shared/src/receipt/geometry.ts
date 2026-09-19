// HTML va ESC/POS renderer'lari uchun UMUMIY o'lchamlar: QR/shtrix-kod qog'ozda ikkalasida bir xil
// kattalikda chiqsin (oldindan ko'rish = chop etilgan chek).
import type { Block } from "./types";

/** QR atrofidagi bo'sh hoshiya (modul) — standart 4. Server matritsasi hoshiyasiz (border 0). */
export const QR_QUIET = 4;
/** CODE128 hoshiyasi (modul) — standart ≥ 10. */
export const BARCODE_QUIET = 10;
/** 203 dpi termal printer: 8 nuqta = 1 mm. */
export const DOTS_PER_MM = 8;

/** QR moduli necha nuqta: qog'oz kengligining ~45% idan oshmasin, 1..8. */
export function qrScale(size: number, dots: number): number {
  const target = Math.floor(dots * 0.45);
  return Math.max(1, Math.min(8, Math.floor(target / (size + 2 * QR_QUIET))));
}

/** CODE128 moduli necha nuqta (1..3) — hoshiya bilan qog'ozga sig'sin. */
export function barcodeModuleDots(modules: number, dots: number): number {
  return Math.max(1, Math.min(3, Math.floor(dots / (modules + 2 * BARCODE_QUIET))));
}

export function barcodeHeightDots(dots: number): number {
  return dots <= 384 ? 64 : 80;
}

type QrBlock = Extract<Block, { t: "qr" }>;
type BarcodeBlock = Extract<Block, { t: "barcode" }>;

export function validQr(b: QrBlock): boolean {
  const n = b.size;
  return (
    Number.isInteger(n) && n >= 21 && n <= 177 && Array.isArray(b.matrix) && b.matrix.length === n &&
    b.matrix.every((r) => typeof r === "string" && r.length === n && /^[01]+$/.test(r))
  );
}

export function validBarcode(b: BarcodeBlock): boolean {
  return typeof b.modules === "string" && b.modules.length > 0 && b.modules.length <= 2000 && /^[01]+$/.test(b.modules);
}
