// Printer profillari — ESC/POS imkoniyatlari (kesish, QR, shtrix-kod, raster, kod sahifasi).
//
// ⚠️  Barcha presetlar ishlab chiqaruvchi hujjatlariga asoslangan (vendor documentation based),
//     real qurilmada SINALMAGAN (not hardware-verified). Aniq model boshqacha bo'lsa — qurilma
//     sozlamasidagi `overrides` bilan to'g'rilanadi (masalan kesgichsiz printer: cut "none").
import type { PaperWidth, PrinterProfile } from "./types";
import { COLS, DOTS } from "./types";

const base = (w: PaperWidth) => ({ width_mm: w, dots: DOTS[w], cols: COLS[w] });
const preset = (p: PrinterProfile): Readonly<PrinterProfile> =>
  Object.freeze({ ...p, codepage: Object.freeze({ ...p.codepage }) });

/**
 * "Universal (kenglik chek shablonidan)" — standart model: kengligi o'zi YO'Q, `profileFor("generic", w)`
 * AYNAN o'sha kenglikdagi generic preset (`generic58`/`generic80`, imkoniyatlari bilan). Ro'yxatdagi
 * yozuv (80 mm) faqat tanlov ro'yxati va eski sozlama tekshiruvi uchun — kenglik manbai EMAS.
 */
export const GENERIC_PROFILE_ID = "generic";

export const PROFILES: Readonly<Record<string, Readonly<PrinterProfile>>> = Object.freeze({
  generic: preset({
    id: GENERIC_PROFILE_ID, label: "Generic ESC/POS", ...base(80),
    cut: "partial", qr: "raster", barcode: "raster", raster: true,
    codepage: { name: "cp866", escT: 17 }, status_query: false, feed_lines: 4,
  }),
  // Noma'lum 58 mm printer: kesgich yo'q deb hisoblaymiz, QR/shtrix-kod raster rasm sifatida (eng keng mos).
  generic58: preset({
    id: "generic58", label: "Generic ESC/POS 58 mm", ...base(58),
    cut: "none", qr: "raster", barcode: "raster", raster: true,
    codepage: { name: "cp866", escT: 17 }, status_query: false, feed_lines: 4,
  }),
  generic80: preset({
    id: "generic80", label: "Generic ESC/POS 80 mm", ...base(80),
    cut: "partial", qr: "raster", barcode: "raster", raster: true,
    codepage: { name: "cp866", escT: 17 }, status_query: false, feed_lines: 4,
  }),
  // Epson TM-T20/T88 oilasi: GS ( k QR, GS k CODE128, DLE EOT holat so'rovi, GS ( D real-vaqt buyruqlarini
  // o'chirish (Epson ESC/POS hujjati).
  epson80: preset({
    id: "epson80", label: "Epson TM (80 mm)", ...base(80),
    cut: "partial", qr: "native", barcode: "native", raster: true,
    codepage: { name: "cp866", escT: 17 }, status_query: true, feed_lines: 4, realtime_disable: true,
  }),
  xprinter80: preset({
    id: "xprinter80", label: "Xprinter (80 mm)", ...base(80),
    cut: "partial", qr: "native", barcode: "native", raster: true,
    codepage: { name: "cp866", escT: 17 }, status_query: false, feed_lines: 4,
  }),
  xprinter58: preset({
    id: "xprinter58", label: "Xprinter (58 mm)", ...base(58),
    cut: "none", qr: "native", barcode: "native", raster: true,
    codepage: { name: "cp866", escT: 17 }, status_query: false, feed_lines: 4,
  }),
});

const oneOf = <T extends string>(v: unknown, allowed: readonly T[]): v is T =>
  typeof v === "string" && (allowed as readonly string[]).includes(v);
const intIn = (v: unknown, lo: number, hi: number): v is number =>
  typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;

/**
 * Profilni hal qiladi: "generic", noma'lum yoki bo'sh id → `generic{width}`. Kenglik HAR DOIM `width` dan olinadi
 * (dots/cols ham) — layout va kodlovchi bir xil ustun sonini ko'rsin; imkoniyatlar esa tanlangan
 * modeldan. `overrides` qurilma localStorage'idan keladi — ishonmaymiz: faqat ma'lum kalitlar va
 * yaroqli qiymatlar qabul qilinadi, qolgani jimgina tashlanadi.
 */
export function profileFor(
  id: string | undefined,
  width: PaperWidth,
  overrides?: Partial<PrinterProfile>,
): PrinterProfile {
  const w: PaperWidth = width === 58 ? 58 : 80;
  // "generic" — kenglikka qarab generic58/generic80 (58 mm da kesgichsiz preset).
  const known = id && id !== GENERIC_PROFILE_ID && Object.prototype.hasOwnProperty.call(PROFILES, id) ? PROFILES[id] : undefined;
  const src = known ?? PROFILES[w === 58 ? "generic58" : "generic80"];
  const p: PrinterProfile = { ...src, codepage: { ...src.codepage }, ...base(w) };
  const o = (overrides ?? {}) as Record<string, unknown>;
  if (typeof o.label === "string" && o.label.length <= 80) p.label = o.label;
  if (oneOf(o.cut, ["none", "partial", "full"] as const)) p.cut = o.cut;
  if (oneOf(o.qr, ["native", "raster", "none"] as const)) p.qr = o.qr;
  if (oneOf(o.barcode, ["native", "raster", "none"] as const)) p.barcode = o.barcode;
  if (typeof o.raster === "boolean") p.raster = o.raster;
  if (typeof o.status_query === "boolean") p.status_query = o.status_query;
  if (typeof o.realtime_disable === "boolean") p.realtime_disable = o.realtime_disable;
  if (intIn(o.feed_lines, 0, 10)) p.feed_lines = o.feed_lines;
  // Ba'zi 80 mm printerlarning bosma maydoni 512 nuqta — faqat kichraytirish mumkin, 8 ga karrali.
  if (intIn(o.dots, 256, DOTS[w]) && o.dots % 8 === 0) p.dots = o.dots;
  const cp = o.codepage as Record<string, unknown> | undefined;
  if (cp && typeof cp === "object" && oneOf(cp.name, ["cp866", "cp1251"] as const) && intIn(cp.escT, 0, 255)) {
    p.codepage = { name: cp.name, escT: cp.escT };
  }
  return p;
}
