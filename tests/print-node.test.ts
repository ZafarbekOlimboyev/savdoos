// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import * as fs from "node:fs";
import * as net from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { EventEmitter } from "node:events";
import { execFileSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { encodeEscPos, layoutReceipt, parseEscPos, profileFor, type ReceiptDoc } from "@/receipt";
import { PRINT_IPC } from "@/print/bridge";
import {
  LIMITS, isLanPort, isPrivateIPv4, validateEscPosRequest, validateHtmlRequest, validateLegacyPrint,
} from "@/print/node/validate";
import { paperStatus, sendLan } from "@/print/node/lan";
import { SPOOLER_SCRIPT, sendSpooler, spoolerExit } from "@/print/node/spooler";
import {
  PRINT_PARTITION, failureCode, printRequestAllowed, registerPrintIpc, withPrintCsp, type PrintWindowOptions,
} from "@/print/node/ipc";
import { LOGO_64x16, smallDto } from "./__golden__/receipt/fixtures";

// Phase 5F F2: Electron MAIN chop etish qatlami — renderer'dan kelgan so'rov tekshiruvi, LAN (virtual TCP
// printer), Windows RAW spooler (argv, in'ektsiyasiz), IPC handler'lari va alias'siz yig'ilish.

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const GOLDEN = path.join(ROOT, "tests", "__golden__", "receipt", "escpos-small-80-epson.hex");

/** F1 golden faylining "baytlar (hex)" bo'limi — kodlovchining kutilgan AYNAN baytlari. */
function goldenBytes(): Buffer {
  const text = fs.readFileSync(GOLDEN, "utf8").replace(/\r\n/g, "\n");
  const i = text.indexOf("# --- baytlar (hex) ---");
  expect(i).toBeGreaterThan(0);
  const out: number[] = [];
  for (const line of text.slice(i).split("\n").slice(1)) {
    const m = /^[0-9a-f]{6}\s+(.*)$/.exec(line.trim());
    if (m) for (const h of m[1].trim().split(/\s+/)) out.push(parseInt(h, 16));
  }
  return Buffer.from(out);
}

function goldenDoc(): ReceiptDoc {
  const dto = smallDto();
  return layoutReceipt(dto, { width_mm: 80, lang: "uzc", template: dto.template });
}

function escposReq(over: Record<string, unknown> = {}) {
  return {
    doc: goldenDoc(),
    profile: profileFor("epson80", 80),
    target: { kind: "lan", host: "192.168.1.50", port: 9100 },
    ...over,
  };
}

// ── virtual printer (mahalliy TCP server) ─────────────────────────────────
interface VPrinter { port: number; received: () => Buffer; closed: Promise<void>; stop: () => Promise<void> }

function startPrinter(opts: { status?: number | null; pause?: boolean } = {}): Promise<VPrinter> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    const sockets = new Set<net.Socket>();
    let onClosed: () => void = () => undefined;
    const closed = new Promise<void>((r) => { onClosed = r; });
    const srv = net.createServer((sock) => {
      sockets.add(sock);
      if (opts.pause) {
        sock.pause();
        return;
      }
      let answered = false;
      sock.on("data", (c) => {
        chunks.push(c);
        const all = Buffer.concat(chunks);
        if (!answered && opts.status !== undefined && opts.status !== null && all.length >= 3 &&
            all[0] === 0x10 && all[1] === 0x04 && all[2] === 0x04) {
          answered = true;
          sock.write(Buffer.from([opts.status]));
        }
      });
      sock.on("end", () => sock.end());
      sock.on("close", () => onClosed());
      sock.on("error", () => undefined);
    });
    srv.listen(0, "127.0.0.1", () => {
      const port = (srv.address() as net.AddressInfo).port;
      resolve({
        port,
        received: () => Buffer.concat(chunks),
        closed,
        stop: () => new Promise<void>((r) => {
          for (const s of sockets) s.destroy();
          srv.close(() => r());
        }),
      });
    });
  });
}

function freePort(): Promise<number> {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => {
      const p = (s.address() as net.AddressInfo).port;
      s.close(() => resolve(p));
    });
  });
}

const printers: VPrinter[] = [];
afterEach(async () => {
  while (printers.length) await printers.pop()!.stop();
});
async function vp(opts?: { status?: number | null; pause?: boolean }) {
  const p = await startPrinter(opts);
  printers.push(p);
  return p;
}

// ── validate.ts ───────────────────────────────────────────────────────────
describe("validate.ts — renderer so'rovi qat'iy tekshiriladi", () => {
  it("to'g'ri so'rov qabul qilinadi va YANGI obyekt qaytadi (logo PNG main'ga o'tmaydi)", () => {
    const dto = smallDto();
    const doc = layoutReceipt(dto, { width_mm: 58, lang: "ru", template: dto.template, logo: LOGO_64x16 });
    expect(doc.blocks.some((b) => b.t === "logo" && !!b.png_data_uri)).toBe(true);
    const r = validateEscPosRequest({ doc, profile: profileFor("generic58", 58), target: { kind: "spooler", printer: "XP-58" }, copies: 2, cut: true });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.value.doc).not.toBe(doc);
    expect(r.value.doc.warnings).toEqual([]);
    const logo = r.value.doc.blocks.find((b) => b.t === "logo");
    expect(logo && "png_data_uri" in logo).toBe(false);
    expect(r.value.copies).toBe(2);
    expect(r.value.target).toEqual({ kind: "spooler", printer: "XP-58" });
    // Bloklar ma'nosi o'zgarmaydi: kodlangan baytlar bir xil.
    const p = profileFor("generic58", 58);
    expect(Array.from(encodeEscPos(r.value.doc, p).bytes)).toEqual(Array.from(encodeEscPos(doc, p).bytes));
  });

  const doc = () => goldenDoc();
  const bad: [string, () => unknown][] = [
    ["xom baytlar (renderer bayt yubora olmaydi)", () => escposReq({ bytes: [0x1b, 0x70, 0x00] })],
    ["noma'lum yuqori kalit", () => escposReq({ extra: 1 })],
    ["bloklar 6000 dan ko'p", () => escposReq({ doc: { ...doc(), blocks: Array.from({ length: LIMITS.blocks + 1 }, () => ({ t: "feed", lines: 0 })) } })],
    ["satr 96 belgidan uzun", () => escposReq({ doc: { ...doc(), blocks: [{ t: "line", text: "x".repeat(97) }] } })],
    ["noma'lum blok turi", () => escposReq({ doc: { ...doc(), blocks: [{ t: "drawer" }] } })],
    ["blokda begona maydon", () => escposReq({ doc: { ...doc(), blocks: [{ t: "line", text: "a", raw: "\x1bp" }] } })],
    ["size 3", () => escposReq({ doc: { ...doc(), blocks: [{ t: "line", text: "a", size: 3 }] } })],
    ["feed 11", () => escposReq({ doc: { ...doc(), blocks: [{ t: "feed", lines: 11 }] } })],
    ["raster eni 8 ga karrali emas", () => escposReq({ doc: { ...doc(), blocks: [{ t: "logo", width: 100, height: 1, raster_b64: "A".repeat(20) }] } })],
    ["raster eni 576 dan katta", () => escposReq({ doc: { ...doc(), blocks: [{ t: "logo", width: 584, height: 1, raster_b64: Buffer.alloc(73).toString("base64") }] } })],
    ["raster balandligi 4000 dan katta", () => escposReq({ doc: { ...doc(), blocks: [{ t: "logo", width: 8, height: 4001, raster_b64: Buffer.alloc(4001).toString("base64") }] } })],
    ["raster_b64 uzunligi o'lchamga mos emas", () => escposReq({ doc: { ...doc(), blocks: [{ t: "logo", width: 64, height: 16, raster_b64: Buffer.alloc(127).toString("base64") }] } })],
    ["raster_b64 base64 emas", () => escposReq({ doc: { ...doc(), blocks: [{ t: "logo", width: 8, height: 3, raster_b64: "A?==" }] } })],
    ["QR payload 700 dan uzun", () => escposReq({ doc: { ...doc(), blocks: [{ t: "qr", payload: "x".repeat(701), size: 21, matrix: Array(21).fill("0".repeat(21)) }] } })],
    ["QR o'lchami 177 dan katta", () => escposReq({ doc: { ...doc(), blocks: [{ t: "qr", payload: "x", size: 181, matrix: Array(181).fill("0".repeat(181)) }] } })],
    ["QR matritsa qatori noto'g'ri", () => escposReq({ doc: { ...doc(), blocks: [{ t: "qr", payload: "x", size: 21, matrix: [...Array(20).fill("0".repeat(21)), "2".repeat(21)] }] } })],
    ["QR payload'da boshqaruv belgisi", () => escposReq({ doc: { ...doc(), blocks: [{ t: "qr", payload: "a\x1bp", size: 21, matrix: Array(21).fill("0".repeat(21)) }] } })],
    ["shtrix-kod payload'ida ESC", () => escposReq({ doc: { ...doc(), blocks: [{ t: "barcode", payload: "12\x1b34", modules: "1101" }] } })],
    ["shtrix-kod payload'i kirill", () => escposReq({ doc: { ...doc(), blocks: [{ t: "barcode", payload: "чек", modules: "1101" }] } })],
    ["shtrix-kod payload'i 65 belgi", () => escposReq({ doc: { ...doc(), blocks: [{ t: "barcode", payload: "1".repeat(65), modules: "1101" }] } })],
    ["copies 0", () => escposReq({ copies: 0 })],
    ["copies 4", () => escposReq({ copies: 4 })],
    ["copies 1.5", () => escposReq({ copies: 1.5 })],
    ["doc.width_mm 70", () => escposReq({ doc: { ...doc(), width_mm: 70 } })],
    ["profil dots 577", () => escposReq({ profile: { ...profileFor("epson80", 80), dots: 584 } })],
    ["profilda begona kalit", () => escposReq({ profile: { ...profileFor("epson80", 80), drawer: true } })],
    ["profil kod sahifasi noma'lum", () => escposReq({ profile: { ...profileFor("epson80", 80), codepage: { name: "utf8", escT: 0 } } })],
    ["LAN: ommaviy IP", () => escposReq({ target: { kind: "lan", host: "8.8.8.8", port: 9100 } })],
    ["LAN: localhost", () => escposReq({ target: { kind: "lan", host: "127.0.0.1", port: 9100 } })],
    ["LAN: xost nomi", () => escposReq({ target: { kind: "lan", host: "printer.local", port: 9100 } })],
    ["LAN: port 80", () => escposReq({ target: { kind: "lan", host: "192.168.1.50", port: 80 } })],
    ["LAN: port 9110", () => escposReq({ target: { kind: "lan", host: "192.168.1.50", port: 9110 } })],
    ["spooler: nom tirnoq bilan", () => escposReq({ target: { kind: "spooler", printer: 'XP"80' } })],
    ["spooler: nom '-' bilan boshlanadi", () => escposReq({ target: { kind: "spooler", printer: "-File" } })],
    // PowerShell `-File` en/em tire va gorizontal chiziqni ham parametr belgisi deb o'qiydi (5F.1 #26).
    ["spooler: nom en-tire (U+2013) bilan", () => escposReq({ target: { kind: "spooler", printer: "\u2013Kassa:1" } })],
    ["spooler: nom em-tire (U+2014) bilan", () => escposReq({ target: { kind: "spooler", printer: "\u2014a:b" } })],
    ["spooler: nom gorizontal chiziq (U+2015) bilan", () => escposReq({ target: { kind: "spooler", printer: "\u2015a:b" } })],
    ["spooler: nom defis (U+2010) bilan", () => escposReq({ target: { kind: "spooler", printer: "\u2010x" } })],
    ["spooler: nom minus (U+2212) bilan", () => escposReq({ target: { kind: "spooler", printer: "\u2212x" } })],
    ["profil realtime_disable boolean emas", () => escposReq({ profile: { ...profileFor("epson80", 80), realtime_disable: 1 } })],
    ["spooler: nomda boshqaruv belgisi", () => escposReq({ target: { kind: "spooler", printer: "XP\n80" } })],
    ["target turi noma'lum", () => escposReq({ target: { kind: "usb", path: "COM1" } })],
    ["prototip hiylasi (oddiy obyekt emas)", () => Object.assign(Object.create({ polluted: true }), escposReq())],
    ["massiv", () => [escposReq()]],
  ];
  it.each(bad)("RAD: %s", (_name, make) => {
    const r = validateEscPosRequest(make());
    expect(r.ok).toBe(false);
  });

  it("96 belgili kirill satr va 177 o'lchamli QR — chegarada qabul qilinadi", () => {
    const r = validateEscPosRequest(escposReq({
      doc: {
        ...goldenDoc(), blocks: [
          { t: "line", text: "Ж".repeat(96) },
          { t: "qr", payload: "https://example.uz/", size: 177, matrix: Array(177).fill("01".repeat(88) + "1") },
          { t: "barcode", payload: "~ ok {}", modules: "1101" },
        ],
      },
      copies: 3,
    }));
    expect(r.ok).toBe(true);
  });

  it("5F.2 R11: 48 ustunli satr birlashuvchi belgilar bilan (asos + 2 belgi = 144 kod nuqtasi) — qabul; kenglik chegarasi saqlanadi", () => {
    const marks = "б́̀".repeat(48); // 48 ustun, 144 kod nuqtasi
    expect(Array.from(marks)).toHaveLength(144);
    const one = (text: string) => validateEscPosRequest(escposReq({ doc: { ...goldenDoc(), blocks: [{ t: "line", text }] } }));
    expect(one(marks).ok).toBe(true);
    // Butun chek: urg'uli mahsulot nomi 80 mm da — har satr bloki main tekshiruvidan o'tadi.
    const dto = smallDto();
    dto.lines = [{ ...dto.lines[0], name: "б́̀".repeat(20) + " Кофе" }, ...dto.lines];
    for (const w of [58, 80] as const) {
      const doc = layoutReceipt(dto, { width_mm: w, lang: "ru", template: dto.template });
      const r = validateEscPosRequest(escposReq({ doc, profile: profileFor("generic", w) }));
      expect(r.ok, `${w}: ${r.ok ? "" : r.error}`).toBe(true);
    }
    // Ko'rinadigan kenglik (belgi 0, keng belgi 2) — 96 ustundan oshsa rad; kod nuqtalari 200 dan oshsa ham rad.
    expect(one("б́".repeat(97)).ok).toBe(false);
    expect(one("中".repeat(49)).ok).toBe(false);
    expect(one("a" + "́".repeat(200)).ok).toBe(false);
    expect(LIMITS.lineCols).toBe(96);
    // doc/profil ustunlari hamon 16..96.
    expect(validateEscPosRequest(escposReq({ doc: { ...goldenDoc(), cols: 97 } })).ok).toBe(false);
    expect(validateEscPosRequest(escposReq({ profile: { ...profileFor("epson80", 80), cols: 97 } })).ok).toBe(false);
  });

  it("HTML so'rovi: 5 MB chegara (UTF-8 baytlarida), kenglik, printer nomi", () => {
    expect(validateHtmlRequest({ html: "<p>x</p>", widthMm: 80 }).ok).toBe(true);
    expect(validateHtmlRequest({ html: "<p>x</p>", widthMm: 58, printer: "XP-58", copies: 2 }).ok).toBe(true);
    const def = validateHtmlRequest({ html: "<p>x</p>", widthMm: 80, printer: "" });
    expect(def.ok && def.value.printer).toBe(undefined); // bo'sh = tizim standarti
    expect(validateHtmlRequest({ html: "x".repeat(LIMITS.htmlBytes + 1), widthMm: 80 }).ok).toBe(false);
    // 2.7 mln kirill belgi = 5.4 MB UTF-8 — belgilar soni chegaradan kichik, baytlar katta.
    expect(validateHtmlRequest({ html: "Ж".repeat(2_700_000), widthMm: 80 }).ok).toBe(false);
    expect(validateHtmlRequest({ html: "", widthMm: 80 }).ok).toBe(false);
    expect(validateHtmlRequest({ html: "<p>x</p>", widthMm: 70 }).ok).toBe(false);
    expect(validateHtmlRequest({ html: "<p>x</p>", widthMm: 80, copies: 9 }).ok).toBe(false);
    expect(validateHtmlRequest({ html: "<p>x</p>", widthMm: 80, printer: "a\x00b" }).ok).toBe(false);
    expect(validateHtmlRequest({ html: 42, widthMm: 80 }).ok).toBe(false);
    expect(validateLegacyPrint({ html: "<p>x</p>", deviceName: null }).ok).toBe(true);
    expect(validateLegacyPrint({ html: "<p>x</p>", deviceName: "-x" }).ok).toBe(false);
    expect(validateLegacyPrint({ html: "<p>x</p>", deviceName: "\u2013x:y" }).ok).toBe(false);
    // Tire nom O'RTASIDA — oddiy nom (masalan "XP-80C", "Kassa \u2013 1").
    expect(validateHtmlRequest({ html: "<p>x</p>", widthMm: 80, printer: "Kassa \u2013 1" }).ok).toBe(true);
  });

  it("HTML so'rovi: sahifa balandligi (20..3276 butun) va rejim (exact/driver)", () => {
    const ok = validateHtmlRequest({ html: "<p>x</p>", widthMm: 58, heightMm: 157, pageMode: "exact" });
    expect(ok.ok && ok.value).toMatchObject({ widthMm: 58, heightMm: 157, pageMode: "exact" });
    expect(validateHtmlRequest({ html: "<p>x</p>", widthMm: 80, heightMm: 20, pageMode: "driver" }).ok).toBe(true);
    expect(validateHtmlRequest({ html: "<p>x</p>", widthMm: 80, heightMm: 3276 }).ok).toBe(true);
    for (const heightMm of [19, 3277, 100.5, "100", -1, NaN]) {
      expect(validateHtmlRequest({ html: "<p>x</p>", widthMm: 80, heightMm }).ok, String(heightMm)).toBe(false);
    }
    expect(validateHtmlRequest({ html: "<p>x</p>", widthMm: 80, heightMm: 100, pageMode: "a4" }).ok).toBe(false);
    const legacy = validateHtmlRequest({ html: "<p>x</p>", widthMm: 80 });
    expect(legacy.ok && legacy.value).not.toHaveProperty("pageMode");
  });

  it("profil realtime_disable (ixtiyoriy boolean) o'tadi — epson80 ESC/POS rad etilmaydi", () => {
    const r = validateEscPosRequest(escposReq({ profile: { ...profileFor("epson80", 80), realtime_disable: true } }));
    expect(r.ok).toBe(true);
    expect(r.ok && r.value.profile.realtime_disable).toBe(true);
    const plain = { ...profileFor("generic80", 80) } as Record<string, unknown>;
    delete plain.realtime_disable;
    const none = validateEscPosRequest(escposReq({ profile: plain }));
    expect(none.ok && "realtime_disable" in none.value.profile).toBe(false);
  });

  it("isPrivateIPv4 / isLanPort — faqat literal xususiy IPv4 va 9100–9109", () => {
    for (const ok of ["10.0.0.1", "10.255.255.254", "172.16.0.5", "172.31.255.254", "192.168.1.50", "169.254.10.20"]) {
      expect(isPrivateIPv4(ok), ok).toBe(true);
    }
    for (const no of ["8.8.8.8", "127.0.0.1", "0.0.0.0", "172.15.0.1", "172.32.0.1", "192.169.0.1", "192.168.1.300",
      "192.168.01.5", "192.168.1", "printer.local", " 192.168.1.5", "::1", "0x0a.0.0.1", "10.0.0.1:9100", "", null, 10]) {
      expect(isPrivateIPv4(no), String(no)).toBe(false);
    }
    for (let p = 9100; p <= 9109; p++) expect(isLanPort(p)).toBe(true);
    for (const p of [9099, 9110, 80, 443, 9100.5, "9100", NaN]) expect(isLanPort(p), String(p)).toBe(false);
  });
});

// ── lan.ts ────────────────────────────────────────────────────────────────
describe("lan.ts — virtual TCP printer", () => {
  it("baytlar F1 golden bilan AYNAN bir xil yetib boradi", async () => {
    const printer = await vp();
    const bytes = encodeEscPos(goldenDoc(), profileFor("epson80", 80)).bytes;
    const golden = goldenBytes();
    expect(Buffer.from(bytes).equals(golden)).toBe(true);
    const r = await sendLan("127.0.0.1", printer.port, bytes);
    expect(r).toEqual({ ok: true });
    await printer.closed;
    expect(printer.received().equals(golden)).toBe(true);
  });

  it("holat so'rovi: qog'oz bor (0x12) → DLE EOT 4 + chek", async () => {
    const printer = await vp({ status: 0x12 });
    const bytes = Uint8Array.from([0x1b, 0x40, 0x41, 0x0a]);
    const r = await sendLan("127.0.0.1", printer.port, bytes, { statusQuery: true });
    expect(r.ok).toBe(true);
    await printer.closed;
    expect(Array.from(printer.received())).toEqual([0x10, 0x04, 0x04, 0x1b, 0x40, 0x41, 0x0a]);
  });

  it("holat so'rovi: qog'oz tugagan (0x72) → PAPER_OUT, chek YUBORILMAYDI", async () => {
    const printer = await vp({ status: 0x72 });
    const r = await sendLan("127.0.0.1", printer.port, Uint8Array.from([0x41, 0x0a]), { statusQuery: true });
    expect(r.ok).toBe(false);
    expect(r.code).toBe("PAPER_OUT");
    await printer.closed;
    expect(Array.from(printer.received())).toEqual([0x10, 0x04, 0x04]);
  });

  it("holat so'rovi: qog'oz kam (0x1e) → chop etiladi + ogohlantirish", async () => {
    const printer = await vp({ status: 0x1e });
    const r = await sendLan("127.0.0.1", printer.port, Uint8Array.from([0x41, 0x0a]), { statusQuery: true });
    expect(r).toEqual({ ok: true, warnings: ["paper_near_end"] });
  });

  it("holat so'roviga javob yo'q → kutib, baribir chop etadi", async () => {
    const printer = await vp({ status: null });
    const t0 = Date.now();
    const r = await sendLan("127.0.0.1", printer.port, Uint8Array.from([0x41, 0x0a]), { statusQuery: true, statusWaitMs: 150 });
    expect(r.ok).toBe(true);
    expect(Date.now() - t0).toBeGreaterThanOrEqual(140);
    await printer.closed;
    expect(Array.from(printer.received())).toEqual([0x10, 0x04, 0x04, 0x41, 0x0a]);
  });

  it("paperStatus: qat'iy bitlar mos kelmasa — noma'lum (e'tiborsiz)", () => {
    expect(paperStatus(0x12)).toBe("ok");
    expect(paperStatus(0x72)).toBe("out");
    expect(paperStatus(0x1e)).toBe("near_end");
    expect(paperStatus(0x60)).toBe("unknown");
    expect(paperStatus(0xff)).toBe("unknown");
  });

  it("yopiq port → OFFLINE", async () => {
    const port = await freePort();
    const r = await sendLan("127.0.0.1", port, Uint8Array.from([0x41]), { timeoutMs: 3000 });
    expect(r.ok).toBe(false);
    expect(r.code).toBe("OFFLINE");
  });

  it("printer o'qimaydi (bufer to'la) → TIMEOUT", async () => {
    const printer = await vp({ pause: true });
    const big = new Uint8Array(64 * 1024 * 1024).fill(0x41);
    const r = await sendLan("127.0.0.1", printer.port, big, { timeoutMs: 400 });
    expect(r.ok).toBe(false);
    expect(r.code).toBe("TIMEOUT");
  }, 20_000);
});

// ── spooler.ts ────────────────────────────────────────────────────────────
class FakeChild extends EventEmitter {
  stderr = new EventEmitter();
  kill = vi.fn();
}

describe("spooler.ts — Windows RAW (PowerShell + winspool)", () => {
  it("Windows emas → REJECTED (spawn chaqirilmaydi)", async () => {
    const spawn = vi.fn();
    const r = await sendSpooler("XP-80", Uint8Array.from([1]), { platform: "linux", tmpdir: os.tmpdir(), spawn: spawn as never });
    expect(r.code).toBe("REJECTED");
    expect(spawn).not.toHaveBeenCalled();
  });

  it("printer nomi argv'da EMAS — muhitda (BINOS_PRINTER); skript o'zgarmas; baytlar faylda; papka o'chadi", async () => {
    // "–Kassa:1" — PowerShell -File uni argv'da parametr deb bo'lib yuborardi (5F.1 #26).
    const evil = "\u2013Kassa:1 XP'; Remove-Item C:\\ -Recurse; $(calc) `whoami` & echo";
    const bytes = Uint8Array.from([0x1b, 0x40, 0x41, 0x0a, 0x00, 0xff]);
    let seen: { cmd: string; args: string[]; opts: Record<string, unknown>; script: string; data: Buffer } | null = null;
    const spawn = vi.fn((cmd: string, args: string[], opts: Record<string, unknown>) => {
      const i = args.indexOf("-File");
      seen = { cmd, args, opts, script: fs.readFileSync(args[i + 1], "utf8"), data: fs.readFileSync(args[i + 2]) };
      const child = new FakeChild();
      setTimeout(() => child.emit("close", 0), 5);
      return child;
    });
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "binos-test-"));
    const r = await sendSpooler(evil, bytes, { platform: "win32", tmpdir: tmp, spawn: spawn as never });
    expect(r).toEqual({ ok: true });
    const s = seen!;
    expect(s.cmd).toBe("powershell.exe");
    expect(s.opts.shell).toBe(false);
    const i = s.args.indexOf("-File");
    expect(s.args.slice(0, i)).toEqual(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]);
    expect(s.args).toHaveLength(i + 3); // skript + baytlar fayli — boshqa argv yo'q
    expect(s.args.some((a) => a.includes("Kassa"))).toBe(false);
    expect(path.isAbsolute(s.args[i + 2])).toBe(true);
    const env = s.opts.env as Record<string, string>;
    expect(env.BINOS_PRINTER).toBe(evil); // butun nom, o'zgarishsiz, muhitda
    expect(env.PATH ?? env.Path).toBe(process.env.PATH ?? process.env.Path); // qolgan muhit saqlanadi
    expect(s.script).toBe(String.fromCharCode(0xfeff) + SPOOLER_SCRIPT); // BOM: PowerShell 5.1 UTF-8 deb o'qisin
    expect(s.script).not.toContain("XP'");
    expect(Array.from(s.data)).toEqual(Array.from(bytes));
    expect(fs.readdirSync(tmp)).toEqual([]); // skript va baytlar o'chirildi
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  it("skript printer nomini faqat muhitdan, fayl yo'lini $args[0] dan oladi va RAW rejimda yozadi", () => {
    expect(SPOOLER_SCRIPT).toContain("$printer = [string]$env:BINOS_PRINTER");
    expect(SPOOLER_SCRIPT).toContain("$dataPath = [string]$args[0]");
    expect(SPOOLER_SCRIPT).not.toContain("$args[1]");
    expect(SPOOLER_SCRIPT).toContain('di.pDataType = "RAW"');
    expect(SPOOLER_SCRIPT).not.toMatch(/Invoke-Expression|iex\s|\$\{/);
  });

  it("chiqish kodlari → natija kodlari", () => {
    expect(spoolerExit(0, "")).toEqual({ ok: true });
    expect(spoolerExit(2, "").code).toBe("NO_PRINTER");
    expect(spoolerExit(3, "").code).toBe("REJECTED");
    expect(spoolerExit(4, "").code).toBe("FAILED");
    const other = spoolerExit(1, "Add-Type : compile\r\n error");
    expect(other.code).toBe("FAILED");
    expect(other.error).toContain("Add-Type : compile error");
  });

  it("PowerShell osilib qolsa → TIMEOUT va jarayon o'ldiriladi", async () => {
    const child = new FakeChild();
    const spawn = vi.fn(() => child);
    const r = await sendSpooler("XP-80", Uint8Array.from([1]), { platform: "win32", tmpdir: os.tmpdir(), spawn: spawn as never, timeoutMs: 50 });
    expect(r.code).toBe("TIMEOUT");
    expect(child.kill).toHaveBeenCalled();
  });

  // CI (ubuntu) da SKIP bo'lmasin (vitest darvozasi skip'ni "o'tmadi" deb sanaydi): har OT'da haqiqiy yo'l.
  it("HAQIQIY platforma: Windows — PowerShell C# kompilyatsiya, yo'q printer (tire+':' nomli ham) → NO_PRINTER; boshqa OT — REJECTED", async () => {
    const bytes = Uint8Array.from([0x1b, 0x40]);
    if (process.platform !== "win32") {
      const r = await sendSpooler("XP-80", bytes, { tmpdir: os.tmpdir() });
      expect(r).toMatchObject({ ok: false, code: "REJECTED" });
      expect(r.error).toContain(process.platform);
      return;
    }
    const name = `BinOS-yoq-printer-${Date.now()}`;
    const r = await sendSpooler(name, bytes, { tmpdir: os.tmpdir(), timeoutMs: 90_000 });
    expect(r).toEqual({ ok: false, code: "NO_PRINTER", error: "OpenPrinter: printer topilmadi" });
    // En-tire + ":" — `-File` argv'ni "-BinOSyoq…" va "1" ga bo'lardi: "1" fayl yo'li bo'lib (exit 1, FAILED),
    // tire esa ASCII'ga aylanib nom buzilardi. Muhit orqali — nom butun, yo'q printer → NO_PRINTER.
    const dashed = await sendSpooler(`\u2013BinOSyoq${Date.now()}:1`, bytes, { tmpdir: os.tmpdir(), timeoutMs: 90_000 });
    expect(dashed).toEqual({ ok: false, code: "NO_PRINTER", error: "OpenPrinter: printer topilmadi" });
  }, 180_000);
});

// ── ipc.ts ────────────────────────────────────────────────────────────────
type Handler = (event: unknown, ...args: unknown[]) => Promise<unknown>;

type BeforeRequest = (d: { url: string }, cb: (r: { cancel?: boolean }) => void) => void;

class FakeWindow {
  static last: FakeWindow | null = null;
  static behavior: { success: boolean; reason: string } | "hang" = { success: true, reason: "" };
  /** `loadURL` — darhol, yoki tashqaridan hal qilinadigan va'da (osilib qolgan yuklash). */
  static loadGate: Promise<void> | null = null;
  static beforeRequest: BeforeRequest | null = null;
  opts: PrintWindowOptions;
  loaded: { file: string; html: string } | null = null;
  /** Oynaga AYNAN berilgan URL (sinov uni o'zi qayta yasamaydi). */
  loadedUrl: string | null = null;
  printed: Record<string, unknown> | null = null;
  destroyed = false;
  handlers: Record<string, (...a: unknown[]) => void> = {};
  openHandler: (() => { action: string }) | null = null;
  webContents = {
    session: { webRequest: { onBeforeRequest: (fn: BeforeRequest) => { FakeWindow.beforeRequest = fn; } } },
    print: (o: Record<string, unknown>, cb: (s: boolean, r: string) => void) => {
      this.printed = o;
      const b = FakeWindow.behavior;
      if (b !== "hang") setTimeout(() => cb(b.success, b.reason), 1);
    },
    on: (ev: string, fn: (...a: unknown[]) => void) => { this.handlers[ev] = fn; },
    setWindowOpenHandler: (fn: () => { action: string }) => { this.openHandler = fn; },
  };
  constructor(opts: PrintWindowOptions) {
    this.opts = opts;
    FakeWindow.last = this;
  }
  async loadURL(url: string) {
    this.loadedUrl = url;
    // Chromium kabi: URL → fayl (noto'g'ri kodlangan URL boshqa/yo'q faylga olib borsa — xato).
    const file = fileURLToPath(url);
    this.loaded = { file, html: fs.readFileSync(file, "utf8") };
    if (FakeWindow.loadGate) await FakeWindow.loadGate;
  }
  isDestroyed() { return this.destroyed; }
  destroy() { this.destroyed = true; }
}

function setupIpc(over: Record<string, unknown> = {}) {
  const handlers: Record<string, Handler> = {};
  const ipcMain = { handle: (ch: string, fn: Handler) => { handlers[ch] = fn; } };
  const lanCalls: { host: string; port: number; bytes: Uint8Array; opts: unknown }[] = [];
  const spoolCalls: { printer: string; bytes: Uint8Array; deps: unknown }[] = [];
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "binos-ipc-"));
  registerPrintIpc({
    ipcMain, BrowserWindow: FakeWindow as never, tmpdir: tmp,
    sendLan: async (host, port, bytes, opts) => { lanCalls.push({ host, port, bytes, opts }); return { ok: true }; },
    sendSpooler: async (printer, bytes, deps) => { spoolCalls.push({ printer, bytes, deps }); return { ok: true }; },
    ...over,
  });
  const list = [
    { name: "XP-80C", displayName: "XP-80C (USB)", isDefault: true, description: "d", status: 0, options: { "printer-location": "kassa" } },
    { name: "Microsoft Print to PDF", displayName: "Microsoft Print to PDF", isDefault: false, description: "", status: 0, options: {} },
  ];
  const event = (printers: unknown[] | Error | "hang" = list) => ({
    sender: {
      getPrintersAsync: async () => {
        if (printers === "hang") return new Promise<unknown[]>(() => undefined); // spooler osilgan
        if (printers instanceof Error) throw printers;
        return printers;
      },
    },
  });
  return { handlers, lanCalls, spoolCalls, tmp, event };
}

describe("ipc.ts — main handler'lari", () => {
  afterEach(() => {
    FakeWindow.last = null;
    FakeWindow.behavior = { success: true, reason: "" };
    FakeWindow.loadGate = null;
    FakeWindow.beforeRequest = null;
  });

  it("aynan 4 kanal ro'yxatga olinadi; printerlar ro'yxati faqat nom/ko'rinish/standart", async () => {
    const { handlers, event } = setupIpc();
    expect(Object.keys(handlers).sort()).toEqual(Object.values(PRINT_IPC).sort());
    const list = await handlers[PRINT_IPC.listPrinters](event());
    expect(list).toEqual([
      { name: "XP-80C", displayName: "XP-80C (USB)", isDefault: true },
      { name: "Microsoft Print to PDF", displayName: "Microsoft Print to PDF", isDefault: false },
    ]);
    expect(await handlers[PRINT_IPC.listPrinters](event(new Error("x")))).toEqual([]);
  });

  it("ESC/POS LAN: tekshiruv → kodlash main'da → baytlar golden bilan bir xil", async () => {
    const { handlers, lanCalls, event } = setupIpc();
    const r = await handlers[PRINT_IPC.printEscPos](event(), escposReq());
    expect(r).toEqual({ ok: true });
    expect(lanCalls).toHaveLength(1);
    expect(lanCalls[0].host).toBe("192.168.1.50");
    expect(lanCalls[0].port).toBe(9100);
    expect(Buffer.from(lanCalls[0].bytes).equals(goldenBytes())).toBe(true);
    expect(lanCalls[0].opts).toMatchObject({ statusQuery: true }); // epson80 holat so'rovini qo'llaydi
  });

  it("ESC/POS LAN oxirigacha: haqiqiy sendLan → virtual printer golden baytlarni oladi", async () => {
    const printer = await vp();
    const { handlers, event } = setupIpc({
      // Tekshiruv 192.168.x ni o'tkazadi; sinovda ulanishni mahalliy virtual printerga yo'naltiramiz.
      sendLan: (_h: string, _p: number, bytes: Uint8Array, o: Record<string, unknown>) =>
        sendLan("127.0.0.1", printer.port, bytes, { ...o, statusQuery: false }),
    });
    const r = await handlers[PRINT_IPC.printEscPos](event(), escposReq({ copies: 1 }));
    expect(r).toEqual({ ok: true });
    await printer.closed;
    expect(printer.received().equals(goldenBytes())).toBe(true);
  });

  it("ESC/POS: in'ektsiya satri printerga buyruq bo'lib ketmaydi (ESC p yo'q, begona buyruq yo'q)", async () => {
    const { handlers, lanCalls, event } = setupIpc();
    const d = goldenDoc();
    d.blocks.unshift({ t: "line", text: "Sut \x1b\x70\x00\x19\xfa drawer \x1d\x56\x00 \x10\x14\x01" });
    const r = await handlers[PRINT_IPC.printEscPos](event(), escposReq({ doc: d }));
    expect(r).toMatchObject({ ok: true });
    const bytes = lanCalls[0].bytes;
    const cmds = parseEscPos(bytes);
    expect(cmds.filter((c) => c.cmd === "UNKNOWN" || c.cmd === "TRUNCATED")).toEqual([]);
    const buf = Buffer.from(bytes);
    expect(buf.indexOf(Buffer.from([0x1b, 0x70]))).toBe(-1); // ESC p — pul qutisi
    expect(buf.indexOf(Buffer.from([0x10, 0x14]))).toBe(-1); // DLE DC4 — real-time buyruq
  });

  it("ESC/POS: xom bayt, tizim printeri, ommaviy IP → REJECTED; hech narsa yuborilmaydi", async () => {
    const { handlers, lanCalls, spoolCalls, event } = setupIpc();
    for (const req of [
      escposReq({ bytes: [0x1b, 0x70, 0x00, 0x19, 0xfa] }),
      escposReq({ target: { kind: "system" } }),
      escposReq({ target: { kind: "lan", host: "93.184.216.34", port: 9100 } }),
      escposReq({ target: { kind: "lan", host: "192.168.1.50", port: 22 } }),
    ]) {
      const r = (await handlers[PRINT_IPC.printEscPos](event(), req)) as { ok: boolean; code: string };
      expect(r.ok).toBe(false);
      expect(r.code).toBe("REJECTED");
    }
    expect(lanCalls).toEqual([]);
    expect(spoolCalls).toEqual([]);
  });

  it("ESC/POS spooler: printer OS ro'yxatida bo'lishi shart", async () => {
    const { handlers, spoolCalls, tmp, event } = setupIpc();
    const miss = (await handlers[PRINT_IPC.printEscPos](event(), escposReq({ target: { kind: "spooler", printer: "Yoq-printer" } }))) as { code: string };
    expect(miss.code).toBe("NO_PRINTER");
    const fail = (await handlers[PRINT_IPC.printEscPos](event(new Error("x")), escposReq({ target: { kind: "spooler", printer: "XP-80C" } }))) as { code: string };
    expect(fail.code).toBe("NO_PRINTER"); // ro'yxat olinmasa — tekshirib bo'lmaydi, yubormaymiz
    expect(spoolCalls).toEqual([]);
    const ok = await handlers[PRINT_IPC.printEscPos](event(), escposReq({ target: { kind: "spooler", printer: "XP-80C" }, copies: 2 }));
    expect(ok).toEqual({ ok: true });
    expect(spoolCalls).toHaveLength(1);
    expect(spoolCalls[0].printer).toBe("XP-80C");
    expect(spoolCalls[0].deps).toMatchObject({ tmpdir: tmp });
    // 2 nusxa = 2 ta ESC @ ... kesish ketma-ketligi.
    expect(parseEscPos(spoolCalls[0].bytes).filter((c) => c.cmd === "ESC @")).toHaveLength(2);
  });

  it("HTML: yashirin oyna javascript:false/sandbox, CSP qo'shiladi, haqiqiy natija, fayl o'chiriladi", async () => {
    const { handlers, tmp, event } = setupIpc();
    const html = "<!doctype html><html><head><title>x</title></head><body><img src=\"http://evil/x.png\"></body></html>";
    const r = await handlers[PRINT_IPC.printHtml](event(), { html, printer: "XP-80C", widthMm: 80, copies: 2 });
    expect(r).toEqual({ ok: true });
    const w = FakeWindow.last!;
    expect(w.opts.show).toBe(false);
    expect(w.opts.webPreferences).toMatchObject({ javascript: false, sandbox: true, contextIsolation: true, nodeIntegration: false });
    expect(w.loaded!.html.startsWith(`<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"></head>`)).toBe(true);
    expect(w.printed).toMatchObject({ silent: true, deviceName: "XP-80C", copies: 2, margins: { marginType: "none" } });
    expect(w.printed).not.toHaveProperty("pageSize"); // eski renderer (pageMode yo'q) — drayver qog'ozi
    expect(w.destroyed).toBe(true);
    const ev = { preventDefault: vi.fn() };
    w.handlers["will-navigate"](ev);
    expect(ev.preventDefault).toHaveBeenCalled();
    expect(w.openHandler!()).toEqual({ action: "deny" });
    expect(fs.readdirSync(tmp)).toEqual([]);
  });

  it("HTML: printer ro'yxatda yo'q → NO_PRINTER (oyna ochilmaydi); standart printer — deviceName yo'q", async () => {
    const { handlers, event } = setupIpc();
    const r = (await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", printer: "Boshqa", widthMm: 58 })) as { code: string };
    expect(r.code).toBe("NO_PRINTER");
    expect(FakeWindow.last).toBeNull();
    const none = (await handlers[PRINT_IPC.printHtml](event([]), { html: "<p>x</p>", widthMm: 58 })) as { code: string };
    expect(none.code).toBe("NO_PRINTER");
    const def = await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 58 });
    expect(def).toEqual({ ok: true });
    expect(FakeWindow.last!.printed).not.toHaveProperty("deviceName");
  });

  it("HTML: drayver xatosi haqiqiy natija bo'lib qaytadi (ilgari doim ok:true edi)", async () => {
    const { handlers, event } = setupIpc();
    for (const [reason, code] of [["Invalid deviceName provided", "NO_PRINTER"], ["cancelled", "REJECTED"], ["failed", "FAILED"]]) {
      FakeWindow.behavior = { success: false, reason };
      const r = (await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 80 })) as { ok: boolean; code: string };
      expect(r.ok).toBe(false);
      expect(r.code).toBe(code);
      expect(FakeWindow.last!.destroyed).toBe(true);
    }
  });

  it("HTML: print javob bermasa → TIMEOUT, oyna yopiladi", async () => {
    FakeWindow.behavior = "hang";
    const { handlers, event } = setupIpc({ printTimeoutMs: 50 });
    const r = (await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 80 })) as { code: string };
    expect(r.code).toBe("TIMEOUT");
    expect(FakeWindow.last!.destroyed).toBe(true);
  });

  it("HTML: yaroqsiz so'rov → REJECTED; eski `savdoos:print` kanali {ok} qaytaradi", async () => {
    const { handlers, event } = setupIpc();
    expect(await handlers[PRINT_IPC.printHtml](event(), { html: "<p/>", widthMm: 70 })).toMatchObject({ ok: false, code: "REJECTED" });
    expect(await handlers[PRINT_IPC.print](event(), { html: "<p>x</p>", deviceName: "XP-80C" })).toEqual({ ok: true });
    expect(await handlers[PRINT_IPC.print](event(), { html: "<p>x</p>", deviceName: "Yoq" })).toEqual({ ok: false, error: "NO_PRINTER" });
    expect((await handlers[PRINT_IPC.print](event(), { html: 5 }) as { ok: boolean }).ok).toBe(false);
  });

  it("withPrintCsp: QAT'IY prefiks — izohdagi <head> yoki head'dan oldingi kontent CSP'ni chetlab o'tmaydi", () => {
    const PREFIX = `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"></head>`;
    for (const html of [
      "<p>x</p>",
      '<HTML><HEAD lang="uz"><title>t</title>',
      // Hujum: regex izohdagi <head> ni topib meta'ni izoh ichiga (head'dan tashqariga) qo'yardi.
      '<!-- <head> --><iframe src="file:///C:/Users/u/AppData/Roaming/x"></iframe><img src="http://host/x">',
      // Hujum: <head> dan oldingi kontent parser'ni body'ga o'tkazadi — keyingi meta e'tiborsiz.
      "<img src=http://host/x><head></head>",
    ]) {
      const out = withPrintCsp(html);
      expect(out.startsWith(PREFIX), html).toBe(true);
      expect(out.slice(PREFIX.length)).toBe(html); // renderer HTML'i o'zgarmaydi, faqat oldidan
    }
    expect(failureCode("No printers available on the network")).toBe("NO_PRINTER");
    expect(failureCode("")).toBe("FAILED");
  });

  it("HTML: alohida sessiya (partition) — faqat data: va AYNAN shu chekning temp fayli yuklanadi", async () => {
    FakeWindow.behavior = "hang"; // print chaqirilganda tekshiramiz, keyin muddat bilan tugaydi
    const { handlers, event } = setupIpc({ printTimeoutMs: 150 });
    const p = handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 80 });
    await vi.waitFor(() => expect(FakeWindow.last?.printed).toBeTruthy());
    const w = FakeWindow.last!;
    expect(w.opts.webPreferences.partition).toBe(PRINT_PARTITION);
    expect(PRINT_PARTITION.startsWith("persist:")).toBe(false); // xotiradagi sessiya
    const guard = FakeWindow.beforeRequest!;
    expect(typeof guard).toBe("function");
    const ask = (url: string) => new Promise<boolean>((resolve) => guard({ url }, (r) => resolve(!r.cancel)));
    const own = w.loadedUrl!; // oynaga berilgan URL'ning o'zi
    expect(own).toBe(pathToFileURL(w.loaded!.file).href);
    const during = {
      own: await ask(own),
      data: await ask("data:image/png;base64,AAAA"),
      http: await ask("http://host/x.png"),
      https: await ask("https://evil.example/"),
      otherFile: await ask(pathToFileURL(path.join(os.tmpdir(), "boshqa.html")).href),
      appData: await ask("file:///C:/Users/u/AppData/Roaming/SavdoOS%20POS/Local%20Storage/leveldb/000003.log"),
    };
    expect(during).toEqual({ own: true, data: true, http: false, https: false, otherFile: false, appData: false });
    expect(await p).toMatchObject({ ok: false, code: "TIMEOUT" });
    // Chop etish tugagach o'sha fayl ham ruxsatdan chiqadi.
    expect(printRequestAllowed(own)).toBe(false);
    expect(printRequestAllowed(undefined)).toBe(false);
  });

  it("5F.2 R5: temp yo'lda yolg'iz '%', bo'shliq, kirill — chekning O'ZI yuklanadi; boshqa fayl baribir yopiq", async () => {
    // Masalan Windows profili `C:\Users\Kassa100%`: '%' dan keyin 2 ta hex yo'q.
    const base = fs.mkdtempSync(path.join(os.tmpdir(), "binos-100%-"));
    const tmpdir = path.join(base, "Kassa 100% Жд ü");
    fs.mkdirSync(tmpdir);
    FakeWindow.behavior = "hang";
    const { handlers, event } = setupIpc({ tmpdir, printTimeoutMs: 300 });
    const p = handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 80 });
    await vi.waitFor(() => expect(FakeWindow.last?.printed).toBeTruthy());
    const w = FakeWindow.last!;
    const guard = FakeWindow.beforeRequest!;
    const ask = (url: string) => new Promise<boolean>((resolve) => guard({ url }, (r) => resolve(!r.cancel)));
    const file = w.loaded!.file;
    expect(file.startsWith(tmpdir)).toBe(true);
    expect(w.loaded!.html).toContain("<p>x</p>"); // oynaga berilgan URL AYNI temp faylga olib boradi
    // 1) Oynaga AYNAN berilgan URL (sinov uni qayta yasamaydi) — himoyadan o'tadi.
    const given = w.loadedUrl!;
    expect(given).toContain("%25"); // '%' kodlangan
    // 2) `loadFile` uslubidagi URL: '%' KODLANMAGAN (Chromium shunday qoldiradi), bo'shliq/kirill kodlangan.
    const posix = file.split(path.sep).join("/");
    const raw = "file://" + (posix.startsWith("/") ? "" : "/") +
      posix.replace(/[^A-Za-z0-9\-._~!$&'()*+,;=:@/%]/g, (c) => encodeURIComponent(c));
    expect(raw).toMatch(/%(?![0-9a-fA-F]{2})/);
    // 3) 8.3 qisqa / uzun nom: haqiqiy (uzun) yo'l ham o'sha fayl.
    const real = fs.realpathSync.native(file);
    const during = {
      given: await ask(given),
      raw: await ask(raw),
      real: await ask(pathToFileURL(real).href),
      sibling: await ask(pathToFileURL(path.join(path.dirname(file), "boshqa.html")).href),
      parentDir: await ask(pathToFileURL(path.join(tmpdir, "receipt.html")).href),
    };
    expect(during).toEqual({ given: true, raw: true, real: true, sibling: false, parentDir: false });
    // UNC so'rovi — FS'ga (tarmoqqa) tegmasdan rad etiladi.
    const rp = vi.spyOn(fs.realpathSync, "native");
    try {
      expect(await ask("file://evil-host/share/binos-print-x/receipt.html")).toBe(false);
      expect(rp).not.toHaveBeenCalled();
    } finally {
      rp.mockRestore();
    }
    expect(await p).toMatchObject({ ok: false, code: "TIMEOUT" });
    expect(printRequestAllowed(given)).toBe(false); // chop etish tugadi — ruxsat yo'q
    expect(printRequestAllowed(raw)).toBe(false);
    fs.rmSync(base, { recursive: true, force: true });
  });

  it("HTML: pageMode exact → pageSize = kenglik × balandlik (mikron); driver/yo'q → drayver qog'ozi", async () => {
    const { handlers, event } = setupIpc();
    await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 80, heightMm: 157, pageMode: "exact" });
    expect(FakeWindow.last!.printed).toMatchObject({ pageSize: { width: 80_000, height: 157_000 } });
    await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 58, heightMm: 3276, pageMode: "exact" });
    expect(FakeWindow.last!.printed).toMatchObject({ pageSize: { width: 58_000, height: 3_276_000 } });
    await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 58, heightMm: 157, pageMode: "driver" });
    expect(FakeWindow.last!.printed).not.toHaveProperty("pageSize");
    await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 58, pageMode: "exact" });
    expect(FakeWindow.last!.printed).not.toHaveProperty("pageSize"); // balandlik yo'q — taxmin qilinmaydi
    const bad = await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 58, heightMm: 5000, pageMode: "exact" });
    expect(bad).toMatchObject({ ok: false, code: "REJECTED" });
  });

  it("printer ro'yxati osilsa (spooler) → TIMEOUT; print oynasi OCHILMAYDI, navbat bo'shaydi", async () => {
    const { handlers, spoolCalls, event } = setupIpc({ printerListTimeoutMs: 40 });
    const t0 = Date.now();
    const html = await handlers[PRINT_IPC.printHtml](event("hang"), { html: "<p>x</p>", widthMm: 80 });
    expect(html).toMatchObject({ ok: false, code: "TIMEOUT" });
    const named = await handlers[PRINT_IPC.printHtml](event("hang"), { html: "<p>x</p>", widthMm: 80, printer: "XP-80C" });
    expect(named).toMatchObject({ ok: false, code: "TIMEOUT" });
    expect(FakeWindow.last).toBeNull(); // webContents.print ga o'tilmadi (UI oqimi qotmaydi)
    const esc = await handlers[PRINT_IPC.printEscPos](event("hang"), escposReq({ target: { kind: "spooler", printer: "XP-80C" } }));
    expect(esc).toMatchObject({ ok: false, code: "TIMEOUT" });
    expect(spoolCalls).toEqual([]);
    expect(await handlers[PRINT_IPC.listPrinters](event("hang"))).toEqual([]);
    expect(await handlers[PRINT_IPC.print](event("hang"), { html: "<p>x</p>" })).toEqual({ ok: false, error: "TIMEOUT" });
    expect(FakeWindow.last).toBeNull();
    expect(Date.now() - t0).toBeLessThan(5000);
    // Keyingi (sog') so'rov odatdagidek ishlaydi.
    expect(await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 80 })).toEqual({ ok: true });
  });

  it("HTML: fayl yuklash (loadURL) osilsa ham muddat ishlaydi; kech yuklansa ham print CHAQIRILMAYDI", async () => {
    let release: () => void = () => undefined;
    FakeWindow.loadGate = new Promise<void>((r) => { release = r; });
    const { handlers, tmp, event } = setupIpc({ printTimeoutMs: 60 });
    const r = await handlers[PRINT_IPC.printHtml](event(), { html: "<p>x</p>", widthMm: 80 });
    expect(r).toMatchObject({ ok: false, code: "TIMEOUT" });
    const w = FakeWindow.last!;
    expect(w.destroyed).toBe(true);
    release(); // yuklash kech tugadi — muddat o'tgan, chop etish davom ETMAYDI
    await new Promise((res) => setTimeout(res, 30));
    expect(w.printed).toBeNull();
    expect(fs.readdirSync(tmp)).toEqual([]);
  });
});

// ── alias'siz yig'ilish va kanal nomlari ──────────────────────────────────
describe("Electron main uchun yaroqlilik", () => {
  const PRINT = path.join(ROOT, "packages", "shared", "src", "print");
  const files = [path.join(PRINT, "bridge.ts"), ...fs.readdirSync(path.join(PRINT, "node")).map((f) => path.join(PRINT, "node", f))];

  it("print/** faqat nisbiy yoki node: importlar ishlatadi (`@/` yo'q)", () => {
    for (const f of files) {
      const src = fs.readFileSync(f, "utf8");
      const specs = [...src.matchAll(/(?:import|export)\s[^;]*?from\s+["']([^"']+)["']/g)].map((m) => m[1]);
      expect(specs.length, f).toBeGreaterThan(0);
      for (const s of specs) expect(s, `${path.basename(f)}: ${s}`).toMatch(/^(\.\.?\/[a-z0-9./]+|node:[a-z_]+)$/);
      expect(src, f).not.toMatch(/from\s+["']@\//);
      // Izohlarsiz kod: renderer global'lari (Electron main'da yo'q) ishlatilmaydi.
      const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
      expect(code, f).not.toMatch(/\blocalStorage\b|\bdocument\.|\bwindow\.|from\s+["']react/);
    }
  });

  it("ipc.ts esbuild bilan alias'siz yig'iladi; tashqi bog'liqlik faqat node builtin", () => {
    const script =
      'const r=require("esbuild").buildSync({entryPoints:[process.argv[1]],bundle:true,platform:"node",' +
      'format:"cjs",write:false,logLevel:"error"});process.stdout.write(r.outputFiles[0].text);';
    const code = execFileSync(process.execPath, ["-e", script, path.join(PRINT, "node", "ipc.ts")], {
      cwd: ROOT, encoding: "utf8", maxBuffer: 16 * 1024 * 1024,
    });
    const reqs = [...code.matchAll(/require\("([^"]+)"\)/g)].map((m) => m[1]);
    expect(reqs.length).toBeGreaterThan(0);
    for (const r of reqs) expect(r).toMatch(/^node:/);
    expect(code).toContain(PRINT_IPC.printEscPos);
  });

  it("preload (POS va Manager) PRINT_IPC kanallarini AYNAN ishlatadi; main registerPrintIpc chaqiradi", () => {
    for (const app of ["pos", "manager"]) {
      const pre = fs.readFileSync(path.join(ROOT, "apps", app, "electron", "preload.ts"), "utf8");
      for (const ch of Object.values(PRINT_IPC)) expect(pre, `${app}: ${ch}`).toContain(`"${ch}"`);
      expect(pre).toMatch(/printHtml:\s*\(req: unknown\) => ipcRenderer\.invoke\("savdoos:print-html", req\)/);
      expect(pre).toMatch(/printEscPos:\s*\(req: unknown\) => ipcRenderer\.invoke\("savdoos:print-escpos", req\)/);
      const main = fs.readFileSync(path.join(ROOT, "apps", app, "electron", "main.ts"), "utf8");
      expect(main).toContain('from "../../../packages/shared/src/print/node/ipc"');
      expect(main).toContain("registerPrintIpc({ ipcMain, BrowserWindow, tmpdir: app.getPath(\"temp\") })");
      expect(main).not.toMatch(/ipcMain\.handle\("savdoos:print/);
    }
  });
});
