// Chek sinovlari uchun umumiy fixture'lar va golden yordamchisi (sinov fayli EMAS — vitest faqat
// `*.test.ts` ni yig'adi). DTO'lar SPEC §3 ga aniq mos: pul — 2 xona, miqdor — 3 xona satr.
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { expect } from "vitest";
import { BUILTIN_TEMPLATE, code128Modules } from "@/receipt";
import type { LogoVariant, ReceiptDTO, ReceiptTemplate } from "@/receipt";

export const GOLDEN_DIR = path.dirname(fileURLToPath(import.meta.url));

/**
 * Golden fayl bilan solishtirish. Yangilash: `UPDATE_GOLDEN=1 npx vitest run tests/receipt-*.test.ts`
 * — keyin git diff'ni KO'ZDAN KECHIRING. Fayl yo'q bo'lsa sinov yiqiladi (jimgina yaratilmaydi).
 */
export function expectGolden(name: string, content: string): void {
  const file = path.join(GOLDEN_DIR, name);
  const got = content.replace(/\r\n/g, "\n");
  if (process.env.UPDATE_GOLDEN === "1") {
    fs.writeFileSync(file, got, "utf8");
    return;
  }
  if (!fs.existsSync(file)) {
    throw new Error(`golden yo'q: ${name} — UPDATE_GOLDEN=1 bilan yarating va ko'zdan kechiring`);
  }
  // Windows'da git autocrlf CRLF qilib qo'yishi mumkin — solishtirishda normallashtiramiz.
  const want = fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n");
  expect(got).toBe(want);
}

/** Har satrni `|...|` ramkaga oladi — kenglik va oxirgi bo'shliqlar golden'da ko'rinsin. */
export function framed(lines: readonly string[], cols: number): string {
  return lines.map((l) => "|" + l + " ".repeat(Math.max(0, cols - Array.from(l).length)) + "|").join("\n");
}

export const tpl = (over: Partial<ReceiptTemplate> = {}): ReceiptTemplate => ({ ...BUILTIN_TEMPLATE, ...over });

// Python `qrcode` (EC M, border 0) bilan "2609191288" uchun olingan HAQIQIY matritsa (versiya 1).
export const QR_MATRIX_1288: string[] = [
  "111111100100001111111",
  "100000101110101000001",
  "101110101001101011101",
  "101110101111001011101",
  "101110100100101011101",
  "100000100101001000001",
  "111111101010101111111",
  "000000001000000000000",
  "100000101101011001110",
  "001111011111110111001",
  "001010101000101100010",
  "100011000001111101100",
  "001111111111111110111",
  "000000001100100001010",
  "111111100101010010101",
  "100000100110001000000",
  "101110100101010010100",
  "101110100101111000100",
  "101110100011110111111",
  "100000100111111000010",
  "111111101110100100100",
];

// 64×16 1-bit logo (ramka + shaxmat); PNG — Pillow bilan xuddi shu rasmdan.
export const LOGO_64x16: LogoVariant = {
  width: 64,
  height: 16,
  raster_b64:
    "//////////+AAAAAAAAAAYAAAAAAAAABgAAAAAAAAAGPDw8PDw8PAY8PDw8PDw8Bjw8PDw8PDwGPDw8PDw8PAYDw8PDw8PDxgPDw8PDw8PGA8PDw8PDw8YDw8PDw8PDxgAAAAAAAAAGAAAAAAAAAAYAAAAAAAAAB//////////8=",
  png_data_uri:
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAAAQAQAAAACOnESEAAAAK0lEQVR4nGNggIH6/2DwjwkmAGewfPwIpvkwpRBq+OXB9H98ahg+4FIDBwAsbAykKq7gjwAAAABJRU5ErkJggg==",
};

const UZ_OK = "ʻ"; // oʻ gʻ dagi "ʻ" (U+02BB)

export const FULL_TEMPLATE = tpl({
  header: "Har kuni yangi mahsulotlar!",
  show_till: true,
  show_customer: true,
  show_barcode: true,
  qr_mode: "receipt_id",
});

/** To'liq sotuv: logo, chegirmalar, yaxlitlash, aralash to'lov, xaridor, shtrix-kod, QR. */
export function saleDto(): ReceiptDTO {
  return {
    schema: "binos.receipt.v1",
    kind: "SALE",
    test: false,
    provisional: false,
    doc: {
      id: "3f1c2a9e-5b7d-4e21-9a0c-6d8e4f2b1a77", number: "#1288", uid: "2609191288",
      issued_at: "2026-09-19T09:32:11+00:00", issued_at_local: "19.09.2026 14:32", tz: "Asia/Tashkent",
      is_offline: false, status: "completed",
    },
    store: {
      name: "Fayzan Market", branch_name: "Chilonzor filiali",
      address: "Toshkent sh., Chilonzor tumani, Bunyodkor ko'chasi 12-uy", phone: "+998 90 123-45-67",
      stir: "305123456",
    },
    actor: { cashier: "Dilnoza Karimova", till_code: "K-01", terminal: "POS-1" },
    customer: { name: "Aliyev Vali" },
    lines: [
      { name: 'Non "Samarqand" 500 g', qty: "2.000", unit: "dona", weighted: false, unit_price: "4000.00",
        gross: "8000.00", discount: "0.00", total: "8000.00" },
      { name: "Pomidor (issiqxona)", qty: "0.352", unit: "kg", weighted: true, unit_price: "12000.00",
        gross: "4224.00", discount: "0.00", total: "4224.00" },
      { name: `Qo${UZ_OK}y go${UZ_OK}shti yangi, suyaksiz`, qty: "1.235", unit: "kg", weighted: true,
        unit_price: "89990.50", gross: "111138.27", discount: "5000.00", total: "106138.27" },
      { name: "Кымыз табигый 1 л (Суусамыр өрөөнү, жаңы)", qty: "3.000", unit: "dona", weighted: false,
        unit_price: "18500.00", gross: "55500.00", discount: "0.00", total: "55500.00" },
      { name: "Ziravor (zira)", qty: "0.001", unit: "kg", weighted: true, unit_price: "250000.00",
        gross: "250.00", discount: "0.00", total: "250.00" },
    ],
    totals: {
      currency: "UZS", subtotal: "179112.27", line_discount: "5000.00", doc_discount: "1000.00",
      rounding: "-0.27", total: "173112.00",
    },
    payments: [
      { method: "cash", amount: "100000.00", given: null, change: null },
      { method: "card", amount: "73112.00", given: null, change: null },
    ],
    refund: null,
    original: null,
    barcode: { format: "CODE128", payload: "2609191288", modules: code128Modules("2609191288") as string },
    qr: { kind: "receipt_id", payload: "2609191288", size: 21, matrix: QR_MATRIX_1288 },
    logo: { id: "0b6c7c55-1f59-5b0e-9d7b-2d6f0f0a8c11", sha256: "a".repeat(64) },
    template: FULL_TEMPLATE,
  };
}

/** Qaytarish: kartaga qaytarildi, asl chekka havola bilan. */
export function returnDto(): ReceiptDTO {
  return {
    schema: "binos.receipt.v1",
    kind: "RETURN",
    test: false,
    provisional: false,
    doc: {
      id: "9d2e4b1c-7a3f-4c8e-b5d6-1e2f3a4b5c6d", number: "QAY-1003", uid: null,
      issued_at: "2026-09-19T11:05:40+00:00", issued_at_local: "19.09.2026 16:05", tz: "Asia/Tashkent",
      is_offline: false, status: "completed",
    },
    store: {
      name: "Fayzan Market", branch_name: "Chilonzor filiali", address: null, phone: "+998 90 123-45-67",
      stir: "305123456",
    },
    actor: { cashier: "Dilnoza Karimova", till_code: "K-01", terminal: null },
    customer: null,
    lines: [
      { name: "Pomidor (issiqxona)", qty: "0.352", unit: "kg", weighted: true, unit_price: "12000.00",
        gross: "4224.00", discount: "0.00", total: "4224.00" },
      { name: 'Non "Samarqand" 500 g', qty: "1.000", unit: "dona", weighted: false, unit_price: "4000.00",
        gross: "4000.00", discount: "0.00", total: "4000.00" },
    ],
    totals: {
      currency: "UZS", subtotal: "8224.00", line_discount: "0.00", doc_discount: "0.00", rounding: "0.00",
      total: "8224.00",
    },
    payments: [],
    refund: { method: "card", amount: "8224.00" },
    original: { id: "3f1c2a9e-5b7d-4e21-9a0c-6d8e4f2b1a77", number: "#1288", uid: "2609191288",
      issued_at_local: "19.09.2026 14:32" },
    barcode: null,
    qr: null,
    logo: null,
    template: tpl(),
  };
}

/** Kichik chek (ESC/POS golden): 2 qator, bitta naqd to'lov (berildi/qaytim), shtrix-kod, QR. */
export function smallDto(): ReceiptDTO {
  return {
    ...saleDto(),
    customer: null,
    lines: [
      { name: 'Non "Samarqand" 500 g', qty: "2.000", unit: "dona", weighted: false, unit_price: "4000.00",
        gross: "8000.00", discount: "0.00", total: "8000.00" },
      { name: "Pomidor (issiqxona)", qty: "0.352", unit: "kg", weighted: true, unit_price: "12000.00",
        gross: "4224.00", discount: "0.00", total: "4224.00" },
    ],
    totals: {
      currency: "UZS", subtotal: "12224.00", line_discount: "0.00", doc_discount: "0.00", rounding: "0.00",
      total: "12224.00",
    },
    payments: [{ method: "cash", amount: "12224.00", given: "20000.00", change: "7776.00" }],
    template: tpl({ show_barcode: true, qr_mode: "receipt_id" }),
  };
}

const MONEY_RE = /^-?\d+\.\d{2}$/;
const QTY_RE = /^\d+\.\d{3}$/;

/** DTO SPEC §3 formatiga mosmi: hamma pul 2 xona, miqdor 3 xona satr. Buzilgan maydonlar ro'yxati. */
export function dtoFormatProblems(d: ReceiptDTO): string[] {
  const bad: string[] = [];
  const m = (v: unknown, f: string) => {
    if (typeof v !== "string" || !MONEY_RE.test(v)) bad.push(`${f}=${String(v)}`);
  };
  d.lines.forEach((l, i) => {
    if (!QTY_RE.test(l.qty)) bad.push(`lines[${i}].qty=${l.qty}`);
    m(l.unit_price, `lines[${i}].unit_price`);
    m(l.gross, `lines[${i}].gross`);
    m(l.discount, `lines[${i}].discount`);
    m(l.total, `lines[${i}].total`);
  });
  for (const k of ["subtotal", "line_discount", "doc_discount", "rounding", "total"] as const) {
    m(d.totals[k], `totals.${k}`);
  }
  d.payments.forEach((p, i) => {
    m(p.amount, `payments[${i}].amount`);
    if (p.given !== null) m(p.given, `payments[${i}].given`);
    if (p.change !== null) m(p.change, `payments[${i}].change`);
  });
  if (d.refund) m(d.refund.amount, "refund.amount");
  return bad;
}
