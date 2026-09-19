import { describe, expect, it } from "vitest";
import { code128Modules } from "@/receipt";
import { CODE128_WIDTHS } from "@/receipt/code128";

// Phase 5F F1: oflayn namuna uchun CODE128-B. Jadval tuzilishi (ISO/IEC 15417 xossalari) va ma'lum
// vektorlar bilan tekshiriladi; haqiqiy chekda modullarni server beradi.

const START_B = "11010010000";
const STOP = "1100011101011";

function toModules(w: string): string {
  let s = "";
  for (let i = 0; i < w.length; i++) s += (i % 2 === 0 ? "1" : "0").repeat(Number(w[i]));
  return s;
}

describe("CODE128 jadvali", () => {
  it("107 belgi; 0..105: 3 chiziq + 3 bo'shliq, 11 modul, chiziqlar yig'indisi juft; stop 13 modul", () => {
    expect(CODE128_WIDTHS.length).toBe(107);
    for (let v = 0; v <= 105; v++) {
      const w = CODE128_WIDTHS[v].split("").map(Number);
      expect(w.length, String(v)).toBe(6);
      expect(w.every((x) => x >= 1 && x <= 4), String(v)).toBe(true);
      expect(w.reduce((a, b) => a + b, 0), String(v)).toBe(11);
      expect((w[0] + w[2] + w[4]) % 2, `bar parity ${v}`).toBe(0);
      expect((w[1] + w[3] + w[5]) % 2, `space parity ${v}`).toBe(1);
    }
    expect(toModules(CODE128_WIDTHS[106])).toBe(STOP);
    expect(new Set(CODE128_WIDTHS).size).toBe(107);
  });

  it("ma'lum naqshlar: bo'shliq (0), '0' (16), 'A' (33), Start B (104)", () => {
    expect(toModules(CODE128_WIDTHS[0])).toBe("11011001100");
    expect(toModules(CODE128_WIDTHS[16])).toBe("10011101100");
    expect(toModules(CODE128_WIDTHS[17])).toBe("10011100110");
    expect(toModules(CODE128_WIDTHS[33])).toBe("10100011000");
    expect(toModules(CODE128_WIDTHS[104])).toBe(START_B);
  });
});

describe("code128Modules", () => {
  it("'A' → Start B + A + checksum(34) + Stop", () => {
    expect(code128Modules("A")).toBe(START_B + "10100011000" + toModules(CODE128_WIDTHS[34]) + STOP);
  });

  it("dekodlash: modullar qayta qiymatlarga, checksum to'g'ri", () => {
    const inverse = new Map(CODE128_WIDTHS.slice(0, 106).map((w, v) => [toModules(w), v]));
    for (const payload of ["2609191288", "0000000000", "Test {B} ~ 123", " "]) {
      const m = code128Modules(payload) as string;
      expect(m.endsWith(STOP)).toBe(true);
      const body = m.slice(0, m.length - STOP.length);
      expect(body.length % 11).toBe(0);
      const values: number[] = [];
      for (let i = 0; i < body.length; i += 11) values.push(inverse.get(body.slice(i, i + 11)) as number);
      expect(values[0]).toBe(104);
      const data = values.slice(1, -1);
      expect(String.fromCharCode(...data.map((v) => v + 32))).toBe(payload);
      const sum = data.reduce((s, v, i) => s + v * (i + 1), 104);
      expect(values[values.length - 1]).toBe(sum % 103);
    }
  });

  it("yaroqsiz kirish → null", () => {
    expect(code128Modules("")).toBeNull();
    expect(code128Modules("Ўз")).toBeNull();
    expect(code128Modules("a\nb")).toBeNull();
    expect(code128Modules("x".repeat(65))).toBeNull();
  });
});
