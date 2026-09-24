import { describe, expect, it } from "vitest";
import { translateServerError } from "@/lib/serverErrors";
import { useLang } from "@/store/lang";

// SERVER XATOSINING OXIRGI CHEGARASI (Phase 5G.1, B3 — AU-2 T23).
//
// `translateServerError` — `api.ts` zanjirining OXIRGI bo'g'ini. Lug'atda yo'q matn
// ilgari AYNAN ko'rsatilardi: UUID ham, `Traceback`/`[SQL: ...]` ham. Mobil ilovada
// (`errors.dart:_sanitize`) bunday to'r bor edi, desktopda YO'Q edi. Bu sinovlar
// to'rni desktopga ham qo'yadi: lug'atdagi matnlar avvalgidek tarjima qilinadi,
// noma'lum matn esa id'siz va ichki lug'atsiz chiqadi.

const UUID = "3f2a9c1e-7b4d-4e0a-9c11-2b7f8e6d5a10";
const UUID2 = "9d1c0b2a-1111-4222-8333-444455556666";
const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
const INTERNAL = [
  "Traceback (most recent call last): File \"/app/x.py\", line 3",
  "(psycopg.errors.UndefinedTable) relation \"cash.x\" does not exist [SQL: SELECT 1]",
  "sqlalchemy.exc.IntegrityError: duplicate key",
  "stock_invariant.Mismatch: product 1 != 2",
];

for (const lang of ["ru", "uzc", "uz", "ky"] as const) {
  describe(`translateServerError [${lang}] — noma'lum matn xavfsiz`, () => {
    it("UUID ko'rsatilmaydi, jumla qoladi", () => {
      useLang.setState({ lang });
      const out = translateServerError(
        `Yangi noma'lum xato: hisob boshqa filialga tegishli (${UUID} != ${UUID2}).`,
      );
      expect(out).not.toMatch(UUID_RE);
      expect(out).toContain("hisob boshqa filialga tegishli");
      expect(out).not.toContain("( != )");
    });

    it("Traceback / SQL / psycopg / sqlalchemy -> umumiy lokalizatsiyalangan jumla", () => {
      useLang.setState({ lang });
      const outs = INTERNAL.map((t) => translateServerError(t));
      for (const [i, out] of outs.entries()) {
        expect(out.length).toBeGreaterThan(10);
        expect(out).not.toContain("Traceback");
        expect(out).not.toContain("psycopg");
        expect(out).not.toContain("sqlalchemy");
        expect(out).not.toContain("SQL");
        expect(out).not.toContain("relation");
        expect(out).not.toContain(INTERNAL[i].slice(0, 12));
      }
      // Bitta umumiy jumla — ichki matn qanday bo'lishidan qat'i nazar.
      expect(new Set(outs).size).toBe(1);
    });

    it("noma'lum `KOD_TOKEN:` prefiksi ko'rsatilmaydi", () => {
      useLang.setState({ lang });
      const out = translateServerError("SUPPLIER_IDEMPOTENCY_KEY_REUSED: kalit band, qaytadan yuboring");
      expect(out).not.toMatch(/^[A-Z][A-Z0-9_]+:/);
      expect(out).toContain("kalit band");
    });

    it("juda uzun matn kesiladi", () => {
      useLang.setState({ lang });
      const out = translateServerError("x".repeat(2000));
      expect(out.length).toBeLessThanOrEqual(401);
    });
  });
}

describe("translateServerError — lug'at avvalgidek", () => {
  it("statik kalit tarjima qilinadi (ru)", () => {
    useLang.setState({ lang: "ru" });
    expect(translateServerError("Sessiya tugadi — qayta kiring")).toBe("Сессия истекла — войдите снова");
  });
  it("dinamik qoida mijoz yuborgan qiymatni saqlaydi (ru)", () => {
    useLang.setState({ lang: "ru" });
    expect(translateServerError("Mahsulot topilmadi: SKU-77")).toBe("Товар не найден: SKU-77");
  });
  it("uz — asl matn, provayder -> biz", () => {
    useLang.setState({ lang: "uz" });
    expect(translateServerError("Provayder bilan bog'laning")).toBe("Biz bilan bog'laning");
  });
  it("bo'sh/matn bo'lmagan kirish o'zgarmaydi", () => {
    useLang.setState({ lang: "ru" });
    expect(translateServerError("")).toBe("");
  });
});
