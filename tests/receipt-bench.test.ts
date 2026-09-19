import { describe, expect, it } from "vitest";
import {
  decAdd, decMul, decRound, decSub, encodeEscPos, layoutReceipt, profileFor, renderHtml, type ReceiptDTO,
} from "@/receipt";
import { FULL_TEMPLATE, LOGO_64x16, saleDto } from "./__golden__/receipt/fixtures";

// Phase 5F F1: tezlik — 100 va 500 qatorli chek (layout + HTML + ESC/POS). Chegara ataylab keng
// (sekin CI mashinasi); maqsad — kvadratik/eksponentsial regressiyani ushlash, vaqtni jurnalga chiqarish.

function bigDto(n: number): ReceiptDTO {
  const dto = saleDto();
  const names = [
    "Молоко ультрапастеризованное «Простоквашино» 3,2% 950 мл",
    "Кымыз табигый, жаңы саалган 1 л (Суусамыр өрөөнү)",
    "Oʻzbekiston paxta yogʻi tozalangan 1 l (Gʻallaorol)",
    "СуперДлинноеНазваниеТовараБезПробеловКотороеНеПомещаетсяВСтроку",
  ];
  dto.lines = [];
  let sub = "0.00";
  let disc = "0.00";
  for (let i = 0; i < n; i++) {
    const weighted = i % 4 === 1;
    const qty = weighted ? "1.235" : "3.000";
    const price = (1000 + i * 37.5).toFixed(2);
    const gross = decMul(qty, price, 2);
    const discount = i % 6 === 0 ? decMul(gross, "0.05", 2) : "0.00";
    dto.lines.push({
      name: `${names[i % names.length]} #${i + 1}`, qty, unit: weighted ? "kg" : "dona", weighted,
      unit_price: price, gross, discount, total: decSub(gross, discount, 2),
    });
    sub = decAdd(sub, gross, 2);
    disc = decAdd(disc, discount, 2);
  }
  const net = decSub(sub, disc, 2);
  const total = decRound(decRound(net, 0), 2);
  dto.totals = { currency: "UZS", subtotal: sub, line_discount: disc, doc_discount: "0.00", rounding: decSub(total, net, 2), total };
  dto.payments = [
    { method: "cash", amount: "50000.00", given: null, change: null },
    { method: "card", amount: decSub(total, "50000.00", 2), given: null, change: null },
  ];
  return dto;
}

describe("chek tezligi", () => {
  for (const n of [100, 500]) {
    it(`${n} qator: layout + html + escpos (58 va 80)`, () => {
      const dto = bigDto(n);
      const t0 = performance.now();
      let bytes = 0;
      let htmlLen = 0;
      for (const w of [58, 80] as const) {
        const doc = layoutReceipt(dto, { width_mm: w, lang: "ru", template: FULL_TEMPLATE, logo: LOGO_64x16 });
        expect(doc.warnings).toEqual([]);
        htmlLen += renderHtml(doc).length;
        bytes += encodeEscPos(doc, profileFor(w === 58 ? "generic58" : "epson80", w)).bytes.length;
      }
      const ms = performance.now() - t0;
      // eslint-disable-next-line no-console
      console.log(`[receipt-bench] ${n} qator: ${ms.toFixed(1)} ms (html ${htmlLen} belgi, escpos ${bytes} bayt)`);
      expect(bytes).toBeGreaterThan(n * 40);
      expect(ms).toBeLessThan(n === 100 ? 1500 : 5000);
    });
  }
});
