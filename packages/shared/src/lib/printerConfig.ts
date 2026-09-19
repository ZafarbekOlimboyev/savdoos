// QURILMA printeri sozlamasi (Phase 5F) — shu kompyuterning o'zida (localStorage), serverda EMAS.
//
// Nega qurilmada: printer — jismoniy qurilmaning xossasi. Ilgari `receipt.printer` KOMPANIYA sozlamasi
// edi: bitta nom hamma filial va kassaga tarqalardi, boshqa kompyuterda bunday printer yo'q edi.
// ⚠️  Kalit server bo'yicha AJRATILMAYDI (`nsKey` yo'q): server manzili o'zgarsa ham printer o'sha
//     printer. (Chek jurnali va profil keshi esa server bo'yicha ajratiladi — printing.ts.)
// ⚠️  localStorage — ishonchsiz kirish: o'qishda har maydon tekshiriladi, yaroqsizi standartga qaytadi.
import { CACHE, cacheGet } from "@/lib/offline";
import { PROFILES, profileFor, type PaperWidth, type PrinterProfile } from "@/receipt";

export type PrinterTransport = "system" | "escpos_lan" | "escpos_spooler" | "browser";

export interface PrinterDeviceConfig {
  transport: PrinterTransport;
  printer?: string;
  host?: string;
  port?: number;
  profile_id: string;
  width_mm?: PaperWidth | null;
  overrides?: Partial<PrinterProfile>;
}

export const PRINTER_CONFIG_KEY = "savdoos_printer_device";
export const TRANSPORTS: readonly PrinterTransport[] = ["system", "escpos_lan", "escpos_spooler", "browser"];
export const DEFAULT_LAN_PORT = 9100;

/** Electron ko'prigi bormi (brauzer/e2e da yo'q). */
export function hasElectronPrint(): boolean {
  try {
    return typeof window !== "undefined" && !!window.savdoosPrint && typeof window.savdoosPrint.listPrinters === "function";
  } catch {
    return false;
  }
}

export function defaultPrinterConfig(): PrinterDeviceConfig {
  return { transport: hasElectronPrint() ? "system" : "browser", profile_id: "generic80" };
}

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
    profile_id: typeof r.profile_id === "string" && Object.prototype.hasOwnProperty.call(PROFILES, r.profile_id)
      ? r.profile_id : def.profile_id,
  };
  const printer = cleanStr(r.printer, 200);
  if (printer) cfg.printer = printer;
  const host = cleanStr(r.host, 64);
  if (host) cfg.host = host;
  if (typeof r.port === "number" && Number.isInteger(r.port) && r.port >= 1 && r.port <= 65535) cfg.port = r.port;
  if (r.width_mm === 58 || r.width_mm === 80) cfg.width_mm = r.width_mm;
  else if (r.width_mm === null) cfg.width_mm = null;
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

/** Sozlama + chek shabloni kengligi → chop etishda ishlatiladigan profil. */
export function effectiveProfile(cfg: PrinterDeviceConfig, templateWidth: PaperWidth): PrinterProfile {
  const width: PaperWidth = cfg.width_mm === 58 || cfg.width_mm === 80 ? cfg.width_mm : templateWidth === 58 ? 58 : 80;
  return profileFor(cfg.profile_id, width, cfg.overrides);
}
