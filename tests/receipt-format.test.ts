import { describe, expect, it } from "vitest";
import {
  RECEIPT_LABELS, currencyLabel, decAdd, decCmp, decIsZero, decMul, decNeg, decRound, decSub, decSum, fmtMoney,
  fmtQty, isDecimal, labelsFor, methodLabel, type Labels, type ReceiptLang,
} from "@/receipt";

// Phase 5F F1: chekdagi son formati va aniq o'nlik arifmetika (BigInt, float yo'q).

describe("fmtMoney", () => {
  it("minglik — oddiy bo'shliq, kasr — vergul, faqat nolga teng bo'lmasa", () => {
    expect(fmtMoney("24224.00", "uz")).toBe("24 224");
    expect(fmtMoney("4224.50", "ru")).toBe("4 224,50");
    expect(fmtMoney("0.00", "ky")).toBe("0");
    expect(fmtMoney("0.05", "uzc")).toBe("0,05");
    expect(fmtMoney("987654321.00", "uz")).toBe("987 654 321");
    expect(fmtMoney("1000000", "uz")).toBe("1 000 000");
    expect(fmtMoney("999.99", "uz")).toBe("999,99");
    expect(fmtMoney("-1234.40", "uz")).toBe("-1 234,40");
    expect(fmtMoney("-0.00", "uz")).toBe("0");
    expect(fmtMoney("12.5", "uz")).toBe("12,50");
    expect(fmtMoney("12.505", "uz")).toBe("12,51"); // ROUND_HALF_UP
  });
  it("NBSP ham, Intl ham yo'q — faqat ASCII bo'shliq", () => {
    expect(fmtMoney("1234567.89")).not.toMatch(/[\u00a0\u202f]/);
  });
  it("yaroqsiz kirish yiqitmaydi — o'zi qaytadi", () => {
    expect(fmtMoney("abc")).toBe("abc");
    expect(fmtMoney("")).toBe("");
  });
});

describe("fmtQty", () => {
  it("tortiladigan — doim 3 xona; dona — ortiqcha nolsiz", () => {
    expect(fmtQty("0.352", true)).toBe("0,352");
    expect(fmtQty("0.001", true)).toBe("0,001");
    expect(fmtQty("1.000", true)).toBe("1,000");
    expect(fmtQty("2.000", false)).toBe("2");
    expect(fmtQty("1.500", false)).toBe("1,5");
    expect(fmtQty("12500.000", false)).toBe("12 500");
    expect(fmtQty("0.35200000000000004", true)).toBe("0,352");
  });
});

describe("currencyLabel", () => {
  it("4 til", () => {
    expect(currencyLabel("uz")).toBe("so'm");
    expect(currencyLabel("uzc")).toBe("сўм");
    expect(currencyLabel("ru")).toBe("сом");
    expect(currencyLabel("ky")).toBe("сом");
  });
});

describe("o'nlik yordamchilar (BigInt)", () => {
  it("decMul — ROUND_HALF_UP noldan uzoqqa", () => {
    expect(decMul("0.352", "12000.00", 2)).toBe("4224.00");
    expect(decMul("1.235", "89990.50", 2)).toBe("111138.27");
    expect(decMul("0.001", "250000.00", 2)).toBe("250.00");
    expect(decMul("0.005", "1", 2)).toBe("0.01");
    expect(decMul("-0.005", "1", 2)).toBe("-0.01");
    expect(decMul("0.0049", "1", 2)).toBe("0.00");
    expect(decMul("98765432.10", "10.000", 2)).toBe("987654321.00");
  });
  it("float xatosiz: 0.1 + 0.2 = 0.3", () => {
    expect(decAdd("0.1", "0.2")).toBe("0.3");
    expect(decCmp(decAdd("0.1", "0.2"), "0.30")).toBe(0);
    expect(decSub("0.3", "0.1", 2)).toBe("0.20");
    expect(decSum(["0.10", "0.20", "0.30"], 2)).toBe("0.60");
    expect(decSum([], 2)).toBe("0.00");
  });
  it("decCmp masshtabdan mustaqil; decRound/decNeg/decIsZero", () => {
    expect(decCmp("1.50", "1.5")).toBe(0);
    expect(decCmp("-1", "0")).toBe(-1);
    expect(decCmp("10", "9.999")).toBe(1);
    expect(decRound("2.5", 0)).toBe("3");
    expect(decRound("-2.5", 0)).toBe("-3");
    expect(decRound("173112.27", 0)).toBe("173112");
    expect(decRound("7", 2)).toBe("7.00");
    expect(decNeg("0.27")).toBe("-0.27");
    expect(decNeg("-0.27")).toBe("0.27");
    expect(decIsZero("-0.000")).toBe(true);
  });
  it("JS sonining satr ko'rinishi (eksponent) qabul qilinadi, qolgani rad etiladi", () => {
    expect(decRound("1e-7", 3)).toBe("0.000");
    expect(decRound("1.5e3", 2)).toBe("1500.00");
    for (const bad of ["abc", "", ".", "1,5", "1.2.3", "NaN", "Infinity", "0x10", "1e999"]) {
      expect(isDecimal(bad), bad).toBe(false);
      expect(() => decRound(bad, 2), bad).toThrow(/decimal/);
    }
    expect(isDecimal("12.50")).toBe(true);
    expect(isDecimal(12 as unknown)).toBe(false);
  });
});

describe("RECEIPT_LABELS", () => {
  const LANGS: ReceiptLang[] = ["uz", "uzc", "ru", "ky"];
  const keys = Object.keys(RECEIPT_LABELS.uz) as (keyof Labels)[];

  it("4 tilda bir xil kalitlar, bo'sh qiymat yo'q", () => {
    expect(keys.length).toBe(30);
    for (const l of LANGS) {
      expect(Object.keys(RECEIPT_LABELS[l]).sort()).toEqual([...keys].sort());
      for (const k of keys) expect(RECEIPT_LABELS[l][k].trim(), `${l}.${k}`).not.toBe("");
    }
  });
  it("testTitle hamma tilda '*** TEST PRINT ***'; testSub tarjima qilingan", () => {
    for (const l of LANGS) expect(RECEIPT_LABELS[l].testTitle).toBe("*** TEST PRINT ***");
    expect(RECEIPT_LABELS.uz.testSub).toBe("sotuv emas");
    expect(RECEIPT_LABELS.ru.testSub).toBe("не продажа");
  });
  it("haqiqiy tarjimalar: ru/ky/uzc kirill, uz lotin; ky da qirg'iz harflari", () => {
    const cyr = /[Ѐ-ӿ]/;
    for (const k of ["receipt", "total", "cashier", "footerDefault", "change"] as const) {
      expect(RECEIPT_LABELS.uz[k]).not.toMatch(cyr);
      expect(RECEIPT_LABELS.ru[k]).toMatch(cyr);
      expect(RECEIPT_LABELS.ky[k]).toMatch(cyr);
      expect(RECEIPT_LABELS.uzc[k]).toMatch(cyr);
    }
    expect(Object.values(RECEIPT_LABELS.ky).join(" ")).toMatch(/[ңөү]/);
    expect(Object.values(RECEIPT_LABELS.uzc).join(" ")).toMatch(/[ўқғҳ]/);
    // Hech bir yorliqda boshqaruv belgisi yo'q.
    for (const l of LANGS) {
      for (const k of keys) {
        expect(Array.from(RECEIPT_LABELS[l][k]).every((c) => (c.codePointAt(0) as number) >= 0x20)).toBe(true);
      }
    }
  });
  it("labelsFor noma'lum tilda ru ga qaytadi; methodLabel", () => {
    expect(labelsFor("xx")).toBe(RECEIPT_LABELS.ru);
    expect(labelsFor(null)).toBe(RECEIPT_LABELS.ru);
    expect(methodLabel(RECEIPT_LABELS.uz, "cash")).toBe("Naqd");
    expect(methodLabel(RECEIPT_LABELS.ru, "credit")).toBe("В долг");
    expect(methodLabel(RECEIPT_LABELS.ky, "card")).toBe("Карта");
    expect(methodLabel(RECEIPT_LABELS.uz, "wire")).toBe("wire");
  });
});
