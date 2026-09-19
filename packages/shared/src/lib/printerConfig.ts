// QURILMA printeri sozlamasi (Phase 5F) — shu kompyuterning o'zida (localStorage), serverda EMAS.
//
// Nega qurilmada: printer — jismoniy qurilmaning xossasi. Ilgari `receipt.printer` KOMPANIYA sozlamasi
// edi: bitta nom hamma filial va kassaga tarqalardi, boshqa kompyuterda bunday printer yo'q edi.
// ⚠️  Kalit server bo'yicha AJRATILMAYDI (`nsKey` yo'q): server manzili o'zgarsa ham printer o'sha
//     printer. (Chek jurnali va profil keshi esa server bo'yicha ajratiladi — printing.ts.)
// ⚠️  localStorage — ishonchsiz kirish: o'qishda har maydon tekshiriladi, yaroqsizi standartga qaytadi.
import { CACHE, cacheGet } from "@/lib/offline";
import { GENERIC_PROFILE_ID, PROFILES, profileFor, type PaperWidth, type PrinterProfile } from "@/receipt";

export type PrinterTransport = "system" | "escpos_lan" | "escpos_spooler" | "browser";
/**
 * HTML (tizim printeri) sahifa o'lchami: "exact" — sahifa AYNAN chek o'lchamida (kenglik × balandlik,
 * chek bo'linmaydi); "driver" — drayverning standart qog'ozi, CSS `@page` da ham o'lcham yo'q (ba'zi
 * drayverlar maxsus o'lchamni rad etadi — 5F'dan oldingi xulq).
 */
export type PrinterPageSize = "exact" | "driver";

export interface PrinterDeviceConfig {
  transport: PrinterTransport;
  printer?: string;
  host?: string;
  port?: number;
  profile_id: string;
  width_mm?: PaperWidth | null;
  /** `readPrinterConfig()` doim to'ldiradi; yo'q/noma'lum — "exact" (standart). */
  page_size?: PrinterPageSize;
  overrides?: Partial<PrinterProfile>;
}

export const PRINTER_CONFIG_KEY = "savdoos_printer_device";
export const TRANSPORTS: readonly PrinterTransport[] = ["system", "escpos_lan", "escpos_spooler", "browser"];
export const PAGE_SIZES: readonly PrinterPageSize[] = ["exact", "driver"];
export const DEFAULT_LAN_PORT = 9100;

/** Electron ko'prigi bormi (brauzer/e2e da yo'q). */
export function hasElectronPrint(): boolean {
  try {
    return typeof window !== "undefined" && !!window.savdoosPrint && typeof window.savdoosPrint.listPrinters === "function";
  } catch {
    return false;
  }
}

/**
 * Standart model — "generic" (kenglikka bog'lanmagan): kenglik chek shablonidan (yoki qo'lda 58/80).
 * Tegilmagan sozlama 58 mm shablonni 80 mm/48 ustun qilib yubormasin (ilgari standart "generic80" edi).
 */
export function defaultPrinterConfig(): PrinterDeviceConfig {
  return { transport: hasElectronPrint() ? "system" : "browser", profile_id: GENERIC_PROFILE_ID, page_size: "exact" };
}

const knownProfile = (id: unknown): id is string =>
  typeof id === "string" && (id === GENERIC_PROFILE_ID || Object.prototype.hasOwnProperty.call(PROFILES, id));

const oneOf = <T extends string>(v: unknown, allowed: readonly T[]): v is T =>
  typeof v === "string" && (allowed as readonly string[]).includes(v);
const intIn = (v: unknown, lo: number, hi: number): v is number =>
  typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;

/** Imkoniyat o'zgartirishlari — `profileFor` qabul qiladigan kalit/qiymatlargina (qolgani tashlanadi). */
function cleanOverrides(raw: unknown): Partial<PrinterProfile> | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const o = raw as Record<string, unknown>;
  const out: Partial<PrinterProfile> = {};
  if (oneOf(o.cut, ["none", "partial", "full"] as const)) out.cut = o.cut;
  if (oneOf(o.qr, ["native", "raster", "none"] as const)) out.qr = o.qr;
  if (oneOf(o.barcode, ["native", "raster", "none"] as const)) out.barcode = o.barcode;
  if (typeof o.raster === "boolean") out.raster = o.raster;
  if (typeof o.status_query === "boolean") out.status_query = o.status_query;
  if (intIn(o.feed_lines, 0, 10)) out.feed_lines = o.feed_lines;
  if (intIn(o.dots, 256, 576) && o.dots % 8 === 0) out.dots = o.dots;
  const cp = o.codepage as Record<string, unknown> | undefined;
  if (cp && typeof cp === "object" && oneOf(cp.name, ["cp866", "cp1251"] as const) && intIn(cp.escT, 0, 255)) {
    out.codepage = { name: cp.name, escT: cp.escT };
  }
  return Object.keys(out).length ? out : undefined;
}

// Boshqaruv/bidi belgilarisiz bir qatorli satr.
function cleanStr(v: unknown, max: number): string | undefined {
  if (typeof v !== "string") return undefined;
  // eslint-disable-next-line no-control-regex
  const s = v.replace(/[\x00-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]/g, "").trim().slice(0, max);
  return s || undefined;
}

export function sanitizePrinterConfig(raw: unknown): PrinterDeviceConfig {
  const def = defaultPrinterConfig();
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return def;
  const r = raw as Record<string, unknown>;
  const cfg: PrinterDeviceConfig = {
    transport: TRANSPORTS.includes(r.transport as PrinterTransport) ? (r.transport as PrinterTransport) : def.transport,
    // Saqlangan aniq model (generic80 ham) o'zgarmaydi — foydalanuvchi uni tanlaganmi, bilib bo'lmaydi.
    profile_id: knownProfile(r.profile_id) ? r.profile_id : def.profile_id,
  };
  const printer = cleanStr(r.printer, 200);
  if (printer) cfg.printer = printer;
  const host = cleanStr(r.host, 64);
  if (host) cfg.host = host;
  if (typeof r.port === "number" && Number.isInteger(r.port) && r.port >= 1 && r.port <= 65535) cfg.port = r.port;
  if (r.width_mm === 58 || r.width_mm === 80) cfg.width_mm = r.width_mm;
  else if (r.width_mm === null) cfg.width_mm = null;
  // Noma'lum/yo'q qiymat (eski sozlama) — standart "exact".
  cfg.page_size = r.page_size === "driver" ? "driver" : "exact";
  const ov = cleanOverrides(r.overrides);
  if (ov) cfg.overrides = ov;
  return cfg;
}

let listeners: (() => void)[] = [];

export function subscribePrinterConfig(fn: () => void): () => void {
  listeners.push(fn);
  return () => {
    listeners = listeners.filter((l) => l !== fn);
  };
}

export function readPrinterConfig(): PrinterDeviceConfig {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(PRINTER_CONFIG_KEY);
  } catch {
    return defaultPrinterConfig();
  }
  if (raw !== null) {
    try {
      return sanitizePrinterConfig(JSON.parse(raw));
    } catch {
      return defaultPrinterConfig();
    }
  }
  // Bir martalik ko'chirish: qurilma sozlamasi hali yo'q, eski KOMPANIYA sozlamasida printer nomi bor —
  // shu kompyuter avval o'sha printerga chop etardi, yangilanishdan keyin ham shunday qolsin.
  const legacy = cacheGet<{ receipt?: { printer?: unknown } }>(CACHE.settings, {}).receipt?.printer;
  const printer = cleanStr(legacy, 200);
  if (!printer) return defaultPrinterConfig();
  const cfg: PrinterDeviceConfig = { ...defaultPrinterConfig(), printer };
  writePrinterConfig(cfg);
  return cfg;
}

export function writePrinterConfig(cfg: PrinterDeviceConfig): boolean {
  const clean = sanitizePrinterConfig(cfg);
  try {
    localStorage.setItem(PRINTER_CONFIG_KEY, JSON.stringify(clean));
  } catch {
    return false;
  }
  for (const l of listeners) l();
  return true;
}

/** HTML sahifa rejimi (sozlamada yo'q yoki noma'lum — "exact"). */
export function pageSizeOf(cfg: PrinterDeviceConfig): PrinterPageSize {
  return cfg.page_size === "driver" ? "driver" : "exact";
}

/**
 * Chop etish kengligi — layout VA kodlovchi uchun BITTA manba (ikkalasi bir xil ustun sonini ko'rsin):
 * 1) qurilmada qo'lda tanlangan 58/80; 2) ESC/POS (LAN/RAW) da tanlangan KENGLIKLI printer modeli
 * ("generic" dan boshqa har qanday) — "Xprinter (58 mm)" tanlangan bo'lsa 80 mm shablon 48 ustun bo'lib
 * 32 ustunli printerga KETMAYDI; 3) aks holda (standart "generic" ham) chek shablonidagi kenglik.
 */
export function effectiveWidth(cfg: PrinterDeviceConfig, templateWidth: PaperWidth): PaperWidth {
  if (cfg.width_mm === 58 || cfg.width_mm === 80) return cfg.width_mm;
  if ((cfg.transport === "escpos_lan" || cfg.transport === "escpos_spooler") && cfg.profile_id !== GENERIC_PROFILE_ID) {
    const w = Object.prototype.hasOwnProperty.call(PROFILES, cfg.profile_id) ? PROFILES[cfg.profile_id].width_mm : undefined;
    if (w === 58 || w === 80) return w;
  }
  return templateWidth === 58 ? 58 : 80;
}

/** Sozlama + chek shabloni kengligi → chop etishda ishlatiladigan profil. */
export function effectiveProfile(cfg: PrinterDeviceConfig, templateWidth: PaperWidth): PrinterProfile {
  return profileFor(cfg.profile_id, effectiveWidth(cfg, templateWidth), cfg.overrides);
}
