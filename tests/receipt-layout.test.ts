import { describe, expect, it } from "vitest";
import {
  COLS, base64Encode, decAdd, normalizeTemplate, decCmp, decSub, docToText, layoutReceipt, provisionalSaleReceipt, sampleReceipt, strWidth,
  type Block, type ReceiptDTO, type ReceiptDoc, type ReceiptLang, type RenderOptions,
} from "@/receipt";
import {
  FULL_TEMPLATE, LOGO_64x16, dtoFormatProblems, expectGolden, framed, returnDto, saleDto, tpl,
} from "./__golden__/receipt/fixtures";

// Phase 5F F1: ReceiptDTO → bloklar. Golden'lar `tests/__golden__/receipt/layout-*.txt` da (ramkali matn:
// har satr `|...|` ichida — kenglik ko'rinadi). Asosiy invariant: HECH bir satr `cols / size` dan uzun emas.

const opts = (width_mm: 58 | 80, lang: ReceiptLang, extra: Partial<RenderOptions> = {}, dto?: ReceiptDTO): RenderOptions => ({
  width_mm, lang, template: dto?.template ?? FULL_TEMPLATE, ...extra,
});

function lineTexts(doc: ReceiptDoc): string[] {
  return doc.blocks.filter((b): b is Extract<Block, { t: "line" }> => b.t === "line").map((b) => b.text);
}

/** Har `line` bloki cols/size ga sig'adi, docToText satrlari ham cols dan oshmaydi. */
function assertFits(doc: ReceiptDoc) {
  for (const b of doc.blocks) {
    if (b.t !== "line") continue;
    const size = b.size === 2 ? 2 : 1;
    expect(strWidth(b.text), JSON.stringify(b.text)).toBeLessThanOrEqual(doc.cols / size);
    expect(b.text).not.toMatch(/\n/);
    expect(b.text).toBe(b.text.replace(/ +$/, "")); // oxirgi bo'shliq yo'q
  }
  for (const l of docToText(doc)) expect(strWidth(l), l).toBeLessThanOrEqual(doc.cols);
}

function golden(name: string, dto: ReceiptDTO, o: RenderOptions) {
  const doc = layoutReceipt(dto, o);
  assertFits(doc);
  const head =
    `# layoutReceipt kind=${dto.kind} width=${o.width_mm} cols=${doc.cols} lang=${o.lang}` +
    `${o.copy ? ` copy=${o.copy.kind}#${o.copy.no ?? ""}` : ""}\n# warnings: ${JSON.stringify(doc.warnings)}\n`;
  expectGolden(name, head + framed(docToText(doc), doc.cols) + "\n");
  return doc;
}

describe("layoutReceipt — golden (58/80, 4 til)", () => {
  it("to'liq sotuv 58 mm uz", () => {
    const d = golden("layout-sale-58-uz.txt", saleDto(), opts(58, "uz", { logo: LOGO_64x16 }));
    expect(d.cols).toBe(32);
    expect(d.warnings).toEqual([]);
  });
  it("to'liq sotuv 80 mm ru", () => {
    const d = golden("layout-sale-80-ru.txt", saleDto(), opts(80, "ru", { logo: LOGO_64x16 }));
    expect(d.cols).toBe(48);
    expect(d.warnings).toEqual([]);
  });
  it("to'liq sotuv 58 mm ky", () => golden("layout-sale-58-ky.txt", saleDto(), opts(58, "ky")));
  it("to'liq sotuv 80 mm uzc", () => golden("layout-sale-80-uzc.txt", saleDto(), opts(80, "uzc")));
  it("qaytarish 58 ru va 80 uz", () => {
    golden("layout-return-58-ru.txt", returnDto(), opts(58, "ru", {}, returnDto()));
    golden("layout-return-80-uz.txt", returnDto(), opts(80, "uz", {}, returnDto()));
  });
  it("nusxa (REPRINT #2) 80 uz", () =>
    golden("layout-reprint-80-uz.txt", saleDto(), opts(80, "uz", { copy: { kind: "REPRINT", no: 2 } })));
  it("oflayn vaqtinchalik chek 58 ru", () => {
    const dto = provisionalSaleReceipt({
      client_uuid: "5a0f9c3e-12ab-4cde-8f01-23456789abcd",
      lines: [
        { name: "Хлеб белый 500 г", qty: "2", unit_price: "4000", weighted: false, unit: "dona" },
        { name: "Помидоры", qty: String(0.1 + 0.252), unit_price: "12000", weighted: true, unit: "kg" },
      ],
      payments: [{ method: "cash", amount: "12224" }],
      given: "20000",
      change: "7776",
      total: "12224",
      store: { name: "Fayzan Market", branch_name: "Chilonzor filiali", address: null, phone: null, stir: null },
      cashier: "Dilnoza Karimova",
      issued_at_local: "19.09.2026 14:40",
      template: tpl(),
    });
    golden("layout-provisional-58-ru.txt", dto, opts(58, "ru", {}, dto));
  });
  it("TEST namuna (sale) 80 uz va uzun (120+ qator) 58 ru", () => {
    const s = sampleReceipt("sale", { name: "Fayzan Market" });
    golden("layout-test-sale-80-uz.txt", s, opts(80, "uz", {}, s));
    const l = sampleReceipt("long", { name: "Fayzan Market" });
    golden("layout-test-long-58-ru.txt", l, opts(58, "ru", {}, l));
  });
});

describe("layoutReceipt — tartib va mazmun", () => {
  it("bir xil kirish → bir xil natija (deterministik)", () => {
    const a = layoutReceipt(saleDto(), opts(58, "uz", { logo: LOGO_64x16 }));
    const b = layoutReceipt(saleDto(), opts(58, "uz", { logo: LOGO_64x16 }));
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it("bloklar tartibi: banner → logo → sarlavha → do'kon → '=' → ... → footer → shtrix-kod → QR → kesish", () => {
    const doc = layoutReceipt(saleDto(), opts(80, "uz", { logo: LOGO_64x16, copy: { kind: "REPRINT", no: 1 } }));
    const kinds = doc.blocks.map((b) => b.t);
    const texts = lineTexts(doc);
    expect(texts[0].trim()).toBe("*** NUSXA #1 ***");
    const iLogo = kinds.indexOf("logo");
    const iHeader = texts.findIndex((t) => t.includes("Har kuni yangi"));
    expect(iLogo).toBeGreaterThan(0);
    expect(doc.blocks.findIndex((b) => b.t === "line" && b.text.includes("Har kuni"))).toBeGreaterThan(iLogo);
    expect(iHeader).toBeGreaterThan(0);
    const store = doc.blocks.find((b) => b.t === "line" && b.text.includes("Fayzan Market")) as Extract<Block, { t: "line" }>;
    expect(store.bold).toBe(true);
    expect(store.size).toBe(2);
    const iBarcode = kinds.indexOf("barcode");
    const iQr = kinds.indexOf("qr");
    const iFooter = doc.blocks.findIndex((b) => b.t === "line" && b.text.includes("Xaridingiz uchun rahmat!"));
    expect(iFooter).toBeGreaterThan(0);
    expect(iBarcode).toBeGreaterThan(iFooter);
    expect(iQr).toBeGreaterThan(iBarcode);
    expect(kinds[kinds.length - 1]).toBe("cut");
  });

  it("do'kon nomi yarim kenglikka sig'masa — size 1 qalin, o'ralgan", () => {
    const dto = saleDto();
    dto.store.name = "Fayzan Market — Chilonzor savdo majmuasi 24/7";
    const doc = layoutReceipt(dto, opts(58, "uz"));
    const nameLines = doc.blocks.filter((b) => b.t === "line" && b.bold && /Fayzan|majmuasi/.test(b.text));
    expect(nameLines.length).toBeGreaterThan(1);
    for (const b of nameLines) expect((b as { size?: number }).size).toBeUndefined();
    assertFits(doc);
  });

  it("show_* bayroqlari: filial, STIR, kassir, kassa, xaridor, chegirma, to'lov tafsiloti o'chiriladi", () => {
    const off = tpl({
      show_branch: false, show_stir: false, show_cashier: false, show_till: false, show_customer: false,
      show_discount: false, show_payment_breakdown: false, show_barcode: false, qr_mode: "none", auto_cut: false,
    });
    const dto = saleDto();
    const text = lineTexts(layoutReceipt(dto, { width_mm: 80, lang: "uz", template: off })).join("\n");
    for (const s of ["Filial:", "STIR:", "Kassir:", "Kassa:", "Xaridor:", "Chegirma", "Chek chegirmasi"]) {
      expect(text).not.toContain(s);
    }
    // Aralash to'lov (2 ta) — show_payment_breakdown=false bo'lsa ham ko'rinadi (SPEC: yoki >1 to'lov).
    expect(text).toContain("To'lov:");
    const doc = layoutReceipt(dto, { width_mm: 80, lang: "uz", template: off });
    expect(doc.blocks.some((b) => b.t === "barcode" || b.t === "qr" || b.t === "cut")).toBe(false);
    // Chegirma yashirilganda qator sof summani, oraliq jami esa chegirmalardan keyingisini ko'rsatadi.
    expect(text).toMatch(/1,235 kg × 89 990,50 +106 138,27/);
    expect(text).toMatch(/Oraliq jami +173 112,27/);
  });

  it("bitta to'lov + show_payment_breakdown=false → to'lov bo'limi yo'q; true → naqd berildi/qaytim bilan", () => {
    const dto = saleDto();
    dto.payments = [{ method: "cash", amount: "173112.00", given: "200000.00", change: "26888.00" }];
    const hidden = lineTexts(layoutReceipt(dto, { width_mm: 58, lang: "ru", template: tpl({ show_payment_breakdown: false }) }));
    expect(hidden.join("\n")).not.toContain("Оплата");
    const shown = lineTexts(layoutReceipt(dto, { width_mm: 58, lang: "ru", template: tpl() })).join("\n");
    expect(shown).toMatch(/Наличные +173 112/);
    expect(shown).toMatch(/Внесено +200 000/);
    expect(shown).toMatch(/Сдача +26 888/);
  });

  it("qaytarish: summalar '-' (ASCII) bilan, qaytarilgan pul musbat, asl chek havolasi", () => {
    const doc = layoutReceipt(returnDto(), opts(80, "ru", {}, returnDto()));
    const text = lineTexts(doc).join("\n");
    expect(text).toContain("ЧЕК ВОЗВРАТА");
    expect(text).toMatch(/Исходный чек: #1288 +19.09.2026 14:32/);
    expect(text).toMatch(/-4 224\n/);
    expect(text).toMatch(/И Т О Г О|ИТОГО ВОЗВРАТ/);
    expect(text).toMatch(/-8 224 сом/);
    expect(text).toMatch(/Возвращено \(Карта\) +8 224/);
    expect(text).not.toContain("−"); // U+2212 kod sahifalarida yo'q
    expect(text).not.toContain("Оплата");
  });

  it("chekSIZ qaytarish (original=null) — havola satri yo'q, yiqilmaydi", () => {
    const dto = returnDto();
    dto.original = null;
    const text = lineTexts(layoutReceipt(dto, opts(58, "uz", {}, dto))).join("\n");
    expect(text).not.toContain("Asl chek");
    expect(text).toContain("QAYTARISH CHEKI");
  });

  it("bannerlar: TEST (boshida va oxirida), OFLAYN, NUSXA birga", () => {
    const t = sampleReceipt("sale");
    const tl = lineTexts(layoutReceipt(t, opts(58, "ru", {}, t)));
    expect(tl[0].trim()).toBe("*** TEST PRINT ***");
    expect(tl[1].trim()).toBe("не продажа");
    expect(tl[tl.length - 1].trim()).toBe("*** TEST PRINT ***");
    const p = provisionalSaleReceipt({
      client_uuid: "ABCDEF12-0000-4000-8000-000000000000", lines: [], payments: [], total: "0",
      store: { name: "X", branch_name: null, address: null, phone: null, stir: null }, cashier: null,
      issued_at_local: "", template: tpl(),
    });
    const pl = lineTexts(layoutReceipt(p, { width_mm: 80, lang: "uz", template: tpl(), copy: { kind: "REPRINT", no: 3 } }));
    expect(pl[0].trim()).toBe("*** NUSXA #3 ***");
    expect(pl[1].trim()).toBe("OFLAYN — VAQTINCHALIK CHEK");
    expect(pl.join("\n")).toContain("Chek OFFLINE-ABCDEF12");
  });

  it("ORIGINAL nusxada banner yo'q; REPRINT raqamsiz ham ishlaydi", () => {
    const a = lineTexts(layoutReceipt(saleDto(), opts(58, "uz", { copy: { kind: "ORIGINAL" } })));
    expect(a.join("\n")).not.toContain("NUSXA");
    const b = lineTexts(layoutReceipt(saleDto(), opts(58, "uz", { copy: { kind: "REPRINT" } })));
    expect(b[0].trim()).toBe("*** NUSXA ***");
  });

  it("logo faqat show_logo + yaroqli raster bilan; noto'g'ri raster → ogohlantirish, blok yo'q", () => {
    const on = layoutReceipt(saleDto(), opts(58, "uz", { logo: LOGO_64x16 }));
    expect(on.blocks.some((b) => b.t === "logo")).toBe(true);
    const off = layoutReceipt(saleDto(), { width_mm: 58, lang: "uz", template: tpl({ show_logo: false }), logo: LOGO_64x16 });
    expect(off.blocks.some((b) => b.t === "logo")).toBe(false);
    const bad = layoutReceipt(saleDto(), opts(58, "uz", { logo: { ...LOGO_64x16, height: 17 } }));
    expect(bad.blocks.some((b) => b.t === "logo")).toBe(false);
    expect(bad.warnings).toContain("logo_invalid");
    const wide = layoutReceipt(saleDto(), opts(58, "uz", {
      logo: { width: 512, height: 1, raster_b64: base64Encode(new Uint8Array(64)), png_data_uri: "" },
    }));
    expect(wide.warnings).toContain("logo_too_wide");
  });

  it("QR: shablon rejimi DTO turiga mos bo'lmasa chiqmaydi; buzilgan matritsa → qr_invalid", () => {
    const dto = saleDto();
    const other = layoutReceipt(dto, { width_mm: 80, lang: "uz", template: tpl({ qr_mode: "store_url" }) });
    expect(other.blocks.some((b) => b.t === "qr")).toBe(false);
    dto.qr = { ...dto.qr!, matrix: dto.qr!.matrix.slice(0, 20) };
    const broken = layoutReceipt(dto, opts(80, "uz"));
    expect(broken.warnings).toContain("qr_invalid");
    expect(broken.blocks.some((b) => b.t === "qr")).toBe(false);
  });

  it("shtrix-kod qog'ozdan keng (1 nuqtali modulda ham) — blok yo'q, payload matni qoladi", () => {
    const dto = saleDto();
    dto.barcode = { format: "CODE128", payload: "X-1", modules: "10".repeat(200) }; // 400 + 20 > 384
    const doc = layoutReceipt(dto, opts(58, "uz"));
    expect(doc.warnings).toContain("barcode_too_wide");
    expect(doc.blocks.some((b) => b.t === "barcode")).toBe(false);
    expect(lineTexts(doc).some((t) => t.trim() === "X-1")).toBe(true);
    expect(layoutReceipt(dto, opts(80, "uz")).blocks.some((b) => b.t === "barcode")).toBe(true); // 576 ga sig'adi
  });

  it("normalizeTemplate: eski/buzilgan shablon BUILTIN bilan to'ldiriladi", () => {
    const t = normalizeTemplate({
      footer: "F", width_mm: 70 as never, qr_mode: "evil" as never, lang: "de" as never, copies: 9,
      show_logo: "yes" as never,
    });
    expect(t).toMatchObject({ footer: "F", width_mm: 80, qr_mode: "none", lang: null, copies: 1, show_logo: true });
    expect(normalizeTemplate(null)).toEqual(tpl());
    expect(normalizeTemplate({ lang: "ky", copies: 3 })).toMatchObject({ lang: "ky", copies: 3 });
  });

  it("buzilgan summa chekni yiqitmaydi: '?' + bad_amount; invariant buzilsa totals_mismatch/payments_mismatch", () => {
    const dto = saleDto();
    dto.lines[0].total = "abc";
    dto.totals.total = "173113.00";
    const doc = layoutReceipt(dto, opts(58, "uz"));
    expect(doc.warnings).toEqual(expect.arrayContaining([
      "bad_amount:lines[0].total", "totals_mismatch", "payments_mismatch",
    ]));
    assertFits(doc);
    const ok = layoutReceipt(saleDto(), opts(58, "uz"));
    expect(ok.warnings).toEqual([]);
  });
});

describe("layoutReceipt — matn xavfsizligi va o'rash", () => {
  it("boshqaruv, bidi, zero-width belgilar olib tashlanadi; \\n qatorga bo'ladi", () => {
    const C = String.fromCharCode;
    const dto = saleDto();
    dto.store.name = `Fay${C(0x202e)}zan${C(0x200b)} ${C(0x1b)}${C(0x70)}${C(0)}Mar${C(0xfeff)}ket`;
    dto.lines[0].name = `Non${C(0x1b, 0x70, 0x00)} oq${C(0x1d, 0x56)}${C(0x10, 0x14)}${C(0x85)}${C(0x7f)}`;
    dto.template = { ...FULL_TEMPLATE, footer: `Rahmat!${C(0x2066)}\nYana keling${C(0x200e)}` };
    const doc = layoutReceipt(dto, { width_mm: 58, lang: "uz", template: dto.template });
    const all = lineTexts(doc).join("\n");
    const forbidden = Array.from(all).filter((ch) => {
      const cp = ch.codePointAt(0) as number;
      return (cp < 0x20 && cp !== 0x0a) || (cp >= 0x7f && cp <= 0x9f) || (cp >= 0x200b && cp <= 0x200f) ||
        (cp >= 0x202a && cp <= 0x202e) || (cp >= 0x2066 && cp <= 0x2069) || cp === 0xfeff;
    });
    expect(forbidden).toEqual([]);
    expect(all).toContain("Fayzan pMarket");
    expect(all).toContain("Nonp oqV");
    expect(all).toContain("Rahmat!");
    expect(all).toMatch(/\n +Yana keling/);
    assertFits(doc);
  });

  it("probelsiz juda uzun so'z qattiq bo'linadi, hech narsa kesilmaydi", () => {
    const dto = saleDto();
    const word = "СуперДлинноеНазваниеТовараБезПробеловКотороеНеПомещаетсяВСтрокуНикак";
    dto.lines[0].name = word;
    const doc = layoutReceipt(dto, opts(58, "ru"));
    assertFits(doc);
    const joined = lineTexts(doc).join("");
    expect(joined).toContain(word.slice(0, 32));
    expect(lineTexts(doc).slice(0, 60).join("")).toContain(word.slice(32, 64));
  });

  it("uzun qiymat bilan juftlik: chap matn o'raladi, summa o'ngda saqlanadi (58 mm, katta summa)", () => {
    const dto = saleDto();
    dto.lines[0] = {
      name: "Sanoat muzlatkichi", qty: "10.000", unit: "dona", weighted: false, unit_price: "98765432.10",
      gross: "987654321.00", discount: "0.00", total: "987654321.00",
    };
    const text = lineTexts(layoutReceipt(dto, opts(58, "uz"))).join("\n");
    expect(text).toContain("10 dona × 98 765 432,10");
    expect(text).toMatch(/ 987 654 321\n/);
  });

  it("keng belgi (emoji/CJK) 2 ustun hisoblanadi — satr baribir sig'adi", () => {
    const dto = saleDto();
    dto.lines[0].name = "茶".repeat(40) + " 🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎";
    assertFits(layoutReceipt(dto, opts(58, "uz")));
  });

  it("'…' '...' ga almashadi (ESC/POS kengligi HTML bilan bir xil)", () => {
    const dto = saleDto();
    dto.lines[0].name = "Kofe…";
    const text = lineTexts(layoutReceipt(dto, opts(80, "uz"))).join("\n");
    expect(text).toContain("Kofe...");
    expect(text).not.toContain("…");
  });
});

describe("Ko'p qatorli cheklar (30+, 100+)", () => {
  function manyLines(n: number): ReceiptDTO {
    const dto = saleDto();
    dto.lines = [];
    let sub = "0.00";
    for (let i = 0; i < n; i++) {
      const weighted = i % 3 === 0;
      const qty = weighted ? "0.001" : "1.000";
      const price = weighted ? "250000.00" : "12345.67";
      const gross = weighted ? "250.00" : "12345.67";
      dto.lines.push({
        name: `${["Кымыз жаңы өрүк", "Qoʻy goʻshti", "Молоко"][i % 3]} #${i + 1}`,
        qty, unit: weighted ? "kg" : "dona", weighted, unit_price: price, gross, discount: "0.00", total: gross,
      });
      sub = decAdd(sub, gross);
    }
    const total = sub.replace(/\.\d+$/, ".00");
    dto.totals = { currency: "UZS", subtotal: sub, line_discount: "0.00", doc_discount: "0.00", rounding: decSub(total, sub), total };
    dto.payments = [{ method: "card", amount: total, given: null, change: null }];
    return dto;
  }

  for (const n of [35, 120]) {
    it(`${n} qator: hammasi chiqadi, sig'adi, jami to'g'ri`, () => {
      const dto = manyLines(n);
      expect(dtoFormatProblems(dto)).toEqual([]);
      for (const w of [58, 80] as const) {
        const doc = layoutReceipt(dto, opts(w, "ky"));
        assertFits(doc);
        const text = lineTexts(doc).join("\n");
        for (let i = 1; i <= n; i++) expect(text).toContain(`#${i}`);
        expect(doc.warnings).toEqual([]);
        expect(text).toContain("0,001 kg × 250 000");
      }
    });
  }
});

describe("sampleReceipt va provisionalSaleReceipt", () => {
  it("namuna DTO'lari SPEC §3 formatida va invariantlarni saqlaydi", () => {
    for (const kind of ["sale", "mixed", "return", "long"] as const) {
      const d = sampleReceipt(kind, { name: "Do'kon" }, { show_barcode: true });
      expect(d.schema).toBe("binos.receipt.v1");
      expect(d.test).toBe(true);
      expect(d.doc.id).toBeNull();
      expect(d.doc.number).toBe("TEST");
      expect(dtoFormatProblems(d), kind).toEqual([]);
      const t = d.totals;
      expect(decCmp(decAdd(decSub(decSub(t.subtotal, t.line_discount), t.doc_discount), t.rounding), t.total)).toBe(0);
      expect(decCmp(t.total.replace(/\.\d+$/, ".00"), t.total)).toBe(0); // butun so'm
      if (d.kind === "SALE") {
        let s = "0";
        for (const p of d.payments) s = decAdd(s, p.amount);
        expect(decCmp(s, t.total), kind).toBe(0);
        expect(d.barcode?.payload).toBe(d.doc.uid);
      } else {
        expect(d.refund?.amount).toBe(t.total);
        expect(d.payments).toEqual([]);
      }
      expect(layoutReceipt(d, opts(58, "uz", {}, d)).warnings).toEqual([]);
    }
    const long = sampleReceipt("long");
    expect(long.lines.length).toBeGreaterThanOrEqual(120);
    expect(long.lines.some((l) => l.qty === "0.001" && l.weighted)).toBe(true);
    expect(long.lines.some((l) => decCmp(l.discount, "0") > 0)).toBe(true);
    expect(new Set(long.payments.map((p) => p.method)).size).toBeGreaterThan(1);
  });

  it("namuna shablon qisman berilsa BUILTIN bilan to'ldiriladi; show_customer=false → customer null", () => {
    const d = sampleReceipt("sale", undefined, { width_mm: 58 });
    expect(d.template.width_mm).toBe(58);
    expect(d.template.show_logo).toBe(true);
    expect(d.customer).toBeNull();
    expect(d.barcode).toBeNull(); // show_barcode standart false
    expect(sampleReceipt("sale", undefined, { show_customer: true }).customer).not.toBeNull();
  });

  it("vaqtinchalik chek: OFFLINE raqam, float qoldig'i tozalanadi, yaxlitlash = jami − Σ", () => {
    const d = provisionalSaleReceipt({
      client_uuid: "5a0f9c3e-12ab-4cde-8f01-23456789abcd",
      lines: [
        { name: "Pomidor", qty: String(0.1 + 0.252), unit_price: "12000", weighted: true, unit: "kg" },
        { name: "Olma", qty: "1.235", unit_price: "18990", weighted: true },
      ],
      payments: [{ method: "cash", amount: "27677" }],
      given: "30000",
      change: "2323",
      total: "27677",
      store: { name: "S", branch_name: null, address: null, phone: null, stir: null },
      cashier: "K",
      issued_at_local: "19.09.2026 14:40",
      template: tpl(),
    });
    expect(d.provisional).toBe(true);
    expect(d.test).toBe(false);
    expect(d.doc).toMatchObject({ id: null, uid: null, number: "OFFLINE-5A0F9C3E", is_offline: true });
    expect(d.lines[0]).toMatchObject({ qty: "0.352", gross: "4224.00", total: "4224.00", discount: "0.00" });
    expect(d.lines[1]).toMatchObject({ qty: "1.235", gross: "23452.65", unit: null });
    expect(d.totals).toMatchObject({ subtotal: "27676.65", total: "27677.00", rounding: "0.35" });
    expect(d.payments).toEqual([{ method: "cash", amount: "27677.00", given: "30000.00", change: "2323.00" }]);
    expect(dtoFormatProblems(d)).toEqual([]);
    expect(() =>
      provisionalSaleReceipt({
        client_uuid: "x", lines: [{ name: "a", qty: "abc", unit_price: "1", weighted: false }], payments: [],
        total: "1", store: d.store, cashier: null, issued_at_local: "", template: tpl(),
      }),
    ).toThrow(/decimal/);
  });

  it("aralash to'lovda berildi/qaytim bog'lanmaydi (server ham saqlamaydi)", () => {
    const d = provisionalSaleReceipt({
      client_uuid: "00000000-0000-4000-8000-000000000001",
      lines: [{ name: "A", qty: "1", unit_price: "1000", weighted: false }],
      payments: [{ method: "cash", amount: "500" }, { method: "card", amount: "500" }],
      given: "1000", change: "500", total: "1000",
      store: { name: "S", branch_name: null, address: null, phone: null, stir: null },
      cashier: null, issued_at_local: "", template: tpl(),
    });
    expect(d.payments.every((p) => p.given === null && p.change === null)).toBe(true);
  });
});

describe("COLS", () => {
  it("58 → 32, 80 → 48", () => {
    expect(COLS[58]).toBe(32);
    expect(COLS[80]).toBe(48);
  });
});
