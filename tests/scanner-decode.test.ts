// @vitest-environment node
//
// HAQIQIY DEKODLASH TESTI: piksel -> ZXing -> barkod matni.
//
// Nega shunday. Repo'da barkod RASMINI yasaydigan bog'liqlik yo'q (vendored
// ZXing'ning `MultiFormatWriter` i faqat QR chizadi) va jsdom'da canvas yo'q.
// Shu bois bu yerda barkod MODULLARI (qora/oq chiziqlar) to'g'ridan-to'g'ri
// luminance buferiga chiziladi va AYNI vendored `zxing-0.19.1.min.js` — ya'ni
// brauzerga jo'natiladigan faylning O'ZI — `node:vm` ichida yurgizilib, kadr
// undan o'tkaziladi. `node:vm` naqshi repo'da allaqachon bor
// (`scripts/pwa_sw_selftest.mjs`: "Dart cannot execute JavaScript").
//
// ⚠️  BU HAQIQIY QURILMA ISBOTI EMAS. Bu yerda kamera, Safari, linza, fokus va
//     yorug'lik YO'Q — faqat dekoder yadrosi sinaladi. iPhone 16 Pro natijasi
//     foydalanuvchi tasdig'i bilan keladi.
import { describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as vm from 'vm';

// ── Vendored ZXing'ni yuklash (brauzerga ketadigan AYNI fayl) ────────────────
function loadZXing(): any {
  const file = path.resolve(
    __dirname,
    '../apps/mobile/web/vendor/zxing/zxing-0.19.1.min.js',
  );
  const code = fs.readFileSync(file, 'utf-8');
  const sandbox: any = { console };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  new vm.Script(code, { filename: 'zxing-0.19.1.min.js' }).runInContext(sandbox);
  if (!sandbox.ZXing?.MultiFormatReader) throw new Error('ZXing global yuklanmadi');
  return sandbox.ZXing;
}

const ZX = loadZXing();

// ── Barkod modullarini chizish ───────────────────────────────────────────────
// EAN/UPC kodlash jadvallari (standart).
const L = ['0001101', '0011001', '0010011', '0111101', '0100011',
           '0110001', '0101111', '0111011', '0110111', '0001011'];
const G = ['0100111', '0110011', '0011011', '0100001', '0011101',
           '0111001', '0000101', '0010001', '0001001', '0010111'];
const R = ['1110010', '1100110', '1101100', '1000010', '1011100',
           '1001110', '1010000', '1000100', '1001000', '1110100'];
// Birinchi raqam 2–7-raqamlarning L/G naqshini belgilaydi.
const PARITY = ['LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG',
                'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL'];

function ean13Bits(code: string): string {
  if (!/^\d{13}$/.test(code)) throw new Error('EAN-13 uchun 13 raqam kerak');
  const d = code.split('').map(Number);
  const parity = PARITY[d[0]];
  let bits = '101';
  for (let i = 1; i <= 6; i++) bits += (parity[i - 1] === 'L' ? L : G)[d[i]];
  bits += '01010';
  for (let i = 7; i <= 12; i++) bits += R[d[i]];
  return bits + '101';
}

function ean8Bits(code: string): string {
  if (!/^\d{8}$/.test(code)) throw new Error('EAN-8 uchun 8 raqam kerak');
  const d = code.split('').map(Number);
  let bits = '101';
  for (let i = 0; i < 4; i++) bits += L[d[i]];
  bits += '01010';
  for (let i = 4; i < 8; i++) bits += R[d[i]];
  return bits + '101';
}

/// Modul satridan kulrang kadr yasaydi: har modul `scale` piksel, atrofida
/// oq "tinch zona" (quiet zone) — usiz ZXing boshlanishni topa olmaydi.
function frameFromBits(bits: string, scale = 4, height = 40, quiet = 12) {
  const width = (bits.length + quiet * 2) * scale;
  const h = height;
  const lum = new Uint8ClampedArray(width * h);
  lum.fill(255);
  for (let i = 0; i < bits.length; i++) {
    if (bits[i] !== '1') continue;
    const x0 = (quiet + i) * scale;
    for (let x = x0; x < x0 + scale; x++) {
      for (let y = 0; y < h; y++) lum[y * width + x] = 0;
    }
  }
  return { lum, width, height: h };
}

function decode(bits: string, formats: number[]): { text: string; format: string } {
  const { lum, width, height } = frameFromBits(bits);
  const src = new ZX.RGBLuminanceSource(lum, width, height);
  const bitmap = new ZX.BinaryBitmap(new ZX.HybridBinarizer(src));
  const reader = new ZX.MultiFormatReader();
  const hints = new Map();
  hints.set(ZX.DecodeHintType.POSSIBLE_FORMATS, formats);
  hints.set(ZX.DecodeHintType.TRY_HARDER, true);
  reader.setHints(hints);
  const res = reader.decode(bitmap);
  return { text: res.getText(), format: String(res.getBarcodeFormat()) };
}

// `web/scanner.js` dagi ro'yxat bilan AYNI bo'lishi kerak.
const RETAIL = [
  ZX.BarcodeFormat.EAN_13, ZX.BarcodeFormat.EAN_8, ZX.BarcodeFormat.UPC_A,
  ZX.BarcodeFormat.UPC_E, ZX.BarcodeFormat.CODE_128, ZX.BarcodeFormat.CODE_39,
  ZX.BarcodeFormat.ITF,
];

describe('dekoder — piksel kadridan barkod matnigacha', () => {
  it('vendored ZXing yuklanadi va kerakli eksportlarni beradi', () => {
    for (const name of ['MultiFormatReader', 'HybridBinarizer', 'BinaryBitmap',
                        'RGBLuminanceSource', 'DecodeHintType', 'BarcodeFormat']) {
      expect(ZX[name], name).toBeTruthy();
    }
  });

  it('EAN-13', () => {
    const got = decode(ean13Bits('4780000000038'), RETAIL);
    expect(got.text).toBe('4780000000038');
  });

  it("nazorat raqami NOTO'G'RI bo'lsa dekoder RAD etadi", () => {
    // `4780000000035` — oxirgi raqami noto'g'ri (to'g'risi 8).
    // Dekoder uni jimgina qabul qilmasligi SHART, aks holda noto'g'ri kod
    // serverga ketardi.
    expect(() => decode(ean13Bits('4780000000035'), RETAIL)).toThrow();
  });

  it('EAN-8', () => {
    const got = decode(ean8Bits('96385074'), RETAIL);
    expect(got.text).toBe('96385074');
  });

  it('UPC-A (yetakchi nolli EAN-13 sifatida chiziladi)', () => {
    // UPC-A = 12 raqam; simvol jihatidan bu `0` + 12 raqamli EAN-13.
    const got = decode(ean13Bits('0012345678905'), RETAIL);
    // ZXing UPC_A sifatida 12 raqam, EAN_13 sifatida 13 raqam qaytarishi mumkin.
    expect(['012345678905', '0012345678905']).toContain(got.text);
  });

  // ── FAYZAN TAROZI ETIKETKALARI — regressiya qo'riqchisi ────────────────────
  // Bular oddiy EAN-13; dekoder ularni AYNAN o'qishi shart. Tarozi qoidasi
  // (27 + PLU(5) + gramm(5)) SERVERDA qo'llanadi — bu yerda tegilmaydi.
  const FAYZAN = ['2700345032787', '2700565020205', '2700537004264', '2700349000560'];
  for (const code of FAYZAN) {
    it(`Fayzan tarozi etiketkasi ${code}`, () => {
      const got = decode(ean13Bits(code), RETAIL);
      expect(got.text).toBe(code);
    });
  }

  it('format ro\'yxati cheklanganda ham tarozi etiketkasi o\'qiladi', () => {
    const got = decode(ean13Bits('2700537004264'), [ZX.BarcodeFormat.EAN_13]);
    expect(got.text).toBe('2700537004264');
  });

  it('kadrda barkod bo\'lmasa NotFound beradi (jim muvaffaqiyat EMAS)', () => {
    const blank = '0'.repeat(95);
    expect(() => decode(blank, RETAIL)).toThrow();
  });
});

// ── Do'kon sharoiti: kod atrofida QORONG'I narsa bor ─────────────────────────
// Yuqoridagi `frameFromBits` butun kadrni OQ qiladi, ya'ni skanerlash qatori
// har doim shtrix-kodning O'ZIDAN boshlanadi. Javondagi haqiqiy kadr bunday
// EMAS: kodgacha mahsulot, soya, qo'shni quti — qorong'i maydon bo'ladi.
// Aynan shu farq 2026-09-26 da iPhone 16 Pro sinovini yiqitgan.
function frameWithSurround(bits: string, scale = 4, height = 60, quiet = 10, surround = 200) {
  const inner = (bits.length + quiet * 2) * scale;
  const width = inner + surround * 2;
  const lum = new Uint8ClampedArray(width * height);
  lum.fill(96);                                   // atrof — o'rtacha qorong'i
  for (let y = 0; y < height; y++) {
    for (let x = surround; x < surround + inner; x++) lum[y * width + x] = 255;  // oq etiketka
  }
  for (let i = 0; i < bits.length; i++) {
    if (bits[i] !== '1') continue;
    const x0 = surround + (quiet + i) * scale;
    for (let x = x0; x < x0 + scale; x++) {
      for (let y = 0; y < height; y++) lum[y * width + x] = 16;
    }
  }
  return { lum, width, height };
}

function decodeFrame(Z: any, f: { lum: Uint8ClampedArray; width: number; height: number }): string | null {
  const bitmap = new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.RGBLuminanceSource(f.lum, f.width, f.height)));
  const reader = new Z.MultiFormatReader();
  const hints = new Map();
  hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8, Z.BarcodeFormat.UPC_A]);
  reader.setHints(hints);
  try { return reader.decode(bitmap).getText(); } catch { return null; }
}

/** Vendored faylni berilgan matn bilan yuklaydi (tuzatilgan yoki tuzatilmagan). */
function loadZXingFrom(code: string): any {
  const sandbox: any = { console };
  sandbox.globalThis = sandbox; sandbox.self = sandbox;
  vm.createContext(sandbox);
  new vm.Script(code, { filename: 'zxing-variant.js' }).runInContext(sandbox);
  return sandbox.ZXing;
}

const VENDOR_FILE = path.resolve(__dirname, '../apps/mobile/web/vendor/zxing/zxing-0.19.1.min.js');

describe("guard-pattern tuzatishi — kod atrofida qorong'i maydon", () => {
  const CODE = '4700024930227';   // iPhone 16 Pro sinovida o'qilmagan AYNAN shu kod

  it("tuzatilgan vendored build qorong'i atrofli kadrni o'qiydi", () => {
    expect(decodeFrame(ZX, frameWithSurround(ean13Bits(CODE)))).toBe(CODE);
  });

  it("atrof oq bo'lsa ham o'qiydi (regressiya yo'q)", () => {
    expect(decodeFrame(ZX, frameWithSurround(ean13Bits(CODE), 4, 60, 10, 200))).toBe(CODE);
    expect(decode(ean13Bits(CODE), RETAIL).text).toBe(CODE);
  });

  it("TUZATILMAGAN build AYNAN shu kadrda yiqiladi (nuqson isboti)", async () => {
    const { PATCHES } = await import('../scripts/zxing_patch.mjs');
    let buzuq = fs.readFileSync(VENDOR_FILE, 'utf-8');
    for (const p of PATCHES as Array<{ eski: string; yangi: string }>) {
      expect(buzuq).toContain(p.yangi);          // fayl tuzatilgan holatda turibdi
      buzuq = buzuq.replace(p.yangi, p.eski);    // ... va uni ORQAGA qaytaramiz
    }
    const eski = loadZXingFrom(buzuq);
    expect(decodeFrame(eski, frameWithSurround(ean13Bits(CODE)))).toBeNull();
    // Eski build faqat kod qatorning boshida turganda o'qiydi:
    expect(decodeFrame(eski, frameWithSurround(ean13Bits(CODE), 4, 60, 10, 0))).toBe(CODE);
  });

  it('vendored faylda buzuq idioma QOLMAGAN (qayta vendor qilinsa ushlaydi)', async () => {
    const { holat } = await import('../scripts/zxing_patch.mjs');
    const h = (holat as (m: string) => Array<{ nima: string; tuzatilgan: boolean; buzuq: boolean }>)(
      fs.readFileSync(VENDOR_FILE, 'utf-8'));
    expect(h.length).toBe(2);
    for (const x of h) {
      expect(x.tuzatilgan, `${x.nima} tuzatilmagan`).toBe(true);
      expect(x.buzuq, `${x.nima} da buzuq idioma bor`).toBe(false);
    }
  });
});

// ── Skaner AYNAN qanday dekodlasa, shunday ────────────────────────────────────
// Quyidagilar `web/scanner.js` bilan bir xil sozlamani ishlatadi: RGB luminance
// buferi, HybridBinarizer, format ro'yxati bilan `MultiFormatReader` va
// `decodeWithState`. Fon TEKSTURALI: oq-fonli kadr haqiqiy javonni ifodalamaydi
// va aynan shu sabab 2026-09-26 da nuqson qurilmagacha yetib bordi.
const FAST_FORMATS = [ZX.BarcodeFormat.EAN_13, ZX.BarcodeFormat.EAN_8, ZX.BarcodeFormat.UPC_A, ZX.BarcodeFormat.UPC_E];

function readerWith(formats: number[]): any {
  const hints = new Map();
  hints.set(ZX.DecodeHintType.POSSIBLE_FORMATS, formats);
  const r = new ZX.MultiFormatReader();
  r.setHints(hints);
  return r;
}

/** Teksturali kadr; barkod berilgan nisbiy joyda. */
function scene(bits: string, opts: {
  w: number; h: number; scale: number; cx: number; cy: number; seed?: number; contrast?: 'yuqori' | 'past';
}): { lum: Uint8ClampedArray; width: number; height: number } {
  const { w, h, scale, cx, cy } = opts;
  const lum = new Uint8ClampedArray(w * h);
  let r = opts.seed ?? 11;
  for (let y = 0; y < h; y++) {
    const band = 112 + ((y >> 4) % 2 ? 20 : -16);            // javon chiziqlari
    for (let x = 0; x < w; x++) {
      r = (1103515245 * r + 12345) & 0x7fffffff;
      lum[y * w + x] = Math.max(0, Math.min(255, band + ((r >> 16) % 30) - 15));
    }
  }
  const bw = bits.length * scale, bh = Math.round(scale * 34), qz = scale * 9;
  const x0 = Math.round(w * cx - bw / 2), y0 = Math.round(h * cy - bh / 2);
  const white = opts.contrast === 'past' ? 196 : 250;
  const black = opts.contrast === 'past' ? 92 : 14;
  for (let y = Math.max(0, y0 - scale * 5); y < Math.min(h, y0 + bh + scale * 5); y++) {
    for (let x = Math.max(0, x0 - qz); x < Math.min(w, x0 + bw + qz); x++) lum[y * w + x] = white;
  }
  for (let i = 0; i < bits.length; i++) {
    if (bits[i] !== '1') continue;
    for (let x = Math.max(0, x0 + i * scale); x < Math.min(w, x0 + (i + 1) * scale); x++) {
      for (let y = Math.max(0, y0); y < Math.min(h, y0 + bh); y++) lum[y * w + x] = black;
    }
  }
  return { lum, width: w, height: h };
}

function decodeScene(reader: any, f: { lum: Uint8ClampedArray; width: number; height: number }): string | null {
  const bitmap = new ZX.BinaryBitmap(new ZX.HybridBinarizer(new ZX.RGBLuminanceSource(f.lum, f.width, f.height)));
  try { return reader.decodeWithState(bitmap).getText(); } catch { return null; }
}

describe('dekodlash chidamliligi — turli joy, fon va kontrast', () => {
  const CODE = '4700024930227';                 // real iPhone sinovidagi kod
  const bits = ean13Bits(CODE);
  // Kesim o'lchami skanerникi bilan bir xil tartibda (tasma, ~0.13–0.35 MP).
  const CASES: Array<[string, { w: number; h: number; scale: number; cx: number; cy: number; contrast?: 'past' }]> = [
    ['markazda',                 { w: 700, h: 300, scale: 4, cx: 0.5, cy: 0.5 }],
    ['chapga surilgan',          { w: 700, h: 300, scale: 4, cx: 0.32, cy: 0.5 }],
    ['o‘ngga surilgan',         { w: 700, h: 300, scale: 4, cx: 0.68, cy: 0.5 }],
    ['yuqorida',                 { w: 700, h: 300, scale: 4, cx: 0.5, cy: 0.28 }],
    ['pastda',                   { w: 700, h: 300, scale: 4, cx: 0.5, cy: 0.72 }],
    ['kichik (uzoqdan)',         { w: 700, h: 300, scale: 3, cx: 0.5, cy: 0.5 }],
    ['katta (yaqindan)',         { w: 700, h: 300, scale: 6, cx: 0.5, cy: 0.5 }],
    ['past kontrast',            { w: 700, h: 300, scale: 4, cx: 0.5, cy: 0.5, contrast: 'past' }],
    ['keng kesim',               { w: 900, h: 380, scale: 4, cx: 0.5, cy: 0.5 }],
  ];
  for (const [nom, o] of CASES) {
    it(`teksturali fon: ${nom}`, () => {
      expect(decodeScene(readerWith(FAST_FORMATS), scene(bits, o as any))).toBe(CODE);
    });
  }

  it('barkodsiz teksturali kadr JIMGINA muvaffaqiyat bermaydi', () => {
    const f = scene(bits, { w: 700, h: 300, scale: 4, cx: 0.5, cy: 0.5 });
    f.lum.fill(0);                                           // etiketkani o'chiramiz
    let r = 5;
    for (let i = 0; i < f.lum.length; i++) { r = (1103515245 * r + 12345) & 0x7fffffff; f.lum[i] = 100 + ((r >> 16) % 40); }
    expect(decodeScene(readerWith(FAST_FORMATS), f)).toBeNull();
  });
});

describe('hint yuvilishi — nega decodeWithState', () => {
  // ⚠️  Vendored buildda `decode(t, e) { return this.setHints(e), this.decodeInternal(t) }`.
  //     Bitta argument bilan chaqirilsa hintlar `undefined` bo'ladi: format
  //     ro'yxati o'chib, ZXing zaxira tarmog'iga tushadi (QRCode, DataMatrix,
  //     Aztec, PDF417 va takroriy 1D o'quvchilar). Teksturali topilmaydigan
  //     kadrda o'lchangan farq: 427x302 da 147 ms va 15 ms, 700x500 da 352 ms
  //     va 35 ms. Bu test AYNAN shu nuqsonni mixlab qo'yadi.
  const bitmapOf = (f: { lum: Uint8ClampedArray; width: number; height: number }) =>
    new ZX.BinaryBitmap(new ZX.HybridBinarizer(new ZX.RGBLuminanceSource(f.lum, f.width, f.height)));
  const noise = (w: number, h: number) => {
    const lum = new Uint8ClampedArray(w * h); let r = 3;
    for (let i = 0; i < lum.length; i++) { r = (1103515245 * r + 12345) & 0x7fffffff; lum[i] = 100 + ((r >> 16) % 40); }
    return { lum, width: w, height: h };
  };

  it('decode(bitmap) format ro‘yxatini O‘CHIRADI, decodeWithState saqlaydi', () => {
    const a = readerWith([ZX.BarcodeFormat.EAN_13]);
    expect(a.readers.length).toBe(1);
    try { a.decode(bitmapOf(noise(64, 64))); } catch { /* topilmadi */ }
    expect(a.hints, 'decode() hintlarni yuvdi').toBeUndefined();
    expect(a.readers.length, 'zaxira o‘quvchilar qo‘shildi').toBeGreaterThan(1);

    const b = readerWith([ZX.BarcodeFormat.EAN_13]);
    try { b.decodeWithState(bitmapOf(noise(64, 64))); } catch { /* topilmadi */ }
    expect(b.readers.length).toBe(1);
  });

  it('scanner.js decodeWithState ishlatadi va TRY_HARDER yoqmaydi', () => {
    const js = fs.readFileSync(path.resolve(__dirname, '../apps/mobile/web/scanner.js'), 'utf-8');
    expect(js).toContain('decodeWithState');
    expect(js).not.toContain('TRY_HARDER, true');
  });

  // Halokatli regressiyani ushlaydi (masalan TRY_HARDER qaytib kelsa: o'lchangan
  // 700x500 da 2406 ms). Chegara ataylab keng — CI mashinasi sekin bo'lishi mumkin.
  it('topilmaydigan kadr narxi oqilona chegarada qoladi', () => {
    const r = readerWith(FAST_FORMATS);
    const f = noise(700, 500);
    const t0 = Date.now();
    for (let i = 0; i < 3; i++) { try { r.decodeWithState(bitmapOf(f)); } catch { /* topilmadi */ } }
    const perAttempt = (Date.now() - t0) / 3;
    expect(perAttempt, `urinishiga ${perAttempt} ms`).toBeLessThan(400);
  });
});
