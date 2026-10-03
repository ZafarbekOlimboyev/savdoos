import { beforeEach, describe, expect, it } from "vitest";
import { currencyLabel, layoutReceipt } from "@/receipt";
import type { ReceiptDTO, ReceiptLang } from "@/receipt";
import { fmt } from "@/lib/format";
import { useAuth } from "@/store/auth";
import { useLang } from "@/store/lang";
import { saleDto } from "./__golden__/receipt/fixtures";

// ─── VALYUTA KONTRAKTI ───────────────────────────────────────────────────────
//
// Valyuta va til — IKKI BOSHQA tushuncha:
//   · `company.currency` (ISO-4217) pul BIRLIGINI belgilaydi;
//   · UI tili faqat MATNNI tarjima qiladi.
//
// NUQSON SHU EDI: yorliq faqat tildan chiqarilardi (`CUR[lang]` / `CURRENCY[lang]`), ya'ni
// o'zbekcha interfeys KGS tenantda ham "so'm" ko'rsatardi. Pul birligini til hal qila OLMAYDI.
// Quyida har bir pul yo'li uchun shu kontrakt qadaladi, plus ATAYLAB fallback va NEGATIV nazorat.

const LANGS: ReceiptLang[] = ["uz", "uzc", "ru", "ky"];

// `Intl.NumberFormat("ru-RU")` ming ajratgichi sifatida NBSP (U+00A0) beradi — aniq satr
// solishtirishda uni oddiy probelga keltiramiz (ko'rinmas belgi tufayli yolg'on yiqilish bo'lmasin).
const norm = (s: string) => s.replace(/ /g, " ");
const UZ_MARKS = ["so'm", "сўм"]; // KGS'da bularning BIRORTASI chiqmasligi SHART

/** Login javobi bergan xodim — `fmt()` valyutani SHU yerdan oladi. */
function signIn(currency: string | null | undefined) {
  useAuth.setState({
    token: "tok",
    employee: {
      id: "emp-1", full_name: "Dilnoza", role_code: "kassir", role_name: "Kassir",
      status: "active", permissions: ["kassa.sell"], company_currency: currency,
    },
  } as never);
}

/** DTO dagi valyutani almashtirib chek matn qatorlarini qaytaradi. */
function receiptLines(currency: string | null | undefined, lang: ReceiptLang): string[] {
  const dto = saleDto() as ReceiptDTO;
  const d = { ...dto, totals: { ...dto.totals, currency: currency as string } };
  const doc = layoutReceipt(d, { width_mm: 80, lang, template: { header: null, footer: null } as never });
  return doc.blocks.filter((b): b is Extract<typeof b, { t: "line" }> => b.t === "line").map((b) => b.text);
}

beforeEach(() => {
  useLang.getState().set("ru");
  signIn("KGS");
});

// ─── 1. UMUMIY FORMATLOVCHI (POS narxi shu funksiyadan chiqadi) ──────────────
describe("umumiy formatlovchi fmt() — valyuta TILdan emas, do'kondan", () => {
  for (const lang of LANGS) {
    it(`KGS + UI ${lang} → "сом"`, () => {
      signIn("KGS");
      useLang.getState().set(lang);
      const out = fmt(12345);
      expect(out).toContain("сом");
      for (const m of UZ_MARKS) expect(out).not.toContain(m);
    });
  }

  it("KGS + uz: son formati o'zgarmaydi, faqat birlik", () => {
    signIn("KGS");
    useLang.getState().set("uz");
    expect(norm(fmt(12345))).toBe("12 345 сом");
  });

  it("UZS tenant: bugungi tilga-bog'liq xulq AYNAN saqlanadi (jim qayta talqin YO'Q)", () => {
    signIn("UZS");
    useLang.getState().set("uz");
    expect(norm(fmt(1000))).toBe("1 000 so'm");
    useLang.getState().set("uzc");
    expect(norm(fmt(1000))).toBe("1 000 сўм");
    useLang.getState().set("ru");
    expect(norm(fmt(1000))).toBe("1 000 сом");
  });
});

// ─── 2. POS NARX BIRLIGI (POSKassa `fmt(0)` dan birlikni ajratadi) ───────────
describe("POS narx birligi", () => {
  // POSKassa.tsx: `const curUnit = fmt(0).replace(/[0-9\s.,]/g, "")` — tarozi dialogi va
  // "so'm/kg" yorliqlari shu birlikni ishlatadi, ya'ni u ham kontraktga bo'ysunishi SHART.
  const unit = () => fmt(0).replace(/[0-9\s.,]/g, "");

  for (const lang of LANGS) {
    it(`KGS + UI ${lang} → birlik "сом"`, () => {
      signIn("KGS");
      useLang.getState().set(lang);
      expect(unit()).toBe("сом");
    });
  }
});

// ─── 3. CHEK (server DTO dagi totals.currency hal qiladi) ────────────────────
describe("chek — valyuta DTO dan, UI tilidan emas", () => {
  for (const lang of LANGS) {
    it(`KGS + chek tili ${lang} → "сом", o'zbek belgisi YO'Q`, () => {
      const lines = receiptLines("KGS", lang);
      const blob = lines.join("\n");
      expect(blob).toContain("сом");
      for (const m of UZ_MARKS) expect(blob).not.toContain(m);
    });
  }

  it("UZS + chek tili uz → \"so'm\" (mavjud kontrakt buzilmaydi)", () => {
    expect(receiptLines("UZS", "uz").join("\n")).toContain("so'm");
  });
});

// ─── 4. FALLBACK — ATAYLAB va SINALADI ──────────────────────────────────────
describe("fallback: valyuta yo'q / noma'lum", () => {
  it("fmt(): valyuta yo'q bo'lsa eski tilga-asoslangan yorliq (eski server, regressiya yo'q)", () => {
    for (const v of [null, undefined, ""] as const) {
      signIn(v);
      useLang.getState().set("uz");
      expect(norm(fmt(1000))).toBe("1 000 so'm");
      useLang.getState().set("ky");
      expect(norm(fmt(1000))).toBe("1 000 сом");
    }
  });

  it("chek: DTO da valyuta yo'q bo'lsa ham eski yorliqqa qaytadi", () => {
    expect(receiptLines("", "uz").join("\n")).toContain("so'm");
  });

  it("noma'lum ISO kod: yorliq O'YLAB TOPILMAYDI, kodning o'zi chiqadi", () => {
    signIn("EUR");
    useLang.getState().set("uz");
    expect(norm(fmt(1000))).toBe("1 000 EUR");
    expect(currencyLabel("EUR", "ru")).toBe("EUR");
  });

  it("kod normallashadi: bo'shliq va kichik registr", () => {
    expect(currencyLabel(" kgs ", "uz")).toBe("сом");
    expect(currencyLabel("uzs", "uz")).toBe("so'm");
  });
});

// ─── 5. NEGATIV NAZORAT ─────────────────────────────────────────────────────
describe("negativ nazorat — ESKI tilga-asoslangan amalga oshirish", () => {
  // Nuqsonli algoritmning AYNAN o'zi: yorliq faqat tildan. Agar u hali ham ishlatilayotgan
  // bo'lsa, quyidagi "KGS + uz" holati yiqiladi — ya'ni bu sinov nuqsonni TUTADI.
  const OLD_CUR: Record<string, string> = { uz: "so'm", uzc: "сўм", ru: "сом", ky: "сом" };
  const oldLabel = (_currency: string, lang: string) => OLD_CUR[lang] ?? "сом";

  it("eski amalga oshirish KGS + uz da YIQILADI (shu bois kontrakt kerak edi)", () => {
    expect(oldLabel("KGS", "uz")).toBe("so'm");          // nuqson: til pul birligini bosib ketdi
    expect(oldLabel("KGS", "uz")).not.toBe("сом");       // kontrakt talabi BAJARILMAYDI
    expect(currencyLabel("KGS", "uz")).toBe("сом");      // yangi amalga oshirish esa BAJARADI
  });

  it("eski amalga oshirish uzc da ham yiqiladi", () => {
    expect(oldLabel("KGS", "uzc")).toBe("сўм");
    expect(currencyLabel("KGS", "uzc")).toBe("сом");
  });

  it("eski amalga oshirish ru/ky da TASODIFAN to'g'ri bo'lardi — shu bois nuqson yashiringan", () => {
    for (const lang of ["ru", "ky"]) {
      expect(oldLabel("KGS", lang)).toBe("сом");
      expect(currencyLabel("KGS", lang as ReceiptLang)).toBe("сом");
    }
  });
});
