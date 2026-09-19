import { describe, expect, it } from "vitest";
import {
  docHeightMm, escapeHtml, layoutReceipt, pageSizeMm, renderHtml, sampleReceipt, type Block, type ReceiptDoc,
} from "@/receipt";
import { FULL_TEMPLATE, LOGO_64x16, expectGolden, saleDto, smallDto, tpl } from "./__golden__/receipt/fixtures";

// Phase 5F F1: ReceiptDoc → to'liq HTML. Xavfsizlik (XSS), CSP, @page o'lchami, QR/shtrix-kod SVG.

const CSP = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">`;
const XSS = [`<img src=x onerror=alert(1)>`, `"><script>alert(1)</script>`, `'><svg onload=alert(1)>`];

function parse(html: string): Document {
  return new DOMParser().parseFromString(html, "text/html");
}

describe("renderHtml — tuzilma", () => {
  it("to'liq hujjat: doctype, CSP, @page 58/80, bosma kenglik 48/72 mm, monospace", () => {
    for (const w of [58, 80] as const) {
      const html = renderHtml(layoutReceipt(saleDto(), { width_mm: w, lang: "uz", template: FULL_TEMPLATE }));
      expect(html.startsWith("<!doctype html>")).toBe(true);
      expect(html).toContain(CSP);
      const doc = layoutReceipt(saleDto(), { width_mm: w, lang: "uz", template: FULL_TEMPLATE });
      expect(html).toContain(`@page { size: ${w}mm ${pageSizeMm(doc).height_mm}mm; margin: 0 }`);
      expect(html).toContain(`.r{width:${w === 58 ? 48 : 72}mm`);
      expect(html).toContain(`font-family:"Consolas","DejaVu Sans Mono","Courier New",monospace`);
      expect(html).toContain("white-space:pre");
      // cols belgi sig'adi: printable / cols / 0.62 → 48/32/0.62 = 72/48/0.62 = 2.419 mm
      expect(html).toContain("font-size:2.419mm");
      expect(html).toContain(".s2{font-size:4.839mm}");
    }
  });

  it("har satr alohida <div>, size 2 va qalin sinflar bilan; rule cols belgidan", () => {
    const doc = layoutReceipt(saleDto(), { width_mm: 58, lang: "uz", template: FULL_TEMPLATE });
    const d = parse(renderHtml(doc));
    const lines = Array.from(d.querySelectorAll(".r > div.l"));
    expect(lines.length).toBe(doc.blocks.filter((b) => b.t === "line" || b.t === "rule").length +
      doc.blocks.filter((b) => b.t === "feed").reduce((s, b) => s + (b as { lines: number }).lines, 0));
    const store = lines.find((e) => e.textContent?.includes("Fayzan Market"));
    expect(store?.className).toBe("l b s2");
    expect(lines.some((e) => e.textContent === "=".repeat(32))).toBe(true);
    expect(lines.some((e) => e.textContent === "-".repeat(32))).toBe(true);
  });

  it("title qochiriladi, standart 'Receipt'", () => {
    const doc = layoutReceipt(saleDto(), { width_mm: 80, lang: "ru", template: FULL_TEMPLATE });
    expect(renderHtml(doc)).toContain("<title>Receipt</title>");
    expect(renderHtml(doc, { title: "Chek #1 <b>" })).toContain("<title>Chek #1 &lt;b&gt;</title>");
  });

  it("golden: kichik chek 58 mm (logo, shtrix-kod, QR)", () => {
    const doc = layoutReceipt(smallDto(), { width_mm: 58, lang: "uz", template: smallDto().template, logo: LOGO_64x16 });
    expectGolden("html-small-58-uz.html", renderHtml(doc, { title: "Chek #1288" }) + "\n");
  });
});

describe("renderHtml — XSS", () => {
  it("do'kon nomi, footer, sarlavha, mahsulot nomi, kassir — hammasi matn sifatida", () => {
    const dto = saleDto();
    dto.store.name = XSS[0];
    dto.store.address = XSS[1];
    dto.actor.cashier = XSS[2];
    dto.lines[0].name = XSS[1] + " " + XSS[0];
    dto.lines[1].unit = `<b>kg</b>`;
    const template = { ...FULL_TEMPLATE, header: XSS[2], footer: `${XSS[0]}\n${XSS[1]}` };
    for (const w of [58, 80] as const) {
      const html = renderHtml(layoutReceipt(dto, { width_mm: w, lang: "uz", template, logo: LOGO_64x16 }), { title: XSS[1] });
      expect(html).not.toMatch(/<script/i);
      expect(html).not.toMatch(/<img src=x/i);
      expect(html).not.toMatch(/<svg onload/i);
      expect(html).not.toContain("<b>kg</b>");
      const d = parse(html);
      expect(d.querySelectorAll("script").length).toBe(0);
      // Faqat bitta <img> (logo, data:image/png) — begona img/iframe/object yo'q.
      const imgs = Array.from(d.querySelectorAll("img"));
      expect(imgs.length).toBe(1);
      expect(imgs[0].getAttribute("src")).toMatch(/^data:image\/png;base64,/);
      expect(d.querySelectorAll("iframe,object,embed,link,base,form").length).toBe(0);
      for (const el of Array.from(d.querySelectorAll("*"))) {
        for (const a of Array.from(el.attributes)) expect(a.name.startsWith("on"), `${el.tagName} ${a.name}`).toBe(false);
      }
      // Matn o'z holida ko'rinadi (qochirilgan, lekin yo'qolmagan).
      expect(d.body.textContent).toContain("<img src=x onerror=alert(1)>");
      expect(d.body.textContent).toContain(`"><script>alert(1)</script>`);
    }
  });

  it("escapeHtml: & < > \" ' — beshalasi", () => {
    expect(escapeHtml(`&<>"'`)).toBe("&amp;&lt;&gt;&quot;&#39;");
    expect(escapeHtml("oddiy matn")).toBe("oddiy matn");
  });

  it("logo faqat data:image/png;base64 bo'lsa; javascript:/svg/http URI → img yo'q", () => {
    const base = layoutReceipt(smallDto(), { width_mm: 80, lang: "uz", template: tpl(), logo: LOGO_64x16 });
    for (const uri of [
      "javascript:alert(1)", "data:image/svg+xml;base64,PHN2Zz4=", "http://evil.example/x.png",
      'data:image/png;base64,AAAA" onerror="alert(1)', "data:text/html;base64,PHNjcmlwdD4=",
    ]) {
      const doc: ReceiptDoc = {
        ...base,
        blocks: base.blocks.map((b): Block => (b.t === "logo" ? { ...b, png_data_uri: uri } : b)),
      };
      const html = renderHtml(doc);
      expect(parse(html).querySelectorAll("img").length, uri).toBe(0);
      expect(html).not.toContain("evil.example");
      expect(html).not.toContain("javascript:");
    }
    const ok = parse(renderHtml(base)).querySelector("img");
    expect(ok?.getAttribute("style")).toBe("width:8mm;height:2mm"); // 64/8 × 16/8
  });
});

describe("renderHtml — QR va shtrix-kod SVG", () => {
  it("QR: matritsadagi har qora modul SVG yo'lida; hoshiya 4 modul", () => {
    const dto = saleDto();
    const doc = layoutReceipt(dto, { width_mm: 58, lang: "uz", template: FULL_TEMPLATE });
    const d = parse(renderHtml(doc));
    const svg = d.querySelector('svg[aria-label="QR"]') as SVGElement;
    expect(svg).not.toBeNull();
    expect(svg.getAttribute("viewBox")).toBe("0 0 29 29");
    // Yo'lni qayta pikselga aylantirib, matritsa bilan solishtiramiz.
    const path = svg.querySelector("path")?.getAttribute("d") ?? "";
    const grid = Array.from({ length: 21 }, () => Array(21).fill("0"));
    for (const m of path.matchAll(/M(\d+) (\d+)h(\d+)v1h-\d+z/g)) {
      const [x, y, len] = [Number(m[1]) - 4, Number(m[2]) - 4, Number(m[3])];
      for (let i = 0; i < len; i++) grid[y][x + i] = "1";
    }
    expect(grid.map((r) => r.join(""))).toEqual(dto.qr!.matrix);
  });

  it("shtrix-kod: modullar SVG'da aynan qayta tiklanadi", () => {
    const dto = saleDto();
    const doc = layoutReceipt(dto, { width_mm: 80, lang: "uz", template: FULL_TEMPLATE });
    const svg = parse(renderHtml(doc)).querySelector('svg[aria-label="CODE128"]') as SVGElement;
    const n = dto.barcode!.modules.length;
    expect(svg.getAttribute("viewBox")).toBe(`0 0 ${n + 20} 1`);
    const bits = Array(n).fill("0");
    for (const m of (svg.querySelector("path")?.getAttribute("d") ?? "").matchAll(/M(\d+) 0h(\d+)v1h-\d+z/g)) {
      for (let i = 0; i < Number(m[2]); i++) bits[Number(m[1]) - 10 + i] = "1";
    }
    expect(bits.join("")).toBe(dto.barcode!.modules);
  });

  it("buzilgan QR/shtrix-kod bloki HTML'ga tushmaydi (yiqilmaydi)", () => {
    const doc: ReceiptDoc = {
      width_mm: 58, cols: 32, warnings: [],
      blocks: [
        { t: "qr", payload: "x", size: 21, matrix: ["01"] },
        { t: "barcode", payload: "x", modules: "10<script>" },
        { t: "line", text: "ok" },
      ],
    };
    const html = renderHtml(doc);
    expect(parse(html).querySelectorAll("svg").length).toBe(0);
    expect(html).not.toContain("<script>");
  });
});

describe("@page o'lchami (chop etish sahifasi)", () => {
  // `size: 58mm auto` — YAROQSIZ CSS (uzunlik + auto): brauzer butun deklaratsiyani tashlab, printerning
  // standart qog'ozida (A4/Letter) chekni sahifalarga bo'lardi. Ikkala qiymat ham uzunlik bo'lishi shart.
  const SIZE_RE = /@page \{ size: (\d+(?:\.\d+)?)mm (\d+(?:\.\d+)?)mm; margin: 0 \}/;

  it("ikkala qiymat uzunlik (mm), 'auto' yo'q; kenglik — qog'oz, balandlik — butun chek + zaxira", () => {
    for (const w of [58, 80] as const) {
      for (const kind of ["sale", "long"] as const) {
        const s0 = sampleReceipt(kind);
        const doc = layoutReceipt(s0, { width_mm: w, lang: "ru", template: s0.template, logo: LOGO_64x16 });
        const html = renderHtml(doc);
        const m = SIZE_RE.exec(html);
        expect(m, `${w} ${kind}`).not.toBeNull();
        expect(html).not.toMatch(/size:[^;]*auto/);
        expect(Number(m![1])).toBe(w);
        const h = Number(m![2]);
        expect(Number.isInteger(h)).toBe(true);
        // Chek sahifaga to'liq sig'adi (brauzer yaxlitlashi uchun zaxira), lekin ortiqcha qog'oz yemaydi.
        expect(h).toBeGreaterThanOrEqual(docHeightMm(doc) + 3);
        expect(h).toBeLessThanOrEqual(docHeightMm(doc) + 4);
        expect(pageSizeMm(doc)).toEqual({ width_mm: w, height_mm: h });
      }
    }
    const short = layoutReceipt(smallDto(), { width_mm: 58, lang: "uz", template: tpl() });
    const long = sampleReceipt("long");
    const longDoc = layoutReceipt(long, { width_mm: 58, lang: "uz", template: long.template });
    expect(pageSizeMm(longDoc).height_mm).toBeGreaterThan(pageSizeMm(short).height_mm * 10);
    // Chegaralar Electron pageSize bilan bir xil (validate.ts 20..3276 mm).
    expect(pageSizeMm({ width_mm: 58, cols: 32, blocks: [], warnings: [] })).toEqual({ width_mm: 58, height_mm: 20 });
    const huge: ReceiptDoc = { width_mm: 80, cols: 48, warnings: [], blocks: Array(2000).fill({ t: "line", text: "x" }) };
    expect(pageSizeMm(huge).height_mm).toBe(3276);
  });
});

describe("sahifa rejimi: exact / driver (R4/R14)", () => {
  // «Printer drayveri»: Electron pageSize YUBORMAYDI — CSS sahifasi ham o'lchamsiz bo'lishi shart, aks holda
  // Chromium chek o'lchamidagi CSS sahifani drayver qog'oziga sig'dirib (kichraytirib) o'rtaga qo'yardi.
  const style = (html: string) => /<style>([\s\S]*)<\/style>/.exec(html)![1];
  const body = (html: string) => /<body>([\s\S]*)<\/body>/.exec(html)![1];

  it("driver: `@page { margin: 0 }`, hech qanday `size:` yo'q; tana exact bilan AYNAN bir xil", () => {
    for (const w of [58, 80] as const) {
      for (const kind of ["sale", "long"] as const) {
        const s0 = sampleReceipt(kind);
        const doc = layoutReceipt(s0, { width_mm: w, lang: "ru", template: s0.template, logo: LOGO_64x16 });
        const driver = renderHtml(doc, { pageMode: "driver" });
        expect(style(driver)).toContain("@page { margin: 0 }");
        expect(style(driver)).not.toMatch(/@page[^}]*size/);
        expect(style(driver).match(/@page/g)).toHaveLength(1);
        const exact = renderHtml(doc, { pageMode: "exact" });
        const page = pageSizeMm(doc);
        expect(style(exact)).toContain(`@page { size: ${page.width_mm}mm ${page.height_mm}mm; margin: 0 }`);
        // Standart (rejim berilmagan) — exact: Manager ko'rinishi va eski chaqiruvchilar o'zgarmaydi.
        expect(renderHtml(doc)).toBe(exact);
        expect(body(driver)).toBe(body(exact));
      }
    }
  });

  it("golden: kichik chek 58 mm, drayver rejimi", () => {
    const doc = layoutReceipt(smallDto(), { width_mm: 58, lang: "uz", template: smallDto().template, logo: LOGO_64x16 });
    expectGolden("html-small-58-uz-driver.html", renderHtml(doc, { title: "Chek #1288", pageMode: "driver" }) + "\n");
  });
});

describe("docHeightMm", () => {
  it("satrlar, rasm, QR va shtrix-kod balandligi yig'indisi; uzun chek uzunroq", () => {
    const small = layoutReceipt(smallDto(), { width_mm: 58, lang: "uz", template: tpl() });
    const h = docHeightMm(small);
    let rows = 0;
    for (const b of small.blocks) {
      if (b.t === "line") rows += b.size === 2 ? 2 : 1;
      else if (b.t === "rule") rows += 1;
      else if (b.t === "feed") rows += b.lines;
    }
    const lineMm = (48 / 32 / 0.62) * 1.2;
    expect(h).toBeCloseTo(4 + rows * lineMm, 1);
    const long = sampleReceipt("long");
    const lh = docHeightMm(layoutReceipt(long, { width_mm: 58, lang: "ru", template: long.template }));
    expect(lh).toBeGreaterThan(h * 10);
    const withGfx = layoutReceipt(saleDto(), { width_mm: 80, lang: "uz", template: FULL_TEMPLATE, logo: LOGO_64x16 });
    const noGfx = layoutReceipt(saleDto(), { width_mm: 80, lang: "uz", template: tpl({ show_logo: false }) });
    expect(docHeightMm(withGfx)).toBeGreaterThan(docHeightMm(noGfx) + 2 + 10 + 10);
    expect(Number.isFinite(docHeightMm({ width_mm: 80, cols: 48, blocks: [], warnings: [] }))).toBe(true);
  });
});
