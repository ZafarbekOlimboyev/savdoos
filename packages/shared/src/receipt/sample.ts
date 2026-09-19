// Oflayn namuna chek (TEST) — server `/receipt/sample` javob bermaganda Manager oldindan ko'rishi va
// test chop etish uchun. HAMMA summalar o'nlik yordamchilar bilan hisoblanadi: namuna ham server
// invariantlarini saqlaydi (oraliq − chegirmalar + yaxlitlash = JAMI, Σ to'lovlar = JAMI).
//
// Deterministik: sana o'zgarmas (TEST banneri bilan chiqadi); kerak bo'lsa chaqiruvchi
// `dto.doc.issued_at_local` ni almashtiradi. QR matritsasi bu yerda hisoblanmaydi (QR kodlovchi yo'q) —
// `qr: null`; shtrix-kod esa CODE128-B bilan (code128.ts).
import type { PayMethod, ReceiptDTO, ReceiptLine, ReceiptTemplate } from "./types";
import { BUILTIN_TEMPLATE } from "./types";
import { decMul, decRound, decSub, decSum, decCmp } from "./format";
import { normalizeTemplate } from "./layout";
import { code128Modules } from "./code128";

export type SampleKind = "sale" | "mixed" | "return" | "long";

const ISSUED_AT = "2026-09-19T09:32:11+00:00";
const ISSUED_AT_LOCAL = "19.09.2026 14:32";
const SAMPLE_UID = "0000000000";

function line(name: string, qty: string, unit: string | null, weighted: boolean, price: string, discount = "0.00"): ReceiptLine {
  const q = decRound(qty, 3);
  const p = decRound(price, 2);
  const gross = decMul(q, p, 2);
  const d = decRound(discount, 2);
  return { name, qty: q, unit, weighted, unit_price: p, gross, discount: d, total: decSub(gross, d, 2) };
}

const SALE_LINES = (): ReceiptLine[] => [
  line("Non \"Toshkent\" 500 g", "2", "dona", false, "4000"),
  line("Pomidor", "0.352", "kg", true, "12000"),
  line("Молоко 3,2% 1 л", "1", "dona", false, "11500", "500"),
];

const MIXED_LINES = (): ReceiptLine[] => [
  ...SALE_LINES(),
  line("Olma Golden", "1.235", "kg", true, "18990"),
  line("Шоколад молочный 90 г", "3", "dona", false, "8750.50"),
];

const RETURN_LINES = (): ReceiptLine[] => [
  line("Молоко 3,2% 1 л", "1", "dona", false, "11000"),
  line("Pomidor", "0.352", "kg", true, "12000"),
];

// Uzun nomlar: rus, qirg'iz (ң ө ү), o'zbek lotin (oʻ gʻ — U+02BB), o'zbek kirill, bo'shliqsiz uzun so'z.
const LONG_NAMES = [
  "Молоко ультрапастеризованное «Простоквашино» 3,2% 950 мл",
  "Кымыз табигый, жаңы саалган 1 л (Суусамыр өрөөнү)",
  "Oʻzbekiston paxta yogʻi tozalangan 1 l (Gʻallaorol)",
  "Ўзбекистон гилоси, янги узилган (Фарғона водийси)",
  "Колбаса варёная «Докторская» ГОСТ высший сорт 500 г",
  "СуперДлинноеНазваниеТовараБезПробеловКотороеНеПомещаетсяВСтроку",
  "Өрүк кургатылган Баткен, жогорку сорт, үй шартында",
  "Qoʻy goʻshti yangi soʻyilgan, suyaksiz",
];
const LONG_PRICES = ["4000", "12990.50", "250000", "1500", "86400", "3999.99", "17250"];

function longLines(): ReceiptLine[] {
  const out: ReceiptLine[] = [];
  for (let i = 0; i < 120; i++) {
    const name = `${LONG_NAMES[i % LONG_NAMES.length]} #${i + 1}`;
    const price = LONG_PRICES[i % LONG_PRICES.length];
    const weighted = i % 5 === 1;
    const qty = weighted ? ["0.001", "1.235", "0.352", "12.500"][Math.floor(i / 5) % 4] : String((i % 4) + 1);
    let l = line(name, qty, weighted ? "kg" : "dona", weighted, price);
    if (i % 7 === 3) l = line(name, qty, weighted ? "kg" : "dona", weighted, price, decMul(l.gross, "0.05", 2));
    out.push(l);
  }
  // Katta summa: 9 xonali jami (987 654 321 atrofi) — minglik ajratgich va kenglik sinovi.
  out.push(line("Sanoat muzlatkichi kompleksi (ombor uchun), oʻrnatish bilan", "8", "dona", false, "98765432.10"));
  return out;
}

function totalsOf(lines: ReceiptLine[], docDiscount: string) {
  const subtotal = decSum(lines.map((l) => l.gross), 2);
  const line_discount = decSum(lines.map((l) => l.discount), 2);
  const doc_discount = decRound(docDiscount, 2);
  const net = decSub(decSub(subtotal, line_discount, 2), doc_discount, 2);
  const total = decRound(decRound(net, 0), 2); // server kabi butun so'mga ROUND_HALF_UP
  return { currency: "UZS", subtotal, line_discount, doc_discount, rounding: decSub(total, net, 2), total };
}

const pay = (method: PayMethod, amount: string, given: string | null = null, change: string | null = null) => ({
  method, amount: decRound(amount, 2), given: given === null ? null : decRound(given, 2),
  change: change === null ? null : decRound(change, 2),
});

export function sampleReceipt(
  kind: SampleKind,
  store?: Partial<ReceiptDTO["store"]>,
  template?: Partial<ReceiptTemplate>,
): ReceiptDTO {
  const T = normalizeTemplate({ ...BUILTIN_TEMPLATE, ...(template ?? {}) });
  const k: SampleKind = kind === "mixed" || kind === "return" || kind === "long" ? kind : "sale";
  const isReturn = k === "return";
  const lines = k === "sale" ? SALE_LINES() : k === "mixed" ? MIXED_LINES() : k === "return" ? RETURN_LINES() : longLines();
  const totals = totalsOf(lines, k === "long" ? "1000" : "0");

  let payments: ReceiptDTO["payments"] = [];
  if (k === "sale") {
    // Naqd: xaridor 25 000 berdi (jami undan oshsa — aniq summa), qaytim = berilgan − jami.
    const g = decCmp(totals.total, "25000") <= 0 ? "25000.00" : totals.total;
    payments = [pay("cash", totals.total, g, decSub(g, totals.total, 2))];
  } else if (k === "mixed" || k === "long") {
    const cash = k === "long" ? "150000.00" : "20000.00";
    const qr = k === "long" ? "250000.00" : "15000.00";
    payments = [pay("cash", cash), pay("qr", qr), pay("card", decSub(decSub(totals.total, cash, 2), qr, 2))];
  }

  const uid = isReturn ? null : SAMPLE_UID;
  const modules = uid && T.show_barcode ? code128Modules(uid) : null;
  return {
    schema: "binos.receipt.v1",
    kind: isReturn ? "RETURN" : "SALE",
    test: true,
    provisional: false,
    doc: {
      id: null, number: "TEST", uid, issued_at: ISSUED_AT, issued_at_local: ISSUED_AT_LOCAL,
      tz: "Asia/Tashkent", is_offline: false, status: "completed",
    },
    store: {
      name: store?.name ?? "SavdoOS",
      branch_name: store?.branch_name ?? null,
      address: store?.address ?? null,
      phone: store?.phone ?? null,
      stir: store?.stir ?? null,
    },
    actor: { cashier: "Dilnoza Karimova", till_code: "K-01", terminal: null },
    customer: T.show_customer ? { name: "Ali Valiyev" } : null,
    lines,
    totals,
    payments,
    refund: isReturn ? { method: "cash", amount: totals.total } : null,
    original: isReturn ? { id: null, number: "TEST", uid: null, issued_at_local: ISSUED_AT_LOCAL } : null,
    barcode: uid && modules ? { format: "CODE128", payload: uid, modules } : null,
    qr: null,
    logo: null,
    template: T,
  };
}
