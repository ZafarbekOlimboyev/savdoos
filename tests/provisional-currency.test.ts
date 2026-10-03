import fs from "node:fs";
import path from "node:path";
import { beforeEach, describe, expect, it } from "vitest";
import { BUILTIN_TEMPLATE, currencyLabel, layoutReceipt, provisionalSaleReceipt, sampleReceipt } from "@/receipt";
import type { ProvisionalInput, ReceiptDTO, ReceiptLang } from "@/receipt";
import { currencyUnit } from "@/lib/format";
import { translate } from "@/lib/i18n";
import { useAuth } from "@/store/auth";
import { useLang } from "@/store/lang";

// ─── VAQTINCHALIK (OFLAYN) CHEK VALYUTASI ────────────────────────────────────
//
// NUQSON SHU EDI: `receipt/provisional.ts` da `currency: "UZS"` QATTIQ kodlangan edi.
// Oqibati KGS do'konda:
//   · OFLAYN sotuvning vaqtinchalik cheki `so'm` chiqarardi;
//   · chek marshruti YO'Q eski serverdagi ONLAYN zaxira chek ham (`legacyReceipt`) `so'm`.
// Server tuzatishi bunga TA'SIR QILMAYDI — chek klientda quriladi.
//
// KONTRAKT: valyuta quruvchiga KIRISH sifatida beriladi (`receipt/` mustaqil modul —
// `tests/receipt-purity.test.ts` har importni `^\./[a-z0-9]+$` ga cheklaydi, ya'ni u
// `lib/` dagi do'kon valyutasini O'ZI o'qiy olmaydi). Kalit MAJBURIY: tushirib
// qoldirilsa `tsc` yiqiladi. Bilmaslik `""` bilan ifodalanadi — `"UZS"` O'YLAB TOPILMAYDI.

const LANGS: ReceiptLang[] = ["uz", "uzc", "ru", "ky"];
const UZ_MARKS = ["so'm", "сўм"]; // KGS'da bularning BIRORTASI chiqmasligi SHART

const SHARED = path.resolve(__dirname, "..", "packages", "shared", "src");

/** Login javobi bergan xodim — POS do'kon valyutasini SHU yerdan oladi. */
function signIn(currency: string | null | undefined) {
  useAuth.setState({
    token: "tok",
    employee: {
      id: "emp-1", full_name: "Dilnoza", role_code: "kassir", role_name: "Kassir",
      status: "active", permissions: ["kassa.sell"], company_currency: currency,
    },
  } as never);
}

function input(currency: string | null): ProvisionalInput {
  return {
    client_uuid: "5a0f9c3e-12ab-4cde-8f01-23456789abcd",
    currency,
    lines: [{ name: "Non", qty: "2", unit_price: "4000", weighted: false, unit: "dona" }],
    payments: [{ method: "cash", amount: "8000" }],
    given: "10000",
    change: "2000",
    total: "8000",
    store: { name: "Fayzan", branch_name: "Markaz", address: null, phone: null, stir: null },
    cashier: "Kassir 1",
    issued_at_local: "26.09.2026 18:30",
    template: BUILTIN_TEMPLATE,
  };
}

/** Vaqtinchalik chekni chiqarib, matn qatorlarini qaytaradi. */
function lines(dto: ReceiptDTO, lang: ReceiptLang): string[] {
  const doc = layoutReceipt(dto, {
    width_mm: 80, lang, template: { header: null, footer: null } as never,
  });
  return doc.blocks.filter((b): b is Extract<typeof b, { t: "line" }> => b.t === "line").map((b) => b.text);
}

beforeEach(() => {
  useLang.setState({ lang: "uz" } as never);
  signIn(undefined);
});

describe("vaqtinchalik chek — valyuta KIRISHdan keladi", () => {
  it("KGS: DTO kodi KGS, chop etilgan birlik «сом» — HAR TILDA", () => {
    const dto = provisionalSaleReceipt(input("KGS"));
    expect(dto.totals.currency).toBe("KGS");
    expect(dto.provisional).toBe(true);
    for (const lang of LANGS) {
      const txt = lines(dto, lang).join("\n");
      expect(txt, lang).toContain("сом");
      for (const bad of UZ_MARKS) expect(txt, `${lang}: ${bad}`).not.toContain(bad);
    }
  });

  it("UZS: bugungi xulq AYNAN saqlanadi (uz → so'm, ru/ky → сом)", () => {
    const dto = provisionalSaleReceipt(input("UZS"));
    expect(dto.totals.currency).toBe("UZS");
    expect(lines(dto, "uz").join("\n")).toContain("so'm");
    expect(lines(dto, "uzc").join("\n")).toContain("сўм");
    expect(lines(dto, "ru").join("\n")).toContain("сом");
  });

  it("HUJJAT valyutasi joriy do'kon valyutasidan USTUN", () => {
    signIn("UZS");                                   // do'kon hozir UZS deydi
    const dto = provisionalSaleReceipt(input("KGS")); // hujjat esa KGS da yozilgan
    expect(dto.totals.currency).toBe("KGS");
    expect(lines(dto, "uz").join("\n")).toContain("сом");

    signIn("KGS");                                   // teskarisi ham
    expect(provisionalSaleReceipt(input("UZS")).totals.currency).toBe("UZS");
  });

  it("ESKI SERVER zaxirasi: valyuta yo'q → kod BO'SH, yorliq eski tilga-asoslangan", () => {
    // Eski server `employee.company_currency` ni bermaydi → chaqiruvchi `null` beradi.
    // Chekda "UZS" DA'VO QILINMAYDI; yorliq esa ilgarigidek tildan chiqadi (regressiya yo'q).
    const dto = provisionalSaleReceipt(input(null));
    expect(dto.totals.currency).toBe("");
    expect(lines(dto, "uz").join("\n")).toContain("so'm");
    expect(lines(dto, "ru").join("\n")).toContain("сом");
    expect(dto.totals.currency).not.toBe("UZS");
  });

  it("kod normallashadi; NOMA'LUM kod — kodning O'ZI chiqadi", () => {
    expect(provisionalSaleReceipt(input(" kgs ")).totals.currency).toBe("KGS");
    expect(lines(provisionalSaleReceipt(input(" kgs ")), "uz").join("\n")).toContain("сом");
    const eur = provisionalSaleReceipt(input("eur"));
    expect(eur.totals.currency).toBe("EUR");
    expect(lines(eur, "uz").join("\n")).toContain("EUR");
  });

  it("valyuta faqat TOTALS ga tegadi — summalar va tuzilma o'zgarmaydi", () => {
    const a = provisionalSaleReceipt(input("KGS"));
    const b = provisionalSaleReceipt(input("UZS"));
    expect({ ...a.totals, currency: null }).toEqual({ ...b.totals, currency: null });
    expect(a.lines).toEqual(b.lines);
    expect(a.payments).toEqual(b.payments);
    expect(a.doc).toEqual(b.doc);
  });
});

// ─── NAMUNA / SINOV CHEKI ───────────────────────────────────────────────────
//
// Server namunasi (`services/receipt/sample.py:96`) `company.currency` ni o'qiydi, ya'ni
// ONLAYN namuna to'g'ri edi. Mahalliy ZAXIRA (server yo'q yoki `scope=company` ga 403)
// esa `currency: "UZS"` qattiq kodlagan edi — `lib/printing.ts` sinov cheki va
// `ReceiptSettings` ko'rinishi KGS do'konda `so'm` chiqarardi.
describe("namuna cheki — do'kon valyutasini oladi", () => {
  it("KGS: birlik «сом», hech bir tilda «so'm» YO'Q", () => {
    const dto = sampleReceipt("sale", undefined, undefined, "KGS");
    expect(dto.totals.currency).toBe("KGS");
    expect(dto.test).toBe(true);
    for (const lang of LANGS) {
      const txt = lines(dto, lang).join(" ");
      expect(txt, lang).toContain("сом");
      for (const bad of UZ_MARKS) expect(txt, `${lang}: ${bad}`).not.toContain(bad);
    }
  });

  it("UZS va NOMA'LUM kod; har SampleKind uchun", () => {
    expect(sampleReceipt("sale", undefined, undefined, "UZS").totals.currency).toBe("UZS");
    expect(lines(sampleReceipt("sale", undefined, undefined, "UZS"), "uz").join(" ")).toContain("so'm");
    expect(sampleReceipt("sale", undefined, undefined, " eur ").totals.currency).toBe("EUR");
    for (const k of ["sale", "mixed", "return", "long"] as const) {
      expect(sampleReceipt(k, undefined, undefined, "KGS").totals.currency, k).toBe("KGS");
    }
  });

  it("valyuta BERILMASA — «UZS» DA'VO QILINMAYDI, eski yorliqqa tushadi", () => {
    const dto = sampleReceipt("sale");
    expect(dto.totals.currency).toBe("");
    expect(dto.totals.currency).not.toBe("UZS");
    expect(lines(dto, "uz").join(" ")).toContain("so'm");   // eski ko'rinish saqlanadi
    expect(lines(dto, "ru").join(" ")).toContain("сом");
  });

  it("valyuta faqat TOTALS ga tegadi — namunaning qolgani o'zgarmaydi", () => {
    const a = sampleReceipt("mixed", undefined, undefined, "KGS");
    const b = sampleReceipt("mixed", undefined, undefined, "UZS");
    expect({ ...a.totals, currency: null }).toEqual({ ...b.totals, currency: null });
    expect(a.lines).toEqual(b.lines);
    expect(a.payments).toEqual(b.payments);
  });
});

// ─── TUZILMA DARVOZASI: simlash bir kun jim uzilib qolmasin ──────────────────
describe("simlash manbada qadalgan", () => {
  it("provisional.ts da QATTIQ kodlangan valyuta YO'Q va kalit MAJBURIY", () => {
    const src = fs.readFileSync(path.join(SHARED, "receipt", "provisional.ts"), "utf8");
    const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    expect(code).not.toMatch(/currency:\s*"[A-Z]{3}"/);
    expect(code).toContain("currency: normalizeCurrency(input.currency)");
    // `currency?:` bo'lsa chaqiruvchi uni tushirib qoldira olardi — fail-closed buziladi.
    expect(code).toMatch(/\n\s*currency:\s*string \| null;/);
    expect(code).not.toMatch(/\n\s*currency\?:/);
  });

  it("namuna cheki ikki chaqiruvchida ham valyuta bilan chaqiriladi", () => {
    const pr = fs.readFileSync(path.join(SHARED, "lib", "printing.ts"), "utf8");
    const rs = fs.readFileSync(path.join(SHARED, "screens", "ReceiptSettings.tsx"), "utf8");
    expect(pr).toContain("companyCurrency() ?? null");
    expect(rs).toContain("companyCurrency() ?? null");
    // `currency` IXTIYORIY pozitsion parametr (majburiysi ixtiyoriylardan keyin kela
    // olmaydi), shu bois `tsc` tushib qolgan chaqiruvchini TUTMAYDI. Xavfsizlik
    // STANDARTDA: berilmasa `""` (NOMA'LUM), hech qachon "UZS". Darvoza esa yangi
    // chaqiruvchi paydo bo'lsa YIQILADI — u ham valyuta uzatishi kerak.
    const callers = ["lib/printing.ts", "screens/ReceiptSettings.tsx"];
    const found: string[] = [];
    for (const f of fs.readdirSync(path.join(SHARED, "lib")).map((x) => `lib/${x}`)
      .concat(fs.readdirSync(path.join(SHARED, "screens")).map((x) => `screens/${x}`))) {
      if (!/\.tsx?$/.test(f)) continue;
      if (fs.readFileSync(path.join(SHARED, f), "utf8").includes("sampleReceipt(")) found.push(f);
    }
    expect(found.sort()).toEqual(callers.sort());
    const sp = fs.readFileSync(path.join(SHARED, "receipt", "sample.ts"), "utf8");
    const code = sp.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    expect(code).not.toMatch(/currency:\s*"[A-Z]{3}"/);
    expect(code).toContain("normalizeCurrency(currency)");
  });

  it("POSKassa suratni sotuv paytida oladi va chekka SURATDAN beradi", () => {
    const src = fs.readFileSync(path.join(SHARED, "screens", "POSKassa.tsx"), "utf8");
    expect(src).toContain("currency: companyCurrency() ?? null");  // surat olish
    expect(src).toContain("currency: s.currency");                 // chekka surat beriladi
    expect(src).toMatch(/import \{[^}]*companyCurrency[^}]*\} from "@\/lib\/format"/);
  });
});

// ─── WEB PROZASI: birlik son yonida ─────────────────────────────────────────
//
// `00f77c3` MOBIL tomondagi ikki gapni `{cur}` ga o'tkazdi; web egizagi
// (`lib/i18n.ts`) tegilmagan edi. `prod.zeroPriceConfirm` SON yonida birlikni
// yozib qo'ygan edi ("0 so'm"), ya'ni birlikni TIL hal qilardi — va ruscha qiymati
// `сум` edi, bu HECH BIR yorliq jadvalida yo'q (ru UZS yorlig'i `сом`).
describe("web prozasi: `prod.zeroPriceConfirm` birligi valyutadan", () => {
  const LANGS4 = ["uz", "uzc", "ru", "ky"] as const;

  it("har tilda {cur} bor va birlik YOZIB QO'YILMAGAN", () => {
    const src = fs.readFileSync(path.join(SHARED, "lib", "i18n.ts"), "utf8");
    const rows = [...src.matchAll(/"prod\.zeroPriceConfirm":\s*"([^"]+)"/g)].map((m) => m[1]);
    expect(rows.length).toBe(LANGS4.length);
    for (const r of rows) {
      expect(r, r).toContain("{cur}");
      for (const bad of ["so'm", "сўм", "сом", "сум"]) expect(r, `${bad} :: ${r}`).not.toContain(bad);
    }
  });

  it("KGS do'konda «сом», UZS do'konda tilga mos yorliq", () => {
    for (const lang of LANGS4) {
      useLang.setState({ lang } as never);
      signIn("KGS");
      expect(translate(lang, "prod.zeroPriceConfirm", { cur: currencyUnit() }), lang).toContain("сом");
      signIn("UZS");
      expect(translate(lang, "prod.zeroPriceConfirm", { cur: currencyUnit() }), lang)
        .toContain(currencyLabel("UZS", lang));
    }
  });

  it("chaqiruv joyi {cur} ni UZATADI", () => {
    const src = fs.readFileSync(path.join(SHARED, "screens", "Products.tsx"), "utf8");
    expect(src).toContain('t("prod.zeroPriceConfirm", { cur: currencyUnit() })');
  });
});

// ─── NEGATIV NAZORAT ────────────────────────────────────────────────────────
describe("NEGATIV NAZORAT — eski amalga oshirish nuqsonni qaytaradi", () => {
  /** ESKI (nuqsonli) quruvchi: valyuta kirishga QARAMASDAN doim "UZS". */
  function oldHardcoded(dto: ReceiptDTO): ReceiptDTO {
    return { ...dto, totals: { ...dto.totals, currency: "UZS" } };
  }

  it("qattiq kodlangan UZS KGS do'konda YIQILADI", () => {
    const fixed = provisionalSaleReceipt(input("KGS"));
    const old = oldHardcoded(fixed);

    expect(old.totals.currency).toBe("UZS");
    expect(lines(old, "uz").join("\n")).toContain("so'm");       // nuqson aynan shu
    expect(lines(old, "uz").join("\n")).not.toContain("сом");
    // Tuzatilgani esa to'g'ri:
    expect(lines(fixed, "uz").join("\n")).toContain("сом");
    expect(old.totals.currency).not.toBe(fixed.totals.currency);
  });

  it("UZS do'konda ikki amalga oshirish AYNI — tuzatish TOR", () => {
    const fixed = provisionalSaleReceipt(input("UZS"));
    expect(oldHardcoded(fixed)).toEqual(fixed);
    for (const lang of LANGS) {
      expect(lines(oldHardcoded(fixed), lang)).toEqual(lines(fixed, lang));
    }
  });

  it("yorliq jadvali bitta: provisional kodi currencyLabel bilan IZCHIL", () => {
    for (const lang of LANGS) {
      const dto = provisionalSaleReceipt(input("KGS"));
      expect(lines(dto, lang).join("\n")).toContain(currencyLabel(dto.totals.currency, lang));
    }
  });
});
