import { describe, expect, it } from "vitest";
import {
  ESCPOS_WHITELIST, PROFILES, base64Decode, describeEscPos, encodeEscPos, layoutReceipt, parseEscPos, profileFor,
  sampleReceipt, type EscPosCommand, type PrinterProfile, type ReceiptDoc,
} from "@/receipt";
import {
  FULL_TEMPLATE, LOGO_64x16, expectGolden, saleDto, smallDto, tpl,
} from "./__golden__/receipt/fixtures";

// Phase 5F F1: ReceiptDoc → ESC/POS. Oq ro'yxatdan boshqa buyruq YO'Q (ayniqsa ESC p — pul qutisi),
// matndan boshqaruv bayti chiqmaydi, raster/QR/shtrix-kod ma'lumoti to'g'ri uzunlikda.

const C = String.fromCharCode;
const INJECTIONS = [C(0x1b, 0x70, 0x00) + "drawer", C(0x1d, 0x56) + "cut", C(0x10, 0x14) + "dle", C(0x1b, 0x40)];

function hexDump(bytes: Uint8Array): string {
  const rows: string[] = [];
  for (let i = 0; i < bytes.length; i += 16) {
    const chunk = Array.from(bytes.subarray(i, i + 16), (b) => b.toString(16).padStart(2, "0"));
    rows.push(i.toString(16).padStart(6, "0") + "  " + chunk.join(" "));
  }
  return rows.join("\n");
}

/** Faqat oq ro'yxatdagi buyruqlar, parametrlari ruxsat etilgan qiymatlarda. */
function assertWhitelisted(cmds: EscPosCommand[]) {
  for (const c of cmds) {
    expect(ESCPOS_WHITELIST, JSON.stringify(c)).toContain(c.cmd);
    if (c.cmd === "GS !") expect([0x00, 0x11]).toContain(c.n);
    if (c.cmd === "ESC E") expect([0, 1]).toContain(c.n);
    if (c.cmd === "ESC a") expect([0, 1, 2]).toContain(c.n);
    if (c.cmd === "GS V") expect([[65, 0], [66, 0]]).toContainEqual([c.m, c.n]);
    if (c.cmd === "GS k") expect(c.m).toBe(73);
    if (c.cmd === "GS ( k") {
      expect(c.cn).toBe(0x31);
      expect([0x41, 0x43, 0x45, 0x50, 0x51]).toContain(c.fn);
    }
    if (c.cmd === "GS H") expect(c.n).toBe(0);
  }
}

function encode(doc: ReceiptDoc, p: PrinterProfile, o?: { copies?: number; cut?: boolean }) {
  const r = encodeEscPos(doc, p, o);
  const cmds = parseEscPos(r.bytes, { codepage: p.codepage.name });
  assertWhitelisted(cmds);
  return { ...r, cmds };
}

/** GS v 0 bo'laklarini bitta rasmga yig'adi (sinov: rasterni pikselga qaytarish). */
function rasters(bytes: Uint8Array): { width: number; height: number; bits: Uint8Array }[] {
  const out: { width: number; height: number; bits: Uint8Array }[] = [];
  for (let i = 0; i + 8 <= bytes.length; ) {
    if (bytes[i] === 0x1d && bytes[i + 1] === 0x76 && bytes[i + 2] === 0x30) {
      const x = bytes[i + 4] + bytes[i + 5] * 256;
      const y = bytes[i + 6] + bytes[i + 7] * 256;
      out.push({ width: x * 8, height: y, bits: bytes.slice(i + 8, i + 8 + x * y) });
      i += 8 + x * y;
    } else i++;
  }
  return out;
}
const px = (r: { width: number; bits: Uint8Array }, x: number, y: number) =>
  (r.bits[y * (r.width / 8) + (x >> 3)] >> (7 - (x & 7))) & 1;

describe("encodeEscPos — golden (hex + buyruqlar ro'yxati)", () => {
  function golden(name: string, doc: ReceiptDoc, p: PrinterProfile) {
    const r = encode(doc, p);
    const listing = describeEscPos(r.cmds).map((l) => "# " + l).join("\n");
    expectGolden(
      name,
      `# ESC/POS golden — profil ${p.id} (${p.width_mm} mm, ${p.cols} ustun, ${p.codepage.name}/ESC t ${p.codepage.escT})\n` +
        `# kodlovchi ogohlantirishlari: ${JSON.stringify(r.warnings)}\n# ${r.bytes.length} bayt\n` +
        `# --- buyruqlar (parseEscPos) ---\n${listing}\n# --- baytlar (hex) ---\n${hexDump(r.bytes)}\n`,
    );
    return r;
  }

  it("kichik chek 80 mm, epson80: native QR va CODE128, qisman kesish", () => {
    const dto = smallDto();
    const doc = layoutReceipt(dto, { width_mm: 80, lang: "uzc", template: dto.template });
    const r = golden("escpos-small-80-epson.hex", doc, profileFor("epson80", 80));
    expect(r.warnings).toEqual([]);
    expect(r.cmds.some((c) => c.cmd === "GS ( k" && c.fn === 0x50 && c.data === "2609191288")).toBe(true);
    expect(r.cmds.some((c) => c.cmd === "GS k" && c.data === "{B2609191288")).toBe(true);
    expect(r.cmds[r.cmds.length - 1]).toEqual({ cmd: "GS V", m: 66, n: 0 });
  });

  it("kichik chek 58 mm, generic58: logo + raster shtrix-kod, kesgich yo'q → surish", () => {
    const dto = smallDto();
    const template = tpl({ show_barcode: true });
    const doc = layoutReceipt(dto, { width_mm: 58, lang: "ru", template, logo: LOGO_64x16 });
    const r = golden("escpos-small-58-generic.hex", doc, profileFor("generic58", 58));
    expect(r.warnings).toEqual(["cut_unsupported"]);
    expect(r.cmds.some((c) => c.cmd === "GS V")).toBe(false);
  });
});

describe("encodeEscPos — xavfsizlik", () => {
  it("mahsulot nomidagi ESC p / GS V / DLE DC4 in'ektsiyasi: begona buyruq yo'q, pul qutisi ochilmaydi", () => {
    const dto = saleDto();
    dto.lines = dto.lines.map((l, i) => ({ ...l, name: INJECTIONS[i % INJECTIONS.length] + " " + l.name }));
    dto.store.name = INJECTIONS[0];
    dto.template = { ...FULL_TEMPLATE, footer: INJECTIONS.join(" "), header: INJECTIONS[1] };
    for (const id of Object.keys(PROFILES)) {
      const p = PROFILES[id];
      const doc = layoutReceipt(dto, { width_mm: p.width_mm, lang: "ru", template: dto.template, logo: LOGO_64x16 });
      const { bytes, cmds } = encode(doc, p);
      expect(cmds.filter((c) => c.cmd === "UNKNOWN" || c.cmd === "TRUNCATED")).toEqual([]);
      // ESC @ faqat nusxa boshida; bayt darajasida ham ESC p ketma-ketligi yo'q.
      expect(cmds.filter((c) => c.cmd === "ESC @").length).toBe(1);
      for (let i = 0; i + 1 < bytes.length; i++) {
        if (bytes[i] === 0x1b && bytes[i + 1] === 0x70) {
          // Faqat raster/QR ma'lumoti ichida bo'lishi mumkin — tahlilchi uni buyruq deb o'qimagan.
          expect(cmds.some((c) => c.cmd === "GS v 0" || c.cmd === "GS ( k")).toBe(true);
        }
      }
      expect(cmds.filter((c) => c.cmd === "GS V").length).toBeLessThanOrEqual(1);
    }
  });

  it("layout'ni chetlab o'tgan doc (IPC orqali buzilgan) ham boshqaruv baytini matnga o'tkazmaydi", () => {
    const doc: ReceiptDoc = {
      width_mm: 80, cols: 48, warnings: [],
      blocks: [
        { t: "line", text: `A${C(0x1b, 0x70, 0x00, 0x19, 0xfa)}B` },
        { t: "line", text: `${C(0x1d, 0x56, 0x41, 0x00)}`, bold: true, size: 2 },
        { t: "line", text: `${C(0x10, 0x14, 0x01, 0x00, 0x05)}` },
        { t: "line", text: "x\ny" },
      ],
    };
    const { cmds, warnings, bytes } = encode(doc, PROFILES.epson80);
    expect(cmds.filter((c) => c.cmd === "UNKNOWN")).toEqual([]);
    const text = cmds.filter((c) => c.cmd === "TEXT").map((c) => c.text);
    expect(text).toEqual(["A?p??uB", "?VA?", "?????", "x?y"]);
    expect(warnings).toEqual(expect.arrayContaining(["lossy:U+001B", "lossy:U+001D", "lossy:U+0010", "lossy:U+000A"]));
    expect(Array.from(bytes).includes(0x10)).toBe(false);
  });

  it("parseEscPos oq ro'yxatdan tashqarini UNKNOWN deb belgilaydi (ESC p, DLE DC4, GS V 0)", () => {
    const cmds = parseEscPos(Uint8Array.from([0x1b, 0x70, 0x00, 0x19, 0xfa, 0x10, 0x14, 0x01, 0x1d, 0x56, 0x00, 0x0d]));
    expect(cmds.filter((c) => c.cmd === "UNKNOWN").length).toBeGreaterThanOrEqual(4);
    expect(cmds[0]).toMatchObject({ cmd: "UNKNOWN", byte: 0x1b, next: 0x70 });
  });

  it("parseEscPos raster/QR ma'lumoti ichidagi 0x1B/0x1D ni buyruq deb o'qimaydi; kesilgan buyruq → TRUNCATED", () => {
    const raster = [0x1d, 0x76, 0x30, 0x00, 0x02, 0x00, 0x02, 0x00, 0x1b, 0x70, 0x1d, 0x56];
    const qr = [0x1d, 0x28, 0x6b, 0x06, 0x00, 0x31, 0x50, 0x30, 0x1b, 0x70, 0x00];
    const cmds = parseEscPos(Uint8Array.from([...raster, ...qr, 0x0a]));
    expect(cmds.map((c) => c.cmd)).toEqual(["GS v 0", "GS ( k", "LF"]);
    expect(cmds[0]).toMatchObject({ width: 16, height: 2, data: 4 });
    expect(parseEscPos(Uint8Array.from([0x1d, 0x76, 0x30, 0x00, 0x10, 0x00, 0x10]))[0].cmd).toBe("TRUNCATED");
    expect(parseEscPos(Uint8Array.from([0x1d, 0x76, 0x30, 0x00, 0x01, 0x00, 0x05, 0x00, 0xff]))[0].cmd).toBe("TRUNCATED");
  });
});

describe("encodeEscPos — profil imkoniyatlari", () => {
  const dto = saleDto();
  const doc80 = layoutReceipt(dto, { width_mm: 80, lang: "uz", template: FULL_TEMPLATE, logo: LOGO_64x16 });

  it("raster QR: rasm matritsaga piksel-aniq mos (hoshiya 4 modul, o'rtada)", () => {
    const { bytes, warnings } = encode(doc80, PROFILES.generic80);
    expect(warnings).toEqual([]);
    const imgs = rasters(bytes);
    const qr = imgs[imgs.length - 1];
    expect(qr.width).toBe(576);
    const scale = qr.height / 29;
    expect(Number.isInteger(scale)).toBe(true);
    const off = Math.floor((576 - qr.height) / 2);
    const m = dto.qr!.matrix;
    for (let y = 0; y < 21; y++) {
      for (let x = 0; x < 21; x++) {
        const cx = off + (x + 4) * scale + (scale >> 1);
        const cy = (y + 4) * scale + (scale >> 1);
        expect(px(qr, cx, cy), `${x},${y}`).toBe(Number(m[y][x]));
      }
    }
    // hoshiya oq
    for (let x = 0; x < 576; x++) expect(px(qr, x, 0)).toBe(0);
  });

  it("raster shtrix-kod: modullar qayta tiklanadi; logo o'rtada, baytlari o'zgarmagan", () => {
    const { bytes } = encode(doc80, PROFILES.generic80);
    const imgs = rasters(bytes);
    const logo = imgs[0];
    expect([logo.width, logo.height]).toEqual([576, 16]);
    const src = base64Decode(LOGO_64x16.raster_b64)!;
    const offBytes = (576 / 8 - 64 / 8) / 2;
    for (let y = 0; y < 16; y++) {
      expect(Array.from(logo.bits.subarray(y * 72 + offBytes, y * 72 + offBytes + 8))).toEqual(Array.from(src.subarray(y * 8, y * 8 + 8)));
    }
    const bc = imgs[1];
    const mods = dto.barcode!.modules;
    const w = Math.max(1, Math.min(3, Math.floor(576 / (mods.length + 20))));
    const off = Math.floor((576 - (mods.length + 20) * w) / 2);
    let got = "";
    for (let i = 0; i < mods.length; i++) got += px(bc, off + (i + 10) * w, bc.height >> 1);
    expect(got).toBe(mods);
  });

  it("qo'llanmaydigan imkoniyatlar: ogohlantirish, yiqilmaydi; QR payload matn bo'lib chiqadi; kesish o'rniga surish", () => {
    const bare = profileFor("generic80", 80, { raster: false, qr: "none", barcode: "none", cut: "none" });
    const { cmds, warnings } = encode(doc80, bare);
    expect(warnings).toEqual(expect.arrayContaining(["logo_unsupported", "qr_unsupported", "barcode_unsupported", "cut_unsupported"]));
    expect(cmds.some((c) => c.cmd === "GS v 0" || c.cmd === "GS ( k" || c.cmd === "GS k" || c.cmd === "GS V")).toBe(false);
    const texts = cmds.filter((c) => c.cmd === "TEXT").map((c) => String(c.text).trim());
    expect(texts.filter((t) => t === "2609191288").length).toBe(2); // HRI + QR matn zaxirasi
    const tail = cmds.slice(-2);
    expect(tail).toEqual([{ cmd: "ESC d", n: 4 }, { cmd: "ESC d", n: 4 }]);
  });

  it("native QR raster'ga tushmaydi; raster profil native buyruq ishlatmaydi", () => {
    const n = encode(doc80, PROFILES.epson80);
    expect(n.cmds.filter((c) => c.cmd === "GS ( k").map((c) => c.fn)).toEqual([0x41, 0x43, 0x45, 0x50, 0x51]);
    const qrSize = n.cmds.find((c) => c.cmd === "GS ( k" && c.fn === 0x43) as EscPosCommand;
    expect((qrSize.params as number[])[0]).toBe(8);
    const ec = n.cmds.find((c) => c.cmd === "GS ( k" && c.fn === 0x45) as EscPosCommand;
    expect((ec.params as number[])[0]).toBe(0x31); // M
    const ai = n.cmds.findIndex((c) => c.cmd === "ESC a" && c.n === 1);
    expect(n.cmds[ai + 1].cmd === "GS h" || n.cmds[ai + 1].cmd === "GS ( k").toBe(true);
    const r = encode(doc80, PROFILES.generic80);
    expect(r.cmds.some((c) => c.cmd === "GS ( k" || c.cmd === "GS k" || c.cmd === "ESC a")).toBe(false);
  });

  it("CODE128 native: '{' payload'da '{{' bo'lib qochiriladi; ASCII bo'lmasa raster'ga o'tadi", () => {
    const doc: ReceiptDoc = {
      width_mm: 80, cols: 48, warnings: [],
      blocks: [{ t: "barcode", payload: "A{B", modules: "1101" }, { t: "barcode", payload: "Ўз", modules: "1101" }],
    };
    const r = encode(doc, PROFILES.epson80);
    expect(r.cmds.find((c) => c.cmd === "GS k")?.data).toBe("{BA{{B");
    expect(r.cmds.filter((c) => c.cmd === "GS v 0").length).toBe(1);
  });

  it("qog'ozdan keng shtrix-kod: barcode_too_wide, raster/native yo'q (kesilgan kod o'qilmaydi)", () => {
    const doc: ReceiptDoc = {
      width_mm: 58, cols: 32, warnings: [], blocks: [{ t: "barcode", payload: "X", modules: "10".repeat(200) }],
    };
    for (const p of [PROFILES.generic58, PROFILES.xprinter58]) {
      const r = encode(doc, p);
      expect(r.warnings).toContain("barcode_too_wide");
      expect(r.cmds.some((c) => c.cmd === "GS v 0" || c.cmd === "GS k")).toBe(false);
    }
  });

  it("nusxalar: butun ketma-ketlik takrorlanadi, har nusxa o'z kesishi bilan; 1..3 ga cheklanadi", () => {
    const one = encode(doc80, PROFILES.epson80);
    const three = encode(doc80, PROFILES.epson80, { copies: 3 });
    expect(three.bytes.length).toBe(one.bytes.length * 3);
    expect(three.cmds.filter((c) => c.cmd === "ESC @").length).toBe(3);
    expect(three.cmds.filter((c) => c.cmd === "GS V").length).toBe(3);
    expect(encode(doc80, PROFILES.epson80, { copies: 9 }).cmds.filter((c) => c.cmd === "ESC @").length).toBe(3);
    expect(encode(doc80, PROFILES.epson80, { copies: 0 }).cmds.filter((c) => c.cmd === "ESC @").length).toBe(1);
  });

  it("cut:false kesmaydi; cut:true auto_cut o'chiq bo'lsa ham kesadi; to'liq kesish profili GS V 65", () => {
    expect(encode(doc80, PROFILES.epson80, { cut: false }).cmds.some((c) => c.cmd === "GS V")).toBe(false);
    const noAuto = layoutReceipt(dto, { width_mm: 80, lang: "uz", template: tpl({ auto_cut: false }) });
    expect(encode(noAuto, PROFILES.epson80).cmds.some((c) => c.cmd === "GS V")).toBe(false);
    expect(encode(noAuto, PROFILES.epson80, { cut: true }).cmds.slice(-1)[0]).toEqual({ cmd: "GS V", m: 66, n: 0 });
    const full = profileFor("epson80", 80, { cut: "full" });
    expect(encode(doc80, full).cmds.slice(-1)[0]).toEqual({ cmd: "GS V", m: 65, n: 0 });
  });

  it("80 mm doc 58 mm profilda: width_mismatch, satrlar printer kengligida bo'linadi", () => {
    const { cmds, warnings } = encode(doc80, PROFILES.xprinter58);
    expect(warnings).toEqual(expect.arrayContaining(["width_mismatch", "line_wrapped"]));
    for (const c of cmds) if (c.cmd === "TEXT") expect(Number(c.length)).toBeLessThanOrEqual(32);
  });

  it("cp1251 profili: ESC t 46 va kirill cp1251 baytlarida", () => {
    const p = profileFor("generic80", 80, { codepage: { name: "cp1251", escT: 46 } });
    const doc = layoutReceipt(dto, { width_mm: 80, lang: "ru", template: FULL_TEMPLATE });
    const { cmds, bytes } = encode(doc, p);
    expect(cmds[1]).toEqual({ cmd: "ESC t", n: 46 });
    expect(cmds.some((c) => c.cmd === "TEXT" && String(c.text).includes("ИТОГО"))).toBe(true);
    expect(Array.from(bytes).includes(0xc8)).toBe(true); // "И" cp1251 da
  });

  it("har bir preset va 4 til: yiqilmaydi, faqat oq ro'yxat, matn qatori ustundan oshmaydi", () => {
    for (const id of Object.keys(PROFILES)) {
      const p = PROFILES[id];
      for (const lang of ["uz", "uzc", "ru", "ky"] as const) {
        for (const kind of ["sale", "mixed", "return", "long"] as const) {
          const s = sampleReceipt(kind, { name: "Do'kon" }, { show_barcode: true });
          const doc = layoutReceipt(s, { width_mm: p.width_mm, lang, template: s.template, logo: LOGO_64x16 });
          const { cmds, warnings } = encode(doc, p);
          expect(cmds.some((c) => c.cmd === "UNKNOWN" || c.cmd === "TRUNCATED")).toBe(false);
          expect(warnings.filter((w) => w.startsWith("lossy:") || w === "line_wrapped" || w === "width_mismatch")).toEqual([]);
          let size = 1;
          for (const c of cmds) {
            if (c.cmd === "GS !") size = c.n === 0x11 ? 2 : 1;
            if (c.cmd === "TEXT") expect(Number(c.length)).toBeLessThanOrEqual(p.cols / size);
          }
        }
      }
    }
  });
});

describe("profileFor", () => {
  it("presetlar SPEC bo'yicha", () => {
    expect(PROFILES.generic58).toMatchObject({ dots: 384, cols: 32, cut: "none", qr: "raster", barcode: "raster", raster: true, status_query: false, codepage: { name: "cp866", escT: 17 } });
    expect(PROFILES.generic80).toMatchObject({ dots: 576, cols: 48, cut: "partial", qr: "raster", barcode: "raster" });
    expect(PROFILES.epson80).toMatchObject({ dots: 576, cols: 48, cut: "partial", qr: "native", barcode: "native", status_query: true, codepage: { name: "cp866", escT: 17 } });
    expect(PROFILES.xprinter80).toMatchObject({ dots: 576, cols: 48, cut: "partial", qr: "native", barcode: "native", codepage: { name: "cp866", escT: 17 } });
    expect(PROFILES.xprinter58).toMatchObject({ dots: 384, cols: 32, cut: "none", qr: "native", barcode: "native" });
  });

  it("noma'lum id → generic{kenglik}; kenglik doim so'ralganidan; presetlar o'zgarmaydi", () => {
    expect(profileFor(undefined, 58).id).toBe("generic58");
    expect(profileFor("nope", 80).id).toBe("generic80");
    expect(profileFor("__proto__", 80).id).toBe("generic80");
    const e58 = profileFor("epson80", 58);
    expect(e58).toMatchObject({ id: "epson80", width_mm: 58, dots: 384, cols: 32, qr: "native" });
    e58.codepage.escT = 99;
    expect(PROFILES.epson80.codepage.escT).toBe(17);
  });

  it("overrides: faqat yaroqli kalit/qiymat; axlat e'tiborsiz", () => {
    const p = profileFor("generic80", 80, {
      cut: "full", qr: "native", feed_lines: 2, dots: 512, status_query: true,
      // localStorage'dan kelgan axlat:
      cols: 99, width_mm: 58 as never, raster: "yes" as never, codepage: { name: "utf8" as never, escT: 5 },
    });
    expect(p).toMatchObject({ cut: "full", qr: "native", feed_lines: 2, dots: 512, status_query: true, cols: 48, width_mm: 80, raster: true });
    expect(p.codepage).toEqual({ name: "cp866", escT: 17 });
    expect(profileFor("generic80", 80, { dots: 513 }).dots).toBe(576);
    expect(profileFor("generic80", 80, { feed_lines: 99 }).feed_lines).toBe(4);
    expect(profileFor("generic58", 58, { dots: 576 }).dots).toBe(384);
  });
});
