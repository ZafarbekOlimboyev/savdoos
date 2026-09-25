import { describe, expect, it } from "vitest";
import * as fs from "fs";
import * as path from "path";
import {
  ean13Checksum, normalizePlu, parseScaleBarcode, pluMatches, scaleDigits, scaleQty, SCALE_PREFIX,
} from "@/lib/scaleBarcode";

// Phase 5G: tarozi etiketkasi qoidasi POS (`lib/scaleBarcode.ts`) va server
// (`apps/server/app/services/scale_barcode.py`, `GET /products/scan`) uchun BITTA.
// Ikkalasi AYNI vektor faylini tekshiradi — bir tomon o'zgarsa, ikkinchisi qizaradi.
type Scale = { prefix: string; plu: string; grams: number; qty: string; checksum: number };
type Label = { code: string; digits: string; scale: Scale | null; note?: string };
type PluCase = { plu_code: string | null; plu: string | number; match: boolean };
const V = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "fixtures/scale_barcodes.json"), "utf-8"),
) as { labels: Label[]; plu_match: PluCase[]; mapping: Record<string, string> };

// Fayzan do'konidan olingan HAQIQIY etiketkalar — kontraktning asosi.
const REAL: Array<[string, string, number, string]> = [
  ["2700345032787", "00345", 3278, "3.278"],
  ["2700565020205", "00565", 2020, "2.020"],
  ["2700537004264", "00537", 426, "0.426"],
  ["2700349000560", "00349", 56, "0.056"],
];

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
        // HAR BEShTA maydon tekshiriladi — aks holda "vektor qo'shdim" isboti yolg'on bo'ladi.
        expect(got).toEqual({
          prefix: v.scale.prefix, plu: v.scale.plu, grams: v.scale.grams, checksum: v.scale.checksum,
        });
        expect(got!.prefix).toBe(SCALE_PREFIX);
        expect(got!.plu).toHaveLength(5);
        expect(scaleQty(got!.grams)).toBe(v.scale.qty);
        // POS savatga `grams / 1000` qo'yadi — 3 xonali satr bilan AYNI son.
        expect(got!.grams / 1000).toBe(Number(v.scale.qty));
        // Nazorat raqami AYNAN EAN-13 bo'yicha.
        expect(ean13Checksum(v.digits.slice(0, 12))).toBe(v.scale.checksum);
      }
    });
  }

  for (const c of V.plu_match) {
    it(`PLU ${JSON.stringify(c.plu_code)} ~ ${c.plu}`, () => {
      expect(pluMatches(c.plu_code, c.plu)).toBe(c.match);
    });
  }
});

describe("Fayzan REAL etiketkalari", () => {
  for (const [code, plu, grams, qty] of REAL) {
    it(`${code} -> PLU ${plu}, ${qty} kg`, () => {
      const got = parseScaleBarcode(code);
      expect(got).not.toBeNull();
      expect(got!.prefix).toBe("27");
      expect(got!.plu).toBe(plu);           // 5 xonali SATR, yetakchi nollar bilan
      expect(got!.grams).toBe(grams);
      expect(scaleQty(got!.grams)).toBe(qty);
      expect(got!.checksum).toBe(Number(code[12]));
    });
  }

  // REGRESSIYA: eski taxmin `2 + PLU(6) + gramm(5)` PLU ni 700000 ga surardi.
  it("eski 6 xonali layout qaytib kelmasin", () => {
    for (const [code, plu] of REAL) {
      const got = parseScaleBarcode(code)!;
      expect(got.plu).not.toBe(code.slice(1, 7));   // "700345" kabi qiymat EMAS
      expect(got.plu).toBe(plu);
      expect(Number(got.plu)).toBeLessThanOrEqual(99999);  // BinOS `plu_code` 1-5 xona
    }
  });

  // NARX EMAS, VAZN: etiketkadagi summa = narx x (gramm / 1000).
  it("8-12-raqamlar GRAMM ekani summa bilan isbotlanadi", () => {
    const cases: Array<[string, number, number]> = [
      ["2700537004264", 350, 149.10],
      ["2700349000560", 580, 32.48],
    ];
    for (const [code, perKg, total] of cases) {
      const got = parseScaleBarcode(code)!;
      expect(Number((perKg * (got.grams / 1000)).toFixed(2))).toBe(total);
    }
  });

  it("nazorat raqami buzilsa etiketka QABUL QILINMAYDI", () => {
    for (const [code] of REAL) {
      const bad = code.slice(0, 12) + String((Number(code[12]) + 1) % 10);
      expect(parseScaleBarcode(bad)).toBeNull();
    }
  });
});

describe("PLU kanonik shakli — yetakchi nollar", () => {
  it("normalizePlu 5 xonaga to'ldiradi", () => {
    expect(normalizePlu("537")).toBe("00537");
    expect(normalizePlu("00537")).toBe("00537");
    expect(normalizePlu(537)).toBe("00537");
    expect(normalizePlu("0")).toBe("00000");
  });

  it("etiketkada bosilgan 6 xonali KOD — PLU maydoni EMAS", () => {
    expect(normalizePlu("000537")).toBeNull();
    expect(pluMatches("000537", "00537")).toBe(false);
  });

  // Hujjatlashtirilgan zanjir: KOD 000537 -> barkod PLU 00537 -> BinOS plu_code 537.
  it("DB dagi yetakchi nolsiz qiymat etiketka PLU'siga mos keladi", () => {
    const got = parseScaleBarcode("2700537004264")!;
    expect(V.mapping.barkod_plu_maydoni).toBe(got.plu);
    expect(pluMatches(V.mapping.binos_plu_code, got.plu)).toBe(true);
    expect(pluMatches("537", got.plu)).toBe(true);
    expect(got.plu).toBe("00537");          // yetakchi nol PARSE natijasida YO'QOLMAYDI
  });
});
