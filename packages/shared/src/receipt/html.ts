// ReceiptDoc → to'liq HTML hujjat (tizim printeri / brauzer chop etish / Manager oldindan ko'rish).
//
// Xavfsizlik: HAR matn `escapeHtml` dan o'tadi; skript yo'q; CSP `default-src 'none'` — hatto biror
// satr qochib o'tsa ham tashqi so'rov yoki skript ishlamaydi. Rasm faqat `data:image/png;base64,...`.
import type { Block, ReceiptDoc } from "./types";
import { COLS, DOTS } from "./types";
import {
  BARCODE_QUIET, DOTS_PER_MM, QR_QUIET, barcodeHeightDots, barcodeModuleDots, qrScale, validBarcode, validQr,
} from "./geometry";

const CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'";
const PNG_URI_RE = /^data:image\/png;base64,[A-Za-z0-9+/=]+$/;
const FONT_STACK = `"Consolas","DejaVu Sans Mono","Courier New",monospace`;
const PRINTABLE_MM = { 58: 48, 80: 72 } as const;
const LINE_HEIGHT = 1.2;
const PAD_MM = 2; // yuqori/pastki ichki hoshiya
const GFX_PAD_MM = 0.5; // rasm/QR/shtrix-kod atrofida
// Sahifa balandligi zaxirasi: brauzer satr balandligini piksel ulushiga yaxlitlaydi — chek oxiri ikkinchi
// sahifaga o'tib, alohida kesilmasin (ortiqcha 3 mm qog'oz — sezilmaydi). Chegaralar Electron `pageSize`
// (validate.ts: 20..3276 mm — Windows DEVMODE chegarasi) bilan AYNI: CSS va drayver sahifasi farq qilmasin.
const PAGE_SLACK_MM = 3;
const PAGE_MIN_MM = 20;
const PAGE_MAX_MM = 3276;

const ESC_MAP: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(s: string): string {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ESC_MAP[c] ?? c);
}

interface Metrics {
  paper: 58 | 80;
  printable: number;
  cols: number;
  dots: number;
  fontMm: number;
  lineMm: number;
}

function metrics(doc: ReceiptDoc): Metrics {
  const paper: 58 | 80 = doc.width_mm === 58 ? 58 : 80;
  const printable = PRINTABLE_MM[paper];
  const c = Number(doc.cols);
  const cols = Number.isInteger(c) && c >= 16 && c <= 96 ? c : COLS[paper];
  // `cols` belgi bosma kenglikka sig'sin: monospace belgi kengligi ≈ 0.6em (Consolas 0.55, DejaVu 0.60).
  const fontMm = printable / cols / 0.62;
  return { paper, printable, cols, dots: DOTS[paper], fontMm, lineMm: fontMm * LINE_HEIGHT };
}

const mm = (v: number) => `${Math.round(v * 1000) / 1000}mm`;

function qrSideMm(size: number, dots: number): number {
  return ((size + 2 * QR_QUIET) * qrScale(size, dots)) / DOTS_PER_MM;
}

function qrSvg(b: Extract<Block, { t: "qr" }>, dots: number): string {
  const total = b.size + 2 * QR_QUIET;
  const side = qrSideMm(b.size, dots);
  let d = "";
  b.matrix.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      if (row[x] === "1") {
        let e = x;
        while (e < row.length && row[e] === "1") e++;
        d += `M${x + QR_QUIET} ${y + QR_QUIET}h${e - x}v1h-${e - x}z`;
        x = e;
      } else x++;
    }
  });
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${total} ${total}" width="${mm(side)}" height="${mm(side)}" ` +
    `shape-rendering="crispEdges" role="img" aria-label="QR"><rect width="${total}" height="${total}" fill="#fff"/>` +
    `<path d="${d}" fill="#000"/></svg>`;
  return svg;
}

function barcodeSvg(b: Extract<Block, { t: "barcode" }>, dots: number): string {
  const m = b.modules;
  const w = barcodeModuleDots(m.length, dots);
  const total = m.length + 2 * BARCODE_QUIET;
  const widthMm = (total * w) / DOTS_PER_MM;
  const heightMm = barcodeHeightDots(dots) / DOTS_PER_MM;
  let d = "";
  let x = 0;
  while (x < m.length) {
    if (m[x] === "1") {
      let e = x;
      while (e < m.length && m[e] === "1") e++;
      d += `M${x + BARCODE_QUIET} 0h${e - x}v1h-${e - x}z`;
      x = e;
    } else x++;
  }
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${total} 1" preserveAspectRatio="none" ` +
    `width="${mm(widthMm)}" height="${mm(heightMm)}" shape-rendering="crispEdges" role="img" aria-label="CODE128">` +
    `<rect width="${total}" height="1" fill="#fff"/><path d="${d}" fill="#000"/></svg>`;
  return svg;
}

function logoOk(b: Extract<Block, { t: "logo" }>): boolean {
  return (
    typeof b.png_data_uri === "string" && PNG_URI_RE.test(b.png_data_uri) &&
    Number.isInteger(b.width) && Number.isInteger(b.height) && b.width > 0 && b.height > 0
  );
}

function feedCount(n: unknown): number {
  const v = Number(n);
  return Number.isInteger(v) ? Math.max(0, Math.min(10, v)) : 0;
}

/**
 * Sahifa rejimi: "exact" (standart) — `@page` chek o'lchamida (Electron ham AYNAN shu `pageSize` bilan
 * chop etadi). "driver" — `@page` da o'lcham YO'Q: sahifa = drayver qog'ozi, chek 1:1 tepadan chiqadi.
 * Drayver qog'oziga boshqa o'lchamli CSS sahifa berilsa Chromium uni kichraytirib, o'rtaga qo'yardi.
 */
export type HtmlPageMode = "exact" | "driver";

export function renderHtml(doc: ReceiptDoc, opts?: { title?: string; pageMode?: HtmlPageMode }): string {
  const M = metrics(doc);
  const out: string[] = [];
  const blocks = Array.isArray(doc.blocks) ? doc.blocks : [];
  for (const b of blocks) {
    switch (b?.t) {
      case "line": {
        const cls = "l" + (b.bold ? " b" : "") + (b.size === 2 ? " s2" : "");
        out.push(`<div class="${cls}">${escapeHtml(b.text)}</div>`);
        break;
      }
      case "rule":
        out.push(`<div class="l">${(b.char === "=" ? "=" : "-").repeat(M.cols)}</div>`);
        break;
      case "feed":
        for (let i = 0; i < feedCount(b.lines); i++) out.push(`<div class="l"></div>`);
        break;
      case "logo":
        if (logoOk(b)) {
          out.push(
            `<div class="g"><img alt="" src="${escapeHtml(b.png_data_uri as string)}" ` +
              `style="width:${mm(b.width / DOTS_PER_MM)};height:${mm(b.height / DOTS_PER_MM)}"></div>`,
          );
        }
        break;
      case "qr":
        if (validQr(b)) out.push(`<div class="g">${qrSvg(b, M.dots)}</div>`);
        break;
      case "barcode":
        if (validBarcode(b)) out.push(`<div class="g">${barcodeSvg(b, M.dots)}</div>`);
        break;
      default:
        break; // "cut" va noma'lum bloklar HTML'da ko'rinmaydi
    }
  }
  // `size: 80mm auto` YAROQSIZ CSS (uzunlik + auto) — brauzer butun qoidani tashlab, printer standart
  // qog'ozida (A4/Letter) sahifalarga bo'lardi. Ikkala qiymat ham uzunlik: chek — bitta uzun sahifa.
  // "driver" rejimida o'lcham berilmaydi: Electron `pageSize` yubormaydi, CSS ham drayver qog'ozini olsin.
  const page = pageSizeMm(doc);
  const pageRule = opts?.pageMode === "driver"
    ? "@page { margin: 0 }"
    : `@page { size: ${page.width_mm}mm ${page.height_mm}mm; margin: 0 }`;
  const css =
    pageRule +
    `*{box-sizing:border-box}html,body{margin:0;padding:0;background:#fff;color:#000}` +
    `body{width:${M.paper}mm}` +
    `.r{width:${M.printable}mm;margin:0 auto;padding:${PAD_MM}mm 0;font-family:${FONT_STACK};` +
    `font-size:${mm(M.fontMm)};line-height:${LINE_HEIGHT}}` +
    `.l{white-space:pre;overflow:hidden;min-height:${LINE_HEIGHT}em}` +
    `.b{font-weight:700}.s2{font-size:${mm(M.fontMm * 2)}}` +
    `.g{display:flex;justify-content:center;padding:${GFX_PAD_MM}mm 0}.g img,.g svg{display:block}` +
    `.g img{image-rendering:pixelated}`;
  return (
    `<!doctype html><html><head><meta charset="utf-8">` +
    `<meta http-equiv="Content-Security-Policy" content="${CSP}">` +
    `<title>${escapeHtml(opts?.title ?? "Receipt")}</title><style>${css}</style></head>` +
    `<body><div class="r">${out.join("")}</div></body></html>`
  );
}

/**
 * Chop etish sahifasi (mm): kenglik — qog'oz, balandlik — butun chek + zaxira (butun mm). HTML'dagi `@page`
 * shu; Electron `webContents.print({ pageSize })` ham AYNAN shu qiymatni olsin — ikkisi farq qilsa Chromium
 * sahifani qayta masshtablashi yoki bo'lishi mumkin.
 */
export function pageSizeMm(doc: ReceiptDoc): { width_mm: 58 | 80; height_mm: number } {
  const M = metrics(doc);
  const h = Math.ceil(docHeightMm(doc)) + PAGE_SLACK_MM;
  return { width_mm: M.paper, height_mm: Math.min(PAGE_MAX_MM, Math.max(PAGE_MIN_MM, h)) };
}

/** Hujjat balandligi (mm) — Manager oldindan ko'rish iframe balandligi uchun. */
export function docHeightMm(doc: ReceiptDoc): number {
  const M = metrics(doc);
  let h = 2 * PAD_MM;
  const blocks = Array.isArray(doc.blocks) ? doc.blocks : [];
  for (const b of blocks) {
    switch (b?.t) {
      case "line":
        h += b.size === 2 ? 2 * M.lineMm : M.lineMm;
        break;
      case "rule":
        h += M.lineMm;
        break;
      case "feed":
        h += feedCount(b.lines) * M.lineMm;
        break;
      case "logo":
        if (logoOk(b)) h += b.height / DOTS_PER_MM + 2 * GFX_PAD_MM;
        break;
      case "qr":
        if (validQr(b)) h += qrSideMm(b.size, M.dots) + 2 * GFX_PAD_MM;
        break;
      case "barcode":
        if (validBarcode(b)) h += barcodeHeightDots(M.dots) / DOTS_PER_MM + 2 * GFX_PAD_MM;
        break;
      default:
        break;
    }
  }
  return Math.round(h * 100) / 100;
}
