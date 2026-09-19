import { describe, expect, it } from "vitest";
import {
  COLS, MAX_TEMPLATE_LINES, base64Encode, charWidth, cleanText, decAdd, normalizeTemplate, decCmp, decSub, docToText, encodeEscPos,
  encodeText, labelsFor, layoutReceipt, parseEscPos, profileFor, provisionalSaleReceipt, renderHtml, sampleReceipt,
  strWidth, wrapText, type Block, type ReceiptDTO, type ReceiptDoc, type ReceiptLang, type RenderOptions,
} from "@/receipt";
import {
  FULL_TEMPLATE, LOGO_64x16, dtoFormatProblems, expectGolden, framed, returnDto, saleDto, tpl,
} from "./__golden__/receipt/fixtures";
import { validateEscPosRequest } from "@/print/node/validate";

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
    for (const s of ["Filial:", "STIR:", "Kassir:", "Kassa:", "Xaridor:", "Chegirma"]) {
      expect(text).not.toContain(s);
    }
    // Aralash to'lov (2 ta) — show_payment_breakdown=false bo'lsa ham ko'rinadi (SPEC: yoki >1 to'lov).
    expect(text).toContain("To'lov:");
    const doc = layoutReceipt(dto, { width_mm: 80, lang: "uz", template: off });
    expect(doc.blocks.some((b) => b.t === "barcode" || b.t === "qr" || b.t === "cut")).toBe(false);
    // Qator chegirmasi yashirilganda qator sof summani, oraliq jami — sof qatorlar yig'indisini ko'rsatadi;
    // chek (sarlavha) chegirmasi hech bir qatorga tegishli emas — show_discount=false da ham ko'rinadi.
    expect(text).toMatch(/1,235 kg × 89 990,50 +106 138,27/);
    expect(text).toMatch(/Oraliq jami +174 112,27/);
    expect(text).toMatch(/Chek chegirmasi +-1 000/);
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

// ── Chekdagi arifmetika: bosilgan raqamlar o'zi qo'shilsin (DTO invarianti yetarli emas) ─────────────
const AMT = /(?:^|\s{2,})([+-]?\d{1,3}(?: \d{3})*(?:,\d{2})?)$/;
const cents = (v: string): number => {
  const neg = v.startsWith("-");
  const [w, f = "0"] = v.replace(/^[+-]/, "").replace(/ /g, "").split(",");
  const n = Number(w) * 100 + Number(f.padEnd(2, "0"));
  return neg ? -n : n;
};

/** Bosilgan chekdan: qator summalari (qator chegirmasi juftliklarisiz), oraliq jami, tuzatishlar, JAMI. */
function printedSums(doc: ReceiptDoc, lang: ReceiptLang) {
  const L = labelsFor(lang);
  let rules = 0;
  const items: number[] = [];
  const adj: number[] = [];
  let subtotal: number | null = null;
  let total: number | null = null;
  for (const b of doc.blocks) {
    if (b.t === "rule") { rules++; continue; }
    if (b.t !== "line") continue;
    const t = b.text.trim();
    if (rules === 2) {
      if (t.startsWith(L.lineDiscount)) continue;
      const m = AMT.exec(b.text);
      if (m) items.push(cents(m[1]));
    } else if (rules === 3 && total === null) {
      if (t.startsWith(L.total)) {
        total = cents(/([+-]?\d{1,3}(?: \d{3})*(?:,\d{2})?) \S+$/.exec(t)![1]);
        continue;
      }
      const m = AMT.exec(b.text);
      if (!m) continue;
      if (t.startsWith(L.subtotal)) subtotal = cents(m[1]);
      else adj.push(cents(m[1]));
    }
  }
  return { items, subtotal, adj, total };
}

function saleVariant(kind: "full" | "noRounding" | "docOnly" | "none"): ReceiptDTO {
  const dto = saleDto();
  if (kind === "noRounding") dto.totals = { ...dto.totals, doc_discount: "1000.27", rounding: "0.00" };
  if (kind === "docOnly" || kind === "none") {
    dto.lines[2] = { ...dto.lines[2], discount: "0.00", total: dto.lines[2].gross };
    const doc = kind === "docOnly" ? "1000.27" : "0.00";
    const rounding = kind === "docOnly" ? "0.00" : "-0.27";
    const total = kind === "docOnly" ? "178112.00" : "179112.00";
    dto.totals = { ...dto.totals, line_discount: "0.00", doc_discount: doc, rounding, total };
  }
  dto.payments = [{ method: "card", amount: dto.totals.total, given: null, change: null }];
  return dto;
}

describe("layoutReceipt — bosilgan raqamlar qo'shiladi (show_discount x chegirma x yaxlitlash)", () => {
  it("qatorlar = oraliq jami; oraliq − chegirmalar ± yaxlitlash = JAMI (58/80, chegirma ko'rinsa ham, yashirilsa ham)", () => {
    for (const kind of ["full", "noRounding", "docOnly", "none"] as const) {
      for (const show_discount of [true, false]) {
        for (const w of [58, 80] as const) {
          const dto = saleVariant(kind);
          const doc = layoutReceipt(dto, { width_mm: w, lang: "uz", template: tpl({ show_discount }) });
          const label = `${kind} show_discount=${show_discount} ${w}mm`;
          expect(doc.warnings, label).toEqual([]);
          const { items, subtotal, adj, total } = printedSums(doc, "uz");
          const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
          expect(total, label).toBe(cents("173 112") + (kind === "docOnly" ? 500000 : kind === "none" ? 600000 : 0));
          if (subtotal === null) {
            expect(adj, label).toEqual([]);
            expect(sum(items), label).toBe(total);
          } else {
            expect(sum(items), label).toBe(subtotal);
            expect(subtotal + sum(adj), label).toBe(total);
          }
        }
      }
    }
  });

  it("show_discount=false + chek chegirmasi, yaxlitlashsiz: chegirma satri bor, qatorlar oraliqqa teng (#15 ssenariysi)", () => {
    const dto = saleDto();
    dto.lines = [
      { name: "Non", qty: "2.000", unit: "dona", weighted: false, unit_price: "5000.00", gross: "10000.00", discount: "0.00", total: "10000.00" },
      { name: "Sut", qty: "1.000", unit: "dona", weighted: false, unit_price: "5000.00", gross: "5000.00", discount: "0.00", total: "5000.00" },
    ];
    dto.totals = { currency: "UZS", subtotal: "15000.00", line_discount: "0.00", doc_discount: "1000.00", rounding: "0.00", total: "14000.00" };
    dto.payments = [{ method: "cash", amount: "14000.00", given: null, change: null }];
    const o = opts(58, "uz", {}, { ...dto, template: tpl({ show_discount: false }) });
    const doc = golden("layout-nodisc-docdisc-58-uz.txt", dto, o);
    const text = lineTexts(doc).join("\n");
    expect(text).toMatch(/Oraliq jami +15 000/);
    expect(text).toMatch(/Chek chegirmasi +-1 000/);
    expect(text).toMatch(/JAMI 14 000 so'm/);
  });
});

describe("layoutReceipt — shablon matni chegarasi (sarlavha/footer)", () => {
  it("2000 ta bo'sh qator: ketma-ket bo'sh qatorlar bittaga yig'iladi (metrlab qog'oz yo'q)", () => {
    const dto = saleDto();
    const nl = "\n".repeat(1999);
    const doc = layoutReceipt(dto, { width_mm: 58, lang: "uz", template: tpl({ header: nl + "Shior", footer: nl + "Rahmat" }) });
    assertFits(doc);
    let run = 0;
    let maxRun = 0;
    for (const b of doc.blocks) {
      run = b.t === "line" && b.text === "" ? run + 1 : 0;
      maxRun = Math.max(maxRun, run);
    }
    // Boshidagi bo'sh qatorlar server kabi olinadi (0), o'rtadagilari bittaga yig'iladi.
    expect(maxRun).toBeLessThanOrEqual(1);
    expect(doc.blocks.length).toBeLessThan(120);
    const text = lineTexts(doc).join("\n");
    expect(text).toContain("Shior");
    expect(text).toContain("Rahmat");
    expect(doc.warnings).toEqual([]);
  });

  it(`eski (server tozalamagan) matn: ${MAX_TEMPLATE_LINES} YOZILGAN qator bilan cheklanadi + ogohlantirish`, () => {
    const many = (p: string) => Array.from({ length: 100 }, (_, i) => `${p}${i}`).join("\n");
    const doc = layoutReceipt(saleDto(), { width_mm: 80, lang: "uz", template: tpl({ header: many("H"), footer: many("F") }) });
    const lines = lineTexts(doc).map((l) => l.trim());
    expect(lines.filter((l) => /^H\d+$/.test(l)).length).toBe(MAX_TEMPLATE_LINES);
    expect(lines.filter((l) => /^F\d+$/.test(l)).length).toBe(MAX_TEMPLATE_LINES);
    expect(lines).toContain(`H${MAX_TEMPLATE_LINES - 1}`);
    expect(lines).not.toContain(`H${MAX_TEMPLATE_LINES}`);
    expect(doc.warnings).toEqual(expect.arrayContaining(["header_truncated", "footer_truncated"]));
    // Belgi chegarasi ham server kabi (2000): bitta ulkan qator shu yerda kesiladi.
    const huge = layoutReceipt(saleDto(), { width_mm: 80, lang: "uz", template: tpl({ footer: "ab ".repeat(1500) }) });
    const ab = lineTexts(huge).join(" ").match(/\bab\b/g) ?? [];
    expect(ab.length).toBe(667); // 2000 belgi = 666 × "ab " + "ab"
    expect(huge.warnings).toContain("footer_truncated");
    // Oddiy qisqa matn — o'zgarishsiz (bitta bo'sh qator niyatda saqlanadi).
    const ok = layoutReceipt(saleDto(), { width_mm: 80, lang: "uz", template: tpl({ footer: "A\n\nB" }) });
    const tl = lineTexts(ok).map((l) => l.trim());
    const ia = tl.lastIndexOf("A");
    expect(tl.slice(ia, ia + 3)).toEqual(["A", "", "B"]);
    expect(ok.warnings).toEqual([]);
  });
});

describe("shablon matni: server qabul qilgan matn to'liq chiqadi (R1/R12)", () => {
  // Server 30 YOZILGAN qator + 2000 belgini qabul qiladi; 58 mm da har qator o'ralsa ham hech narsa tushmasin.
  const policy = Array.from({ length: MAX_TEMPLATE_LINES }, (_, i) =>
    `${String(i + 1).padStart(2, "0")}. Qaytarish shartlari: chek va qadoq bilan 14 kun ichida`).join("\n");

  it(`${MAX_TEMPLATE_LINES} qatorli footer (har qator o'raladi) 58 va 80 mm da to'liq chiqadi, ogohlantirishsiz`, () => {
    expect(policy.length).toBeLessThanOrEqual(2000);
    for (const w of [58, 80] as const) {
      const doc = layoutReceipt(saleDto(), { width_mm: w, lang: "uz", template: tpl({ footer: policy, header: policy }) });
      assertFits(doc);
      const text = lineTexts(doc).map((l) => l.trim()).join(" ");
      for (let i = 1; i <= MAX_TEMPLATE_LINES; i++) {
        const n = String(i).padStart(2, "0");
        // Sarlavha va footer — ikkalasida ham har yozilgan qator (oxirgi so'zigacha).
        expect(text.split(`${n}. Qaytarish shartlari: chek va qadoq bilan 14 kun ichida`).length - 1, `${w} ${n}`).toBe(2);
      }
      expect(doc.warnings).not.toContain("footer_truncated");
      expect(doc.warnings).not.toContain("header_truncated");
    }
    // 58 mm da o'ralgan qatorlar soni haqiqatan 30 dan ko'p (eski o'ralgan-qator chegarasi shu yerda kesardi).
    const d58 = layoutReceipt(saleDto(), { width_mm: 58, lang: "uz", template: tpl({ footer: policy }) });
    const all = lineTexts(d58);
    const from = all.findIndex((l) => l.includes("01. Qaytarish"));
    expect(all.length - from).toBeGreaterThan(MAX_TEMPLATE_LINES);
  });

  it("bitta uzun paragraf (1999 belgi) 58 mm da oxirigacha chiqadi", () => {
    const words = Array.from({ length: 400 }, (_, i) => `so'z${i}`);
    let para = "";
    for (const w of words) if ((para + " " + w).length <= 1999) para = para ? `${para} ${w}` : w;
    const last = para.split(" ").pop()!;
    const doc = layoutReceipt(saleDto(), { width_mm: 58, lang: "uz", template: tpl({ footer: para }) });
    assertFits(doc);
    expect(lineTexts(doc).map((l) => l.trim())).toEqual(expect.arrayContaining([expect.stringContaining(last)]));
    expect(doc.warnings).not.toContain("footer_truncated");
  });
});

describe("matn kengligi: birlashuvchi belgilar va emoji (#30)", () => {
  const C = String.fromCharCode;
  const ACUTE = C(0x301);

  it("birlashuvchi belgi 0 ustun; qattiq bo'linishda asosidan ajralmaydi", () => {
    expect(charWidth(ACUTE)).toBe(0);
    expect(strWidth("а" + ACUTE)).toBe(1);
    expect(strWidth("ба" + ACUTE + "лан")).toBe(5);
    // "x" + 40 ta ("а" + U+0301): eski modelda (belgi = 1 ustun) 32-belgida urg'u yangi satr boshiga tushardi.
    const word = "x" + ("а" + ACUTE).repeat(40);
    const lines = wrapText(word, 32);
    for (const l of lines) {
      expect(/^\p{M}/u.test(l), JSON.stringify(l)).toBe(false);
      expect(strWidth(l)).toBeLessThanOrEqual(32);
    }
    expect(lines.join("")).toBe(word); // hech narsa yo'qolmagan
    expect(lines[0]).toBe("x" + ("а" + ACUTE).repeat(31)); // 32 ustun to'liq
    // Chekka holat: keng belgi 1 ustunga sig'maydi (baribir o'z satrida) — urg'u undan ajralmaydi.
    expect(wrapText("茶" + ACUTE + "茶", 1)).toEqual(["茶" + ACUTE, "茶"]);
    const dto = saleDto();
    dto.lines[0].name = word;
    const doc = layoutReceipt(dto, opts(58, "ru"));
    assertFits(doc);
    for (const t of lineTexts(doc)) expect(/^\s*\p{M}/u.test(t), JSON.stringify(t)).toBe(false);
  });

  it("emoji/piktogramma '?' ga, VS16/keycap olib tashlanadi — HTML va ESC/POS bir xil; © ® ™ qoladi", () => {
    const VS16 = C(0xfe0f);
    const dto = saleDto();
    dto.lines[0].name = `Kofe ${C(0x2615)} ${C(0x2764)}${VS16} 1${VS16}${C(0x20e3)} ${C(0x2b50)}${C(0x2705)}`;
    const dense = C(0x2615).repeat(32); // 58 mm to'liq qator: eski modelda sig'ardi, HTML'da ~80 ustun
    const doc = layoutReceipt(dto, {
      width_mm: 58, lang: "uz", template: tpl({ footer: `${dense}\nBrand${C(0xa9)} ${C(0xae)} ${C(0x2122)}` }),
    });
    assertFits(doc);
    const texts = lineTexts(doc);
    for (const t of texts) {
      expect(/(?![\u00a9\u00ae\u2122])[\p{Extended_Pictographic}\p{Emoji_Presentation}\uFE0F\u20E3]/u.test(t), JSON.stringify(t)).toBe(false);
    }
    expect(texts).toContain("Kofe ? ? 1 ??");
    expect(texts).toContain("?".repeat(32));
    expect(texts.some((t) => t.includes(`Brand${C(0xa9)} ${C(0xae)} ${C(0x2122)}`))).toBe(true);
    // HTML: emoji yo'q; ESC/POS: har satr bayti = kengligi (qog'oz va ekran bir xil).
    expect(/\p{Emoji_Presentation}/u.test(renderHtml(doc))).toBe(false);
    for (const t of texts) expect(encodeText(t, "cp1251").bytes.length).toBe(strWidth(t));
    const p = profileFor("generic58", 58);
    const esc = encodeEscPos(doc, p);
    expect(esc.warnings.filter((w) => w === "line_wrapped")).toEqual([]);
    const printed = parseEscPos(esc.bytes).filter((c) => c.cmd === "TEXT").map((c) => String(c.text));
    expect(printed).toContain("Kofe ? ? 1 ??");
    expect(printed).toContain("?".repeat(32));
  });
});

describe("birlashuvchi belgilar zichligi (R11): bir asosga ko'pi bilan 2 ta", () => {
  const C = String.fromCharCode;
  const M1 = C(0x301); // urg'u
  const M2 = C(0x300);
  const M3 = C(0x308);
  const cpLen = (s: string) => Array.from(s).length;

  it("ortiqcha belgi tashlanadi (+ogohlantirish); satr ≤ 3 × ustun kod nuqtasi; ESC/POS so'rovi main'da o'tadi", () => {
    // "zalgo": har harf ustida 5 belgi — eski qoidada 48 ustunli satr ~290 kod nuqtasi bo'lardi.
    const zalgo = ("б" + M1 + M2 + M3 + M1 + M2).repeat(60) + " Кофе";
    expect(cleanText(zalgo).startsWith("б" + M1 + M2 + "б" + M1 + M2)).toBe(true);
    expect(cleanText(zalgo)).not.toContain(M2 + M3);
    for (const w of [58, 80] as const) {
      const dto = saleDto();
      dto.lines[0].name = zalgo;
      dto.store.name = zalgo;
      const doc = layoutReceipt(dto, { width_mm: w, lang: "ru", template: tpl({ footer: zalgo, header: zalgo }) });
      assertFits(doc);
      expect(doc.warnings).toContain("marks_dropped");
      for (const b of doc.blocks) {
        if (b.t !== "line") continue;
        const cols = doc.cols / (b.size === 2 ? 2 : 1);
        expect(cpLen(b.text), JSON.stringify(b.text)).toBeLessThanOrEqual(3 * cols);
        expect(/\p{M}{3}/u.test(b.text), JSON.stringify(b.text)).toBe(false);
      }
      const p = profileFor(w === 58 ? "generic58" : "epson80", w);
      const req = validateEscPosRequest({ doc, profile: p, target: { kind: "lan", host: "192.168.1.50", port: 9100 }, copies: 1, cut: true });
      expect(req.ok, JSON.stringify(req)).toBe(true);
    }
  });

  it("oddiy matn (1–2 belgi: rus urg'usi, qirg'iz/o'zbek diakritikasi) o'zgarmaydi, ogohlantirish yo'q", () => {
    const ok = "за" + M1 + "мок · q" + M1 + M2 + "x · Қо" + M3 + "ғоз";
    expect(cleanText(ok)).toBe(ok.normalize("NFC"));
    const dto = saleDto();
    dto.lines[0].name = ok;
    const doc = layoutReceipt(dto, opts(80, "ru"));
    expect(doc.warnings).not.toContain("marks_dropped");
  });

  it("asossiz belgi (satr boshi, bo'shliq yoki yangi qatordan keyin) tashlanadi", () => {
    expect(cleanText(M1 + M2 + "a")).toBe("a");
    expect(cleanText("a " + M1 + "b")).toBe("a b");
    expect(cleanText("a\n" + M1 + M2 + "b")).toBe("a\nb");
    let n = 0;
    cleanText("a " + M1, () => { n += 1; });
    expect(n).toBe(1);
  });
});

describe("emoji faqat emoji ko'rinishida '?' (R13): matn belgilari qoladi", () => {
  const C = String.fromCodePoint;
  const VS16 = C(0xfe0f);
  // Consolas/DejaVu/Courier'da 1 ustun: ♥ ♦ ♣ ♠ ♪ ♫ ☺ ☻ ☼ ♀ ♂ ‼ ↔ ↕ ▪ ▫
  const TEXT_SYMBOLS = [0x2665, 0x2666, 0x2663, 0x2660, 0x266a, 0x266b, 0x263a, 0x263b, 0x263c, 0x2640, 0x2642,
    0x203c, 0x2194, 0x2195, 0x25aa, 0x25ab].map((c) => C(c)).join("");

  it("matn ko'rinishidagi belgilar o'zgarmaydi, kengligi = kod nuqtasi soni", () => {
    const s = `Rahmat! ${C(0x2665)} Yana keling ${C(0x266a)} ${TEXT_SYMBOLS}`;
    expect(cleanText(s)).toBe(s);
    expect(strWidth(TEXT_SYMBOLS)).toBe(Array.from(TEXT_SYMBOLS).length);
  });

  it("emoji ko'rinishli belgi va VS16 bilan kelgan belgi '?'; ASCII keycap — raqamning o'zi", () => {
    expect(cleanText(C(0x2615, 0x2b50, 0x2705, 0x1f600, 0x1f34e))).toBe("?????");
    expect(cleanText(C(0x2665) + VS16)).toBe("?"); // ♥️ — emoji ko'rinishi (HTML'da ~2.5 ustun)
    expect(cleanText(C(0x2764) + VS16 + " " + C(0x2764))).toBe("? " + C(0x2764));
    expect(cleanText("1" + VS16 + C(0x20e3))).toBe("1");
    expect(cleanText(C(0x2615) + VS16)).toBe("?"); // VS16 alohida "?" bo'lmaydi
  });

  it("footer 'Rahmat! ♥ Yana keling ♪': HTML'da belgilar bilan; ESC/POS'da '?' (kenglik bir xil, o'ralmaydi)", () => {
    const footer = `Rahmat! ${C(0x2665)} Yana keling ${C(0x266a)}`;
    const dto = saleDto();
    dto.lines[0].name = `Konfet ${C(0x2665)}`;
    const doc = layoutReceipt(dto, { width_mm: 58, lang: "uz", template: tpl({ footer }) });
    assertFits(doc);
    const texts = lineTexts(doc).map((t) => t.trim());
    expect(texts).toContain(footer);
    expect(texts).toContain(`Konfet ${C(0x2665)}`);
    const html = renderHtml(doc);
    expect(html).toContain(footer);
    const esc = encodeEscPos(doc, profileFor("generic58", 58));
    expect(esc.warnings.filter((w) => w === "line_wrapped" || w === "width_mismatch")).toEqual([]);
    const printed = parseEscPos(esc.bytes).filter((c) => c.cmd === "TEXT").map((c) => String(c.text).trim());
    expect(printed).toContain("Rahmat! ? Yana keling ?");
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
