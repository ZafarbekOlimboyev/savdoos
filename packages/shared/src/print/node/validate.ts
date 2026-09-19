// Renderer'dan kelgan chop etish so'rovlarini QAT'IY tekshirish (Electron main).
//
// ⚠️  Renderer — ishonchsiz chegara: XSS yoki buzilgan sahifa `savdoosPrint` ni istalgan qiymat bilan
//     chaqira oladi. Shu bois har maydon turi, uzunligi va oralig'i tekshiriladi, noma'lum kalit RAD
//     etiladi va natija YANGI obyekt sifatida qaytadi (prototip/getter hiylalari main'ga o'tmaydi).
// ⚠️  LAN manzil faqat LITERAL xususiy IPv4 va 9100–9109 port: kassa kompyuteri internetdagi yoki
//     lokal xizmatlarga (127.x, 80/443...) xom TCP yuboradigan "proksi" bo'lib qolmasin.
// ⚠️  Faqat nisbiy importlar (Electron main alias'siz yig'iladi).
import type { Block, PaperWidth, PrinterProfile, ReceiptDoc } from "../../receipt/types";
import { base64DecodedLength, isBase64 } from "../../receipt/b64";
import type { PrintEscPosRequest, PrintHtmlRequest, PrintTarget } from "../bridge";

export const LIMITS = Object.freeze({
  blocks: 6000,
  lineChars: 96,
  rasterMaxWidth: 576,
  rasterMaxHeight: 4000,
  qrPayload: 700,
  qrMaxSize: 177,
  qrMinSize: 21,
  barcodeModules: 2000,
  htmlBytes: 5 * 1024 * 1024,
  printerName: 200,
  copiesMin: 1,
  copiesMax: 3,
  lanPortMin: 9100,
  lanPortMax: 9109,
  warnings: 200,
});

export type Checked<T> = { ok: true; value: T } | { ok: false; error: string };

class Invalid extends Error {}
const fail = (msg: string): never => {
  throw new Invalid(msg);
};

function isPlain(v: unknown): v is Record<string, unknown> {
  if (v === null || typeof v !== "object" || Array.isArray(v)) return false;
  const proto = Object.getPrototypeOf(v);
  return proto === Object.prototype || proto === null;
}

function obj(v: unknown, what: string, allowed: readonly string[]): Record<string, unknown> {
  if (!isPlain(v)) fail(`${what}: obyekt emas`);
  const o = v as Record<string, unknown>;
  for (const k of Object.keys(o)) if (!allowed.includes(k)) fail(`${what}: noma'lum maydon '${k.slice(0, 40)}'`);
  return o;
}

function int(v: unknown, what: string, lo: number, hi: number): number {
  if (typeof v !== "number" || !Number.isInteger(v) || v < lo || v > hi) fail(`${what}: ${lo}..${hi} butun son emas`);
  return v as number;
}

function oneOf<T extends string | number>(v: unknown, what: string, allowed: readonly T[]): T {
  if (!(allowed as readonly unknown[]).includes(v)) fail(`${what}: ruxsat etilmagan qiymat`);
  return v as T;
}

function bool(v: unknown, what: string): boolean {
  if (typeof v !== "boolean") fail(`${what}: boolean emas`);
  return v as boolean;
}

function str(v: unknown, what: string, max: number, min = 0): string {
  if (typeof v !== "string" || v.length < min || v.length > max) fail(`${what}: satr uzunligi ${min}..${max} emas`);
  return v as string;
}

const cpLen = (s: string) => Array.from(s).length;
// Printer nomi: boshqaruv belgisisiz, tirnoqsiz, "-" bilan boshlanmaydi (argv'da parametr deb o'qilmasin).
const PRINTER_NAME_RE = /^[^\x00-\x1f\x7f"]+$/;

export function printerName(v: unknown, what = "printer"): string {
  const s = str(v, what, LIMITS.printerName, 1);
  if (!PRINTER_NAME_RE.test(s) || s.startsWith("-") || s.trim() !== s) fail(`${what}: nom yaroqsiz`);
  return s;
}

/** Faqat literal nuqtali IPv4 (bosh nolsiz), xususiy/link-local diapazonlarda. */
export function isPrivateIPv4(host: unknown): boolean {
  if (typeof host !== "string" || host.length > 15) return false;
  const m = /^(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})$/.exec(host);
  if (!m) return false;
  const o = m.slice(1).map(Number);
  if (o.some((x) => x > 255)) return false;
  const [a, b] = o;
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 169 && b === 254);
}

export function isLanPort(port: unknown): boolean {
  return typeof port === "number" && Number.isInteger(port) && port >= LIMITS.lanPortMin && port <= LIMITS.lanPortMax;
}

function copies(v: unknown): number | undefined {
  return v === undefined ? undefined : int(v, "copies", LIMITS.copiesMin, LIMITS.copiesMax);
}

function block(v: unknown, i: number): Block {
  const w = `blocks[${i}]`;
  if (!isPlain(v)) fail(`${w}: obyekt emas`);
  const t = (v as Record<string, unknown>).t;
  switch (t) {
    case "line": {
      const o = obj(v, w, ["t", "text", "bold", "size"]);
      const text = str(o.text, `${w}.text`, LIMITS.lineChars * 2);
      if (cpLen(text) > LIMITS.lineChars) fail(`${w}.text: ${LIMITS.lineChars} belgidan uzun`);
      const b: Block = { t: "line", text };
      if (o.bold !== undefined) b.bold = bool(o.bold, `${w}.bold`);
      if (o.size !== undefined) b.size = oneOf(o.size, `${w}.size`, [1, 2] as const);
      return b;
    }
    case "rule": {
      const o = obj(v, w, ["t", "char"]);
      return { t: "rule", char: oneOf(o.char, `${w}.char`, ["-", "="] as const) };
    }
    case "feed": {
      const o = obj(v, w, ["t", "lines"]);
      return { t: "feed", lines: int(o.lines, `${w}.lines`, 0, 10) };
    }
    case "cut": {
      const o = obj(v, w, ["t", "kind"]);
      return { t: "cut", kind: oneOf(o.kind, `${w}.kind`, ["partial", "full"] as const) };
    }
    case "logo": {
      // png_data_uri — HTML uchun; ESC/POS'ga kerak emas, main'ga olib o'tilmaydi.
      const o = obj(v, w, ["t", "width", "height", "raster_b64", "png_data_uri"]);
      const width = int(o.width, `${w}.width`, 8, LIMITS.rasterMaxWidth);
      if (width % 8 !== 0) fail(`${w}.width: 8 ga karrali emas`);
      const height = int(o.height, `${w}.height`, 1, LIMITS.rasterMaxHeight);
      const need = (width / 8) * height;
      const raster = str(o.raster_b64, `${w}.raster_b64`, Math.ceil(need / 3) * 4 + 4);
      if (!isBase64(raster) || base64DecodedLength(raster) !== need) fail(`${w}.raster_b64: o'lchamga mos emas`);
      if (o.png_data_uri !== undefined && typeof o.png_data_uri !== "string") fail(`${w}.png_data_uri: satr emas`);
      return { t: "logo", width, height, raster_b64: raster };
    }
    case "qr": {
      const o = obj(v, w, ["t", "payload", "size", "matrix"]);
      const payload = str(o.payload, `${w}.payload`, LIMITS.qrPayload, 1);
      if (/[\x00-\x1f\x7f]/.test(payload)) fail(`${w}.payload: boshqaruv belgisi`);
      const size = int(o.size, `${w}.size`, LIMITS.qrMinSize, LIMITS.qrMaxSize);
      if (!Array.isArray(o.matrix) || o.matrix.length !== size) fail(`${w}.matrix: o'lcham mos emas`);
      const matrix = (o.matrix as unknown[]).map((r, y) => {
        if (typeof r !== "string" || r.length !== size || !/^[01]+$/.test(r)) fail(`${w}.matrix[${y}]: yaroqsiz`);
        return r as string;
      });
      return { t: "qr", payload, size, matrix };
    }
    case "barcode": {
      const o = obj(v, w, ["t", "payload", "modules"]);
      const payload = str(o.payload, `${w}.payload`, 64, 1);
      if (!/^[\x20-\x7e]{1,64}$/.test(payload)) fail(`${w}.payload: faqat ASCII 0x20–0x7E`);
      const modules = str(o.modules, `${w}.modules`, LIMITS.barcodeModules, 1);
      if (!/^[01]+$/.test(modules)) fail(`${w}.modules: faqat 0/1`);
      return { t: "barcode", payload, modules };
    }
    default:
      return fail(`${w}: noma'lum blok turi`);
  }
}

export function checkDoc(v: unknown): ReceiptDoc {
  const o = obj(v, "doc", ["width_mm", "cols", "blocks", "warnings"]);
  const width_mm = oneOf(o.width_mm, "doc.width_mm", [58, 80] as const) as PaperWidth;
  const cols = int(o.cols, "doc.cols", 16, LIMITS.lineChars);
  if (!Array.isArray(o.blocks)) fail("doc.blocks: massiv emas");
  const raw = o.blocks as unknown[];
  if (raw.length > LIMITS.blocks) fail(`doc.blocks: ${LIMITS.blocks} dan ko'p`);
  if (o.warnings !== undefined) {
    if (!Array.isArray(o.warnings) || o.warnings.length > LIMITS.warnings ||
        !o.warnings.every((x) => typeof x === "string" && x.length <= 200)) {
      fail("doc.warnings: yaroqsiz");
    }
  }
  return { width_mm, cols, blocks: raw.map(block), warnings: [] };
}

export function checkProfile(v: unknown): PrinterProfile {
  const o = obj(v, "profile", [
    "id", "label", "width_mm", "dots", "cols", "cut", "qr", "barcode", "raster", "codepage", "status_query", "feed_lines",
  ]);
  const cp = obj(o.codepage, "profile.codepage", ["name", "escT"]);
  const dots = int(o.dots, "profile.dots", 8, LIMITS.rasterMaxWidth);
  if (dots % 8 !== 0) fail("profile.dots: 8 ga karrali emas");
  return {
    id: str(o.id, "profile.id", 40, 1),
    label: str(o.label, "profile.label", 80),
    width_mm: oneOf(o.width_mm, "profile.width_mm", [58, 80] as const) as PaperWidth,
    dots,
    cols: int(o.cols, "profile.cols", 16, LIMITS.lineChars),
    cut: oneOf(o.cut, "profile.cut", ["none", "partial", "full"] as const),
    qr: oneOf(o.qr, "profile.qr", ["native", "raster", "none"] as const),
    barcode: oneOf(o.barcode, "profile.barcode", ["native", "raster", "none"] as const),
    raster: bool(o.raster, "profile.raster"),
    codepage: {
      name: oneOf(cp.name, "profile.codepage.name", ["cp866", "cp1251"] as const),
      escT: int(cp.escT, "profile.codepage.escT", 0, 255),
    },
    status_query: bool(o.status_query, "profile.status_query"),
    feed_lines: int(o.feed_lines, "profile.feed_lines", 0, 10),
  };
}

export function checkTarget(v: unknown): PrintTarget {
  if (!isPlain(v)) fail("target: obyekt emas");
  const kind = (v as Record<string, unknown>).kind;
  if (kind === "lan") {
    const o = obj(v, "target", ["kind", "host", "port"]);
    if (!isPrivateIPv4(o.host)) fail("target.host: faqat xususiy IPv4 (10/8, 172.16/12, 192.168/16, 169.254/16)");
    if (!isLanPort(o.port)) fail(`target.port: ${LIMITS.lanPortMin}..${LIMITS.lanPortMax} emas`);
    return { kind: "lan", host: o.host as string, port: o.port as number };
  }
  if (kind === "spooler") {
    const o = obj(v, "target", ["kind", "printer"]);
    return { kind: "spooler", printer: printerName(o.printer, "target.printer") };
  }
  if (kind === "system") {
    const o = obj(v, "target", ["kind", "printer"]);
    return o.printer === undefined ? { kind: "system" } : { kind: "system", printer: printerName(o.printer, "target.printer") };
  }
  return fail("target.kind: noma'lum");
}

function run<T>(fn: () => T): Checked<T> {
  try {
    return { ok: true, value: fn() };
  } catch (e) {
    if (e instanceof Invalid) return { ok: false, error: e.message };
    return { ok: false, error: "so'rov yaroqsiz" };
  }
}

export function validateEscPosRequest(raw: unknown): Checked<PrintEscPosRequest> {
  return run(() => {
    const o = obj(raw, "request", ["doc", "profile", "target", "copies", "cut"]);
    const req: PrintEscPosRequest = { doc: checkDoc(o.doc), profile: checkProfile(o.profile), target: checkTarget(o.target) };
    const c = copies(o.copies);
    if (c !== undefined) req.copies = c;
    if (o.cut !== undefined) req.cut = bool(o.cut, "cut");
    return req;
  });
}

function html(v: unknown): string {
  if (typeof v !== "string" || v.length === 0) fail("html: bo'sh yoki satr emas");
  const s = v as string;
  // UTF-8 bayt uzunligi (kirill 2 bayt) — satr uzunligining 3 barobaridan oshmaydi, arzon oldindan tekshiruv.
  if (s.length > LIMITS.htmlBytes || utf8Length(s) > LIMITS.htmlBytes) fail("html: 5 MB dan katta");
  return s;
}

function utf8Length(s: string): number {
  let n = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c < 0x80) n += 1;
    else if (c < 0x800) n += 2;
    else if (c >= 0xd800 && c <= 0xdbff) {
      n += 4;
      i++;
    } else n += 3;
  }
  return n;
}

export function validateHtmlRequest(raw: unknown): Checked<PrintHtmlRequest> {
  return run(() => {
    const o = obj(raw, "request", ["html", "printer", "widthMm", "copies"]);
    const req: PrintHtmlRequest = {
      html: html(o.html),
      widthMm: oneOf(o.widthMm, "widthMm", [58, 80] as const),
    };
    // Bo'sh satr = tizimning standart printeri (eski sozlama `printer: ""` ham shunday edi).
    if (o.printer !== undefined && o.printer !== "") req.printer = printerName(o.printer);
    const c = copies(o.copies);
    if (c !== undefined) req.copies = c;
    return req;
  });
}

/** ESKI `savdoos:print` ({html, deviceName}) — 0.7.x renderer bilan moslik. */
export function validateLegacyPrint(raw: unknown): Checked<{ html: string; deviceName?: string }> {
  return run(() => {
    const o = obj(raw, "request", ["html", "deviceName"]);
    const out: { html: string; deviceName?: string } = { html: html(o.html) };
    if (o.deviceName !== undefined && o.deviceName !== null && o.deviceName !== "") {
      out.deviceName = printerName(o.deviceName, "deviceName");
    }
    return out;
  });
}

/** Printer nomi OS ro'yxatida AYNAN bormi (getPrintersAsync). */
export function printerExists(name: string, list: readonly { name?: unknown }[] | null | undefined): boolean {
  return Array.isArray(list) && list.some((p) => p && p.name === name);
}
