// ReceiptDoc → ESC/POS baytlari (sof funksiya) va shu buyruqlarning minimal tahlilchisi.
//
// ⚠️  OQ RO'YXAT: faqat quyidagi buyruqlar chiqariladi, boshqasi HECH QACHON:
//   ESC @ (init) · ESC t n (kod sahifa) · ESC E n (qalin) · GS ! n (0x00/0x11) · ESC a n (faqat rasm/QR/
//   shtrix-kod atrofida) · LF · ESC d n (surish) · GS v 0 (raster) · GS ( k (QR: model 2, o'lcham, EC M,
//   saqlash, chop) · GS h / GS w / GS H / GS k 73 (CODE128 "{B") · GS V 66 0 / GS V 65 0 (kesish).
//   `ESC p` (pul qutisi) va boshqa hech narsa yo'q. Matndan 0x20 dan kichik bayt chiqmaydi (codepage.ts).
import type { Block, PrinterProfile, ReceiptDoc } from "./types";
import { encodeText, decodeText, type CodepageName } from "./codepage";
import { base64Decode } from "./b64";
import {
  BARCODE_QUIET, QR_QUIET, barcodeHeightDots, barcodeModuleDots, qrScale, validBarcode, validQr,
} from "./geometry";
import { cleanLine, wrapText } from "./text";

const ESC = 0x1b;
const GS = 0x1d;
const LF = 0x0a;
const RASTER_BAND = 256; // bitta GS v 0 dagi eng ko'p qator (arzon printer buferlari uchun)
const QR_EC_M = 0x31;
const QR_MAX_BYTES = 700;
const NO_CUT_FEED = 4;

export interface EscPosResult {
  bytes: Uint8Array;
  /** Kodlovchi ogohlantirishlari (layout'niki `doc.warnings` da). */
  warnings: string[];
}

class Out {
  a: number[] = [];
  push(...bs: number[]) {
    for (const b of bs) this.a.push(b & 0xff);
  }
  append(bs: ArrayLike<number>) {
    for (let i = 0; i < bs.length; i++) this.a.push(bs[i] & 0xff);
  }
}

function utf8(s: string): number[] {
  const out: number[] = [];
  for (const ch of s) {
    const cp = ch.codePointAt(0) ?? 0x3f;
    if (cp < 0x80) out.push(cp);
    else if (cp < 0x800) out.push(0xc0 | (cp >> 6), 0x80 | (cp & 63));
    else if (cp < 0x10000) out.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
    else out.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 63), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
  }
  return out;
}

/** Qadoqlangan 1-bit rasm (qator bo'yicha, MSB birinchi, 1 = qora) → GS v 0 bo'laklari. */
function pushRaster(out: Out, bits: Uint8Array, bytesPerRow: number, height: number) {
  for (let y0 = 0; y0 < height; y0 += RASTER_BAND) {
    const h = Math.min(RASTER_BAND, height - y0);
    out.push(GS, 0x76, 0x30, 0x00, bytesPerRow & 0xff, bytesPerRow >> 8, h & 0xff, h >> 8);
    out.append(bits.subarray(y0 * bytesPerRow, (y0 + h) * bytesPerRow));
  }
}

class Canvas {
  readonly bpr: number;
  readonly bits: Uint8Array;
  constructor(readonly width: number, readonly height: number) {
    this.bpr = width >> 3;
    this.bits = new Uint8Array(this.bpr * height);
  }
  fill(x: number, y: number, w: number, h: number) {
    for (let yy = y; yy < y + h; yy++) {
      if (yy < 0 || yy >= this.height) continue;
      const row = yy * this.bpr;
      for (let xx = x; xx < x + w; xx++) {
        if (xx < 0 || xx >= this.width) continue;
        this.bits[row + (xx >> 3)] |= 0x80 >> (xx & 7);
      }
    }
  }
}

function qrRaster(b: Extract<Block, { t: "qr" }>, dots: number): Canvas {
  const scale = qrScale(b.size, dots);
  const px = (b.size + 2 * QR_QUIET) * scale;
  const c = new Canvas(dots, px);
  const off = Math.floor((dots - px) / 2);
  b.matrix.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      if (row[x] === "1") c.fill(off + (x + QR_QUIET) * scale, (y + QR_QUIET) * scale, scale, scale);
    }
  });
  return c;
}

function barcodeRaster(modules: string, dots: number): Canvas {
  const w = barcodeModuleDots(modules.length, dots);
  const h = barcodeHeightDots(dots);
  const px = (modules.length + 2 * BARCODE_QUIET) * w;
  const c = new Canvas(dots, h);
  const off = Math.floor((dots - px) / 2);
  for (let i = 0; i < modules.length; i++) {
    if (modules[i] === "1") c.fill(off + (i + BARCODE_QUIET) * w, 0, w, h);
  }
  return c;
}

function clampInt(v: unknown, lo: number, hi: number, def: number): number {
  const n = Number(v);
  return Number.isInteger(n) ? Math.max(lo, Math.min(hi, n)) : def;
}

export function encodeEscPos(
  doc: ReceiptDoc,
  profile: PrinterProfile,
  opts?: { copies?: number; cut?: boolean },
): EscPosResult {
  const warnings: string[] = [];
  const warn = (w: string) => {
    if (!warnings.includes(w)) warnings.push(w);
  };
  const cp: CodepageName = profile.codepage?.name === "cp1251" ? "cp1251" : "cp866";
  const escT = clampInt(profile.codepage?.escT, 0, 255, 17);
  const dots = clampInt(profile.dots, 8, 576, 576) & ~7;
  const pcols = clampInt(profile.cols, 16, 96, 48);
  const dcols = clampInt(doc.cols, 16, 96, pcols);
  if (dcols > pcols) warn("width_mismatch");
  const cols = Math.min(dcols, pcols);
  const feedLines = clampInt(profile.feed_lines, 0, 10, 4);
  const copies = clampInt(opts?.copies ?? 1, 1, 3, 1);
  const blocks = Array.isArray(doc.blocks) ? doc.blocks : [];

  const out = new Out();

  const textBytes = (s: string): number[] => {
    const enc = encodeText(String(s ?? ""), cp);
    for (const l of enc.lossy) warn(`lossy:${l}`);
    return enc.bytes;
  };
  // Printerning o'zi qatorni o'rab yubormasin: sig'maganini baytlar bo'yicha bo'lamiz (layout'da bo'lmaydi).
  const textLine = (s: string, max: number) => {
    const bytes = textBytes(s);
    if (bytes.length <= max) {
      out.append(bytes);
      out.push(LF);
      return;
    }
    warn("line_wrapped");
    for (let i = 0; i < bytes.length; i += max) {
      out.append(bytes.slice(i, i + max));
      out.push(LF);
    }
  };
  const feed = (n: number) => {
    if (n > 0) out.push(ESC, 0x64, n);
  };
  const textFallback = (payload: string) => {
    for (const l of wrapText(cleanLine(payload), cols)) textLine(l, cols);
  };
  const cut = () => {
    feed(feedLines);
    if (profile.cut === "partial") out.push(GS, 0x56, 66, 0);
    else if (profile.cut === "full") out.push(GS, 0x56, 65, 0);
    else {
      warn("cut_unsupported");
      feed(NO_CUT_FEED);
    }
  };

  for (let copy = 0; copy < copies; copy++) {
    out.push(ESC, 0x40); // ESC @
    out.push(ESC, 0x74, escT); // ESC t n
    let cutDone = false;
    for (const b of blocks) {
      switch (b?.t) {
        case "line": {
          const size2 = b.size === 2;
          if (b.bold) out.push(ESC, 0x45, 1);
          if (size2) out.push(GS, 0x21, 0x11);
          textLine(b.text, size2 ? Math.floor(cols / 2) : cols);
          if (size2) out.push(GS, 0x21, 0x00);
          if (b.bold) out.push(ESC, 0x45, 0);
          break;
        }
        case "rule":
          textLine((b.char === "=" ? "=" : "-").repeat(cols), cols);
          break;
        case "feed":
          feed(clampInt(b.lines, 0, 10, 0));
          break;
        case "logo": {
          if (!profile.raster) {
            warn("logo_unsupported");
            break;
          }
          const w = Number(b.width);
          const h = Number(b.height);
          const data = base64Decode(b.raster_b64);
          if (!Number.isInteger(w) || !Number.isInteger(h) || w <= 0 || w % 8 !== 0 || h <= 0 || h > 4000 ||
              !data || data.length !== (w / 8) * h) {
            warn("logo_invalid");
            break;
          }
          if (w > dots) {
            warn("logo_too_wide");
            break;
          }
          // O'rtaga: bayt chegarasida chapdan bo'sh joy (ESC a ga suyanmaymiz — ba'zi printerlar e'tiborsiz qoldiradi).
          const bpr = dots >> 3;
          const offBytes = Math.floor((bpr - w / 8) / 2);
          const bits = new Uint8Array(bpr * h);
          for (let y = 0; y < h; y++) bits.set(data.subarray(y * (w / 8), (y + 1) * (w / 8)), y * bpr + offBytes);
          pushRaster(out, bits, bpr, h);
          break;
        }
        case "qr": {
          if (!validQr(b) || typeof b.payload !== "string" || !b.payload) {
            warn("qr_invalid");
            break;
          }
          const data = utf8(b.payload);
          if (profile.qr === "native" && data.length <= QR_MAX_BYTES) {
            const n = Math.max(1, Math.min(16, qrScale(b.size, dots)));
            const len = data.length + 3;
            out.push(ESC, 0x61, 1);
            out.push(GS, 0x28, 0x6b, 4, 0, 0x31, 0x41, 0x32, 0x00); // model 2
            out.push(GS, 0x28, 0x6b, 3, 0, 0x31, 0x43, n); // modul o'lchami
            out.push(GS, 0x28, 0x6b, 3, 0, 0x31, 0x45, QR_EC_M); // xatoni tuzatish M
            out.push(GS, 0x28, 0x6b, len & 0xff, len >> 8, 0x31, 0x50, 0x30);
            out.append(data);
            out.push(GS, 0x28, 0x6b, 3, 0, 0x31, 0x51, 0x30); // chop etish
            out.push(ESC, 0x61, 0);
          } else if (profile.qr !== "none" && profile.raster) {
            const c = qrRaster(b, dots);
            pushRaster(out, c.bits, c.bpr, c.height);
          } else {
            warn("qr_unsupported");
            textFallback(b.payload);
          }
          break;
        }
        case "barcode": {
          if (!validBarcode(b)) {
            warn("barcode_invalid");
            break;
          }
          if (b.modules.length + 2 * BARCODE_QUIET > dots) {
            warn("barcode_too_wide"); // kesilgan shtrix-kod o'qilmaydi; payload matni layout'da bor
            break;
          }
          const payload = String(b.payload ?? "");
          const ascii = /^[\x20-\x7e]{1,64}$/.test(payload);
          // Printer B to'plamida kodlaydi: (belgilar + start + checksum + stop) modul, har biri 2 nuqta.
          const nativeModules = (payload.length + 3) * 11 + 2;
          const nativeFits = (nativeModules + 2 * BARCODE_QUIET) * 2 <= dots;
          if (profile.barcode === "native" && ascii && nativeFits) {
            const data = [0x7b, 0x42]; // "{B"
            for (const ch of payload) {
              const c = ch.charCodeAt(0);
              if (c === 0x7b) data.push(0x7b); // "{" → "{{"
              data.push(c);
            }
            out.push(ESC, 0x61, 1);
            out.push(GS, 0x68, barcodeHeightDots(dots)); // balandlik
            out.push(GS, 0x77, 2); // modul kengligi
            out.push(GS, 0x48, 0); // HRI yo'q — matnni layout chiqaradi
            out.push(GS, 0x6b, 73, data.length);
            out.append(data);
            out.push(ESC, 0x61, 0);
          } else if (profile.barcode !== "none" && profile.raster) {
            const c = barcodeRaster(b.modules, dots);
            pushRaster(out, c.bits, c.bpr, c.height);
          } else {
            // Payload matni layout'da shtrix-kod ostida allaqachon bor — takrorlamaymiz.
            warn("barcode_unsupported");
          }
          break;
        }
        case "cut":
          if (opts?.cut === false) feed(feedLines);
          else cut();
          cutDone = true;
          break;
        default:
          break;
      }
    }
    if (!cutDone) {
      if (opts?.cut === true) cut();
      else feed(feedLines);
    }
  }
  return { bytes: Uint8Array.from(out.a), warnings };
}

// ---------------------------------------------------------------------------------------------------
// Tahlilchi: FAQAT oq ro'yxatdagi buyruqlarni taniydi; boshqa har qanday boshqaruv bayti → UNKNOWN.
// Sinovlar u bilan "begona buyruq yo'q" ni isbotlaydi; raster/QR/shtrix-kod ma'lumoti uzunligi
// bo'yicha to'g'ri o'tkazib yuboriladi (ichidagi 0x1B baytlari buyruq deb o'qilmaydi).

export interface EscPosCommand {
  cmd: string;
  [k: string]: unknown;
}

export const ESCPOS_WHITELIST: readonly string[] = [
  "ESC @", "ESC t", "ESC E", "GS !", "ESC a", "LF", "ESC d", "GS v 0", "GS ( k", "GS h", "GS w", "GS H", "GS k",
  "GS V", "TEXT",
];

export function parseEscPos(bytes: ArrayLike<number>, opts?: { codepage?: CodepageName }): EscPosCommand[] {
  const cp: CodepageName = opts?.codepage ?? "cp866";
  const out: EscPosCommand[] = [];
  const n = bytes.length;
  let i = 0;
  const need = (k: number) => {
    if (i + k > n) {
      out.push({ cmd: "TRUNCATED", at: i });
      i = n;
      return false;
    }
    return true;
  };
  while (i < n) {
    const b = bytes[i];
    if (b === LF) {
      out.push({ cmd: "LF" });
      i++;
    } else if (b >= 0x20 && b !== 0x7f) {
      const start = i;
      while (i < n && bytes[i] >= 0x20 && bytes[i] !== 0x7f) i++;
      const run = Array.prototype.slice.call(bytes, start, i) as number[];
      out.push({ cmd: "TEXT", text: decodeText(run, cp), length: run.length });
    } else if (b === ESC) {
      if (!need(2)) break;
      const c = bytes[i + 1];
      if (c === 0x40) {
        out.push({ cmd: "ESC @" });
        i += 2;
      } else if (c === 0x74 || c === 0x45 || c === 0x61 || c === 0x64) {
        if (!need(3)) break;
        const name = c === 0x74 ? "ESC t" : c === 0x45 ? "ESC E" : c === 0x61 ? "ESC a" : "ESC d";
        out.push({ cmd: name, n: bytes[i + 2] });
        i += 3;
      } else {
        out.push({ cmd: "UNKNOWN", at: i, byte: b, next: c });
        i += 1;
      }
    } else if (b === GS) {
      if (!need(2)) break;
      const c = bytes[i + 1];
      if (c === 0x21 || c === 0x68 || c === 0x77 || c === 0x48) {
        if (!need(3)) break;
        const name = c === 0x21 ? "GS !" : c === 0x68 ? "GS h" : c === 0x77 ? "GS w" : "GS H";
        out.push({ cmd: name, n: bytes[i + 2] });
        i += 3;
      } else if (c === 0x76 && bytes[i + 2] === 0x30) {
        if (!need(8)) break;
        const m = bytes[i + 3];
        const x = bytes[i + 4] + bytes[i + 5] * 256;
        const y = bytes[i + 6] + bytes[i + 7] * 256;
        const len = x * y;
        if (!need(8 + len)) break;
        out.push({ cmd: "GS v 0", m, width: x * 8, height: y, data: len });
        i += 8 + len;
      } else if (c === 0x28 && bytes[i + 2] === 0x6b) {
        if (!need(5)) break;
        const len = bytes[i + 3] + bytes[i + 4] * 256;
        if (len < 2 || !need(5 + len)) {
          if (len < 2) {
            out.push({ cmd: "UNKNOWN", at: i, byte: b, next: c });
            i += 1;
          }
          continue;
        }
        const cn = bytes[i + 5];
        const fn = bytes[i + 6];
        const params = Array.prototype.slice.call(bytes, i + 7, i + 5 + len) as number[];
        const rec: EscPosCommand = { cmd: "GS ( k", cn, fn };
        if (fn === 0x50) {
          rec.data = String.fromCharCode(...params.slice(1));
          rec.m = params[0];
        } else rec.params = params;
        out.push(rec);
        i += 5 + len;
      } else if (c === 0x6b && bytes[i + 2] === 73) {
        if (!need(4)) break;
        const len = bytes[i + 3];
        if (!need(4 + len)) break;
        const data = Array.prototype.slice.call(bytes, i + 4, i + 4 + len) as number[];
        out.push({ cmd: "GS k", m: 73, data: String.fromCharCode(...data) });
        i += 4 + len;
      } else if (c === 0x56 && (bytes[i + 2] === 65 || bytes[i + 2] === 66)) {
        if (!need(4)) break;
        out.push({ cmd: "GS V", m: bytes[i + 2], n: bytes[i + 3] });
        i += 4;
      } else {
        out.push({ cmd: "UNKNOWN", at: i, byte: b, next: c });
        i += 1;
      }
    } else {
      out.push({ cmd: "UNKNOWN", at: i, byte: b });
      i++;
    }
  }
  return out;
}

const hex2 = (v: unknown) => "0x" + Number(v).toString(16).padStart(2, "0");

/** Inson o'qiydigan buyruqlar ro'yxati (golden va nosozlikni tekshirish uchun). */
export function describeEscPos(cmds: readonly EscPosCommand[]): string[] {
  return cmds.map((c) => {
    switch (c.cmd) {
      case "TEXT":
        return `TEXT ${JSON.stringify(c.text)}`;
      case "LF":
      case "ESC @":
        return c.cmd;
      case "GS !":
        return `GS ! ${hex2(c.n)}`;
      case "GS v 0":
        return `GS v 0 m=${c.m} ${c.width}x${c.height} (${c.data} bytes)`;
      case "GS ( k": {
        const fn = Number(c.fn);
        const p = (c.params as number[] | undefined) ?? [];
        if (fn === 0x41) return `GS ( k QR model=${p[0] === 0x32 ? 2 : p[0]}`;
        if (fn === 0x43) return `GS ( k QR module=${p[0]}`;
        if (fn === 0x45) return `GS ( k QR ec=${p[0] === 0x31 ? "M" : p[0]}`;
        if (fn === 0x50) return `GS ( k QR store ${JSON.stringify(c.data)}`;
        if (fn === 0x51) return `GS ( k QR print`;
        return `GS ( k cn=${c.cn} fn=${fn} params=${JSON.stringify(p)}`;
      }
      case "GS k":
        return `GS k ${c.m} ${JSON.stringify(c.data)}`;
      case "GS V":
        return `GS V ${c.m} ${c.n}${c.m === 66 ? " (partial cut)" : c.m === 65 ? " (full cut)" : ""}`;
      case "UNKNOWN":
      case "TRUNCATED":
        return `${c.cmd} at=${c.at} byte=${hex2(c.byte ?? 0)}`;
      default:
        return `${c.cmd} ${c.n ?? ""}`.trim();
    }
  });
}
