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
