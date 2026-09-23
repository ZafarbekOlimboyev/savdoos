import { describe, expect, it } from "vitest";
import * as fs from "fs";
import * as path from "path";
import { parseScaleBarcode, pluMatches, scaleDigits, scaleQty } from "@/lib/scaleBarcode";

// Phase 5G: tarozi etiketkasi qoidasi POS (`lib/scaleBarcode.ts`) va server
// (`apps/server/app/services/scale_barcode.py`, `GET /products/scan`) uchun BITTA.
// Ikkalasi AYNI vektor faylini tekshiradi — bir tomon o'zgarsa, ikkinchisi qizaradi.
type Label = { code: string; digits: string; scale: { plu: number; grams: number; qty: string } | null };
type PluCase = { plu_code: string | null; plu: number; match: boolean };
const V = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "fixtures/scale_barcodes.json"), "utf-8"),
) as { labels: Label[]; plu_match: PluCase[] };

describe("Tarozi etiketkasi — umumiy vektorlar (POS == server)", () => {
  it("vektorlar bo'sh emas", () => {
    expect(V.labels.length).toBeGreaterThanOrEqual(10);
    expect(V.plu_match.length).toBeGreaterThanOrEqual(8);
  });

  for (const v of V.labels) {
    it(`etiketka ${JSON.stringify(v.code)}`, () => {
      expect(scaleDigits(v.code)).toBe(v.digits);
      const got = parseScaleBarcode(v.code);
      if (v.scale === null) {
        expect(got).toBeNull();
      } else {
        expect(got).toEqual({ plu: v.scale.plu, grams: v.scale.grams });
        expect(scaleQty(got!.grams)).toBe(v.scale.qty);
        // POS savatga `grams / 1000` qo'yadi — 3 xonali satr bilan AYNI son.
        expect(got!.grams / 1000).toBe(Number(v.scale.qty));
      }
    });
  }

  for (const c of V.plu_match) {
    it(`PLU ${JSON.stringify(c.plu_code)} ~ ${c.plu}`, () => {
      expect(pluMatches(c.plu_code, c.plu)).toBe(c.match);
    });
  }
});
