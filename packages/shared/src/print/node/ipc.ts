// Electron main: chop etish IPC handler'lari (Phase 5F). `apps/{pos,manager}/electron/main.ts` chaqiradi.
//
// ⚠️  Faqat nisbiy importlar va node builtin'lar: vite-plugin-electron main'ni `@` alias'siz yig'adi.
//     Electron turlari ham import qilinmaydi (paket `packages/shared` da o'rnatilmagan) — kerakli
//     minimal shakl quyida tuzilmaviy tur sifatida; main.ts haqiqiy `ipcMain`/`BrowserWindow` beradi.
// ⚠️  Renderer ishonchsiz: har so'rov `validate.ts` dan o'tadi; ESC/POS baytlarini FAQAT shu yerda
//     oq ro'yxatli kodlovchi yasaydi (renderer bayt yubora olmaydi); LAN — faqat xususiy IPv4:9100–9109;
//     printer nomi OS ro'yxatida bo'lishi shart.
// ⚠️  HTML chop etish oynasi: ko'rinmas, `javascript: false`, `sandbox: true`, preload'siz; o'tish/yangi
//     oyna taqiqlangan; HTML'ga qo'shimcha CSP qo'yiladi (tarmoqqa chiqa olmaydi).
import * as fs from "node:fs";
import * as path from "node:path";
import { encodeEscPos } from "../../receipt/escpos";
import { PRINT_IPC, type PrintErrorCode, type PrintResult, type PrinterInfo } from "../bridge";
import { sendLan } from "./lan";
import { sendSpooler } from "./spooler";
import {
  printerExists, validateEscPosRequest, validateHtmlRequest, validateLegacyPrint,
} from "./validate";

// ── Electron'ning bizga kerakli qismi (tuzilmaviy) ─────────────────────────────
export interface PrintSenderLike {
  getPrintersAsync(): Promise<unknown[]>;
}
export interface IpcInvokeEventLike {
  sender: PrintSenderLike;
}
export interface IpcMainLike {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  handle(channel: string, listener: (event: any, ...args: any[]) => unknown): void;
}
export interface PrintOptionsLike {
  silent: boolean;
  printBackground: boolean;
  deviceName?: string;
  margins: { marginType: "none" };
  copies: number;
}
export interface PrintWindowLike {
  loadFile(filePath: string): Promise<void>;
  isDestroyed(): boolean;
  destroy(): void;
  webContents: {
    print(options: PrintOptionsLike, callback: (success: boolean, failureReason: string) => void): void;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    on(event: any, listener: (...args: any[]) => void): unknown;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setWindowOpenHandler(handler: (details: any) => { action: "deny" }): void;
  };
}
export interface PrintWindowOptions {
  show: false;
  width: number;
  height: number;
  webPreferences: {
    javascript: false;
    sandbox: true;
    contextIsolation: true;
    nodeIntegration: false;
    webSecurity: true;
    spellcheck: false;
  };
}
export type PrintWindowCtor = new (opts: PrintWindowOptions) => PrintWindowLike;

export interface PrintIpcDeps {
  ipcMain: IpcMainLike;
  BrowserWindow: PrintWindowCtor;
  tmpdir: string;
  /** Sinov uchun almashtiriladi. */
  platform?: string;
  sendLan?: typeof sendLan;
  sendSpooler?: typeof sendSpooler;
  printTimeoutMs?: number;
}

const PRINT_TIMEOUT_MS = 60_000;
const PRINT_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'";

const rejected = (error: string, code: PrintErrorCode = "REJECTED"): PrintResult => ({ ok: false, code, error });

/** OS printerlari — faqat nom/ko'rinadigan nom/standart (drayver `options` renderer'ga chiqmaydi). */
async function printersOf(e: IpcInvokeEventLike): Promise<PrinterInfo[] | null> {
  try {
    const raw = await e.sender.getPrintersAsync();
    if (!Array.isArray(raw)) return null;
    const out: PrinterInfo[] = [];
    for (const p of raw as Record<string, unknown>[]) {
      if (!p || typeof p.name !== "string" || !p.name) continue;
      const info: PrinterInfo = { name: p.name };
      if (typeof p.displayName === "string") info.displayName = p.displayName;
      if (typeof p.isDefault === "boolean") info.isDefault = p.isDefault;
      out.push(info);
    }
    return out;
  } catch {
    return null;
  }
}

/** Bir printerga parallel ikki chek aralashib ketmasin — maqsad bo'yicha navbat. */
const queues = new Map<string, Promise<unknown>>();
function serial<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const prev = queues.get(key) ?? Promise.resolve();
  const run = prev.then(fn, fn);
  const tail = run.then(() => undefined, () => undefined);
  queues.set(key, tail);
  void tail.then(() => {
    if (queues.get(key) === tail) queues.delete(key);
  });
  return run;
}

/** Renderer yuborgan HTML ga qo'shimcha CSP: HTML generatorimiznikiga ishonmasdan ham tarmoq yopiq. */
export function withPrintCsp(html: string): string {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${PRINT_CSP}">`;
  const m = /<head(\s[^>]*)?>/i.exec(html);
  if (m) return html.slice(0, m.index + m[0].length) + meta + html.slice(m.index + m[0].length);
  return meta + html;
}

export function failureCode(reason: string): PrintErrorCode {
  const r = String(reason || "").toLowerCase();
  if (/devicename|no printer|printers available|printer not found/.test(r)) return "NO_PRINTER";
  if (/cancel|invalid printer settings/.test(r)) return "REJECTED";
  return "FAILED";
}

async function printHtmlWindow(
  deps: PrintIpcDeps,
  html: string,
  opt: { deviceName?: string; copies: number },
): Promise<PrintResult> {
  let dir: string | null = null;
  let w: PrintWindowLike | null = null;
  try {
    dir = await fs.promises.mkdtemp(path.join(deps.tmpdir, "binos-print-"));
    const file = path.join(dir, "receipt.html");
    await fs.promises.writeFile(file, withPrintCsp(html), "utf8");
    w = new deps.BrowserWindow({
      show: false,
      width: 600,
      height: 800,
      webPreferences: {
        javascript: false, sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, spellcheck: false,
      },
    });
    const wc = w.webContents;
    wc.on("will-navigate", (ev: { preventDefault(): void }) => ev.preventDefault());
    wc.on("will-redirect", (ev: { preventDefault(): void }) => ev.preventDefault());
    wc.setWindowOpenHandler(() => ({ action: "deny" }));
    await w.loadFile(file);
    const timeoutMs = deps.printTimeoutMs ?? PRINT_TIMEOUT_MS;
    const win = w;
    return await new Promise<PrintResult>((resolve) => {
      const timer = setTimeout(() => resolve(rejected(`print ${timeoutMs} ms ichida tugamadi`, "TIMEOUT")), timeoutMs);
      const opts: PrintOptionsLike = {
        silent: true,
        printBackground: true,
        margins: { marginType: "none" },
        copies: opt.copies,
      };
      if (opt.deviceName) opts.deviceName = opt.deviceName;
      win.webContents.print(opts, (success, failureReason) => {
        clearTimeout(timer);
        if (success) resolve({ ok: true });
        else resolve(rejected(String(failureReason || "failed").slice(0, 200), failureCode(failureReason)));
      });
    });
  } catch (e) {
    return rejected(`print: ${(e as Error)?.message ?? String(e)}`.slice(0, 250), "FAILED");
  } finally {
    if (w && !w.isDestroyed()) w.destroy();
    if (dir) await fs.promises.rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
}

export function registerPrintIpc(deps: PrintIpcDeps): void {
  const lan = deps.sendLan ?? sendLan;
  const spooler = deps.sendSpooler ?? sendSpooler;

  deps.ipcMain.handle(PRINT_IPC.listPrinters, async (e: IpcInvokeEventLike) => (await printersOf(e)) ?? []);

  // ESKI kanal (0.7.x): {ok} qaytaradi — endi haqiqiy natija (ilgari xatoda ham ok:true edi).
  deps.ipcMain.handle(PRINT_IPC.print, async (e: IpcInvokeEventLike, raw: unknown) => {
    const v = validateLegacyPrint(raw);
    if (!v.ok) return { ok: false, error: v.error };
    const { html, deviceName } = v.value;
    if (deviceName && !printerExists(deviceName, await printersOf(e))) return { ok: false, error: "NO_PRINTER" };
    const r = await serial(`html:${deviceName ?? ""}`, () => printHtmlWindow(deps, html, { deviceName, copies: 1 }));
    return r.ok ? { ok: true } : { ok: false, error: r.error };
  });

  deps.ipcMain.handle(PRINT_IPC.printHtml, async (e: IpcInvokeEventLike, raw: unknown): Promise<PrintResult> => {
    const v = validateHtmlRequest(raw);
    if (!v.ok) return rejected(v.error);
    const req = v.value;
    const list = await printersOf(e);
    if (req.printer) {
      if (!printerExists(req.printer, list)) return rejected(`printer topilmadi: ${req.printer}`, "NO_PRINTER");
    } else if (list && list.length === 0) {
      return rejected("tizimda printer yo'q", "NO_PRINTER");
    }
    return serial(`html:${req.printer ?? ""}`, () =>
      printHtmlWindow(deps, req.html, { deviceName: req.printer, copies: req.copies ?? 1 }));
  });

  deps.ipcMain.handle(PRINT_IPC.printEscPos, async (e: IpcInvokeEventLike, raw: unknown): Promise<PrintResult> => {
    const v = validateEscPosRequest(raw);
    if (!v.ok) return rejected(v.error);
    const req = v.value;
    const t = req.target;
    if (t.kind === "system") return rejected("ESC/POS tizim (drayver) printeriga yuborilmaydi — RAW yoki LAN tanlang");
    if (t.kind === "spooler" && !printerExists(t.printer, await printersOf(e))) {
      return rejected(`printer topilmadi: ${t.printer}`, "NO_PRINTER");
    }
    let enc: { bytes: Uint8Array; warnings: string[] };
    try {
      enc = encodeEscPos(req.doc, req.profile, { copies: req.copies ?? 1, cut: req.cut });
    } catch (err) {
      return rejected(`encode: ${(err as Error)?.message ?? String(err)}`.slice(0, 250), "FAILED");
    }
    const r = t.kind === "lan"
      ? await serial(`lan:${t.host}:${t.port}`, () => lan(t.host, t.port, enc.bytes, {
        statusQuery: req.profile.status_query,
        // Katta chek (logo, 500 qator) printer buferi to'lguncha sekin ketadi — muddat hajmga mos.
        timeoutMs: 5000 + Math.ceil(enc.bytes.length / 50),
      }))
      : await serial(`spooler:${t.printer}`, () => spooler(t.printer, enc.bytes, { tmpdir: deps.tmpdir, platform: deps.platform }));
    const warnings = [...enc.warnings, ...(r.warnings ?? [])];
    return warnings.length ? { ...r, warnings } : r;
  });
}
