// Electron main: chop etish IPC handler'lari (Phase 5F). `apps/{pos,manager}/electron/main.ts` chaqiradi.
//
// ⚠️  Faqat nisbiy importlar va node builtin'lar: vite-plugin-electron main'ni `@` alias'siz yig'adi.
//     Electron turlari ham import qilinmaydi (paket `packages/shared` da o'rnatilmagan) — kerakli
//     minimal shakl quyida tuzilmaviy tur sifatida; main.ts haqiqiy `ipcMain`/`BrowserWindow` beradi.
// ⚠️  Renderer ishonchsiz: har so'rov `validate.ts` dan o'tadi; ESC/POS baytlarini FAQAT shu yerda
//     oq ro'yxatli kodlovchi yasaydi (renderer bayt yubora olmaydi); LAN — faqat xususiy IPv4:9100–9109;
//     printer nomi OS ro'yxatida bo'lishi shart.
// ⚠️  HTML chop etish oynasi: ko'rinmas, `javascript: false`, `sandbox: true`, preload'siz; o'tish/yangi
//     oyna taqiqlangan; HTML'ga qo'shimcha CSP qo'yiladi (tarmoqqa chiqa olmaydi) va oyna ALOHIDA xotiradagi
//     sessiyada — `webRequest` shu chekning temp faylidan va data: URL'dan boshqa HAMMA so'rovni bekor qiladi
//     (HTML tahliliga bog'liq bo'lmagan ikkinchi qatlam).
// ⚠️  Hech bir chop etish osilib qolmasin: printer ro'yxati (`getPrintersAsync`) 10 s, butun HTML oynasi
//     (fayl yuklash + print) 60 s bilan cheklangan — spooler osilsa ham navbat TIMEOUT bilan bo'shaydi.
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
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
  /** Mikronda (Electron `webContents.print`): faqat `pageMode: "exact"` da. */
  pageSize?: { width: number; height: number };
}
export interface PrintRequestDetailsLike {
  url: string;
}
export interface PrintSessionLike {
  webRequest: {
    onBeforeRequest(listener: (details: PrintRequestDetailsLike, callback: (response: { cancel?: boolean }) => void) => void): void;
  };
}
export interface PrintWindowLike {
  /** `pathToFileURL` bilan O'ZIMIZ kodlagan URL ('%', '#', bo'shliq, kirill ham to'g'ri) — `loadFile` emas. */
  loadURL(url: string): Promise<void>;
  isDestroyed(): boolean;
  destroy(): void;
  webContents: {
    /** `webPreferences.partition` sessiyasi (Electron'da har doim bor). */
    session?: PrintSessionLike;
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
    /** "persist:" siz — xotiradagi alohida sessiya (asosiy oynaning cookie/keshi/ruxsatlari yo'q). */
    partition: string;
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
  printerListTimeoutMs?: number;
}

const PRINT_TIMEOUT_MS = 60_000;
const PRINTER_LIST_TIMEOUT_MS = 10_000;
const PRINT_CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'";
export const PRINT_PARTITION = "binos-print";

const rejected = (error: string, code: PrintErrorCode = "REJECTED"): PrintResult => ({ ok: false, code, error });

/** Printer ro'yxati muddatida kelmadi (spooler osilgan) — `webContents.print` ga O'TILMAYDI. */
const LIST_TIMEOUT = Symbol("printer-list-timeout");
type PrinterList = PrinterInfo[] | null | typeof LIST_TIMEOUT;

/**
 * OS printerlari — faqat nom/ko'rinadigan nom/standart (drayver `options` renderer'ga chiqmaydi).
 * Muddat bilan: Windows spooler osilsa `getPrintersAsync` hech qachon qaytmaydi — shunda LIST_TIMEOUT.
 */
async function printersOf(e: IpcInvokeEventLike, timeoutMs: number): Promise<PrinterList> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<typeof LIST_TIMEOUT>((resolve) => {
    timer = setTimeout(() => resolve(LIST_TIMEOUT), timeoutMs);
  });
  try {
    const raw = await Promise.race([Promise.resolve().then(() => e.sender.getPrintersAsync()), deadline]);
    if (raw === LIST_TIMEOUT) return LIST_TIMEOUT;
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
  } finally {
    clearTimeout(timer);
  }
}

const listTimedOut = (): PrintResult =>
  rejected("printer ro'yxati olinmadi (spooler javob bermadi)", "TIMEOUT");

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

/**
 * Renderer yuborgan HTML ga qo'shimcha CSP: HTML generatorimiznikiga ishonmasdan ham tarmoq yopiq.
 * QAT'IY PREFIKS (regex bilan `<head>` qidirilmaydi): izohdagi `<head>` yoki `<head>` dan oldingi kontent
 * meta'ni head'dan tashqariga surib, CSP'ni o'chirib qo'yardi. Prefiksdan keyin parser "after head"
 * holatida: renderer'ning doctype/`<head>` i e'tiborsiz, `<meta>/<style>/<title>` baribir head'ga tushadi.
 */
export function withPrintCsp(html: string): string {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${PRINT_CSP}">`;
  return `<!doctype html><html><head>${meta}</head>` + html;
}

/** Chop etilayotgan temp fayllar (normallashtirilgan yo'l) — sessiya faqat shularni yuklaydi. */
const activeFiles = new Set<string>();
const TMP_PREFIX = "binos-print-";
const RECEIPT_FILE = "receipt.html";
const normPath = (p: string) => {
  const r = path.resolve(p);
  return process.platform === "win32" ? r.toLowerCase() : r;
};

/**
 * file: URL → yo'l. Chromium ortidan 2 ta hex kelmagan yolg'iz '%' ni o'zgarishsiz qoldiradi, `fileURLToPath`
 * esa uni URIError bilan rad etardi (masalan profil papkasi `C:\Users\Kassa100%`) — chekning O'ZI bloklanardi.
 * Shunday '%' ni literal ("%25") deb o'qiymiz: boshqa yo'l baribir boshqa yo'l bo'lib chiqadi (ruxsat yo'q).
 */
function urlPath(url: string): string | null {
  try {
    return fileURLToPath(url);
  } catch { /* quyida */ }
  try {
    return fileURLToPath(url.replace(/%(?![0-9a-fA-F]{2})/g, "%25"));
  } catch {
    return null;
  }
}

/**
 * Haqiqiy (uzun) yo'l — 8.3 qisqa nom (`DEVELO~1`) va uzun nom bir faylga olib keladi. FS'ga faqat
 * bizning temp faylimizga o'xshagan MAHALLIY yo'l uchun tegiladi: UNC (`\\server\share`) so'rovi tekshiruvning
 * o'zida tarmoqqa chiqmasin.
 */
function realKey(p: string): string | null {
  if (/^[\\/]{2}/.test(p) || path.basename(p) !== RECEIPT_FILE || !path.basename(path.dirname(p)).startsWith(TMP_PREFIX)) {
    return null;
  }
  try {
    return normPath(fs.realpathSync.native(p));
  } catch {
    return null;
  }
}

/** Chop etish sessiyasi: data: URL va AYNAN faol temp fayl — qolgan hamma so'rov bekor. */
export function printRequestAllowed(url: unknown): boolean {
  if (typeof url !== "string") return false;
  if (url.startsWith("data:")) return true;
  if (!url.startsWith("file:")) return false;
  const p = urlPath(url);
  if (!p) return false;
  if (activeFiles.has(normPath(p))) return true;
  const real = realKey(p);
  return real !== null && activeFiles.has(real);
}

function guardSession(w: PrintWindowLike): void {
  const s = w.webContents.session;
  if (!s || !s.webRequest || typeof s.webRequest.onBeforeRequest !== "function") return;
  // Bitta sessiya — bitta tinglovchi (qayta o'rnatish avvalgisini almashtiradi; ruxsat to'plami umumiy).
  s.webRequest.onBeforeRequest((details, callback) => callback({ cancel: !printRequestAllowed(details?.url) }));
}

export function failureCode(reason: string): PrintErrorCode {
  const r = String(reason || "").toLowerCase();
  if (/devicename|no printer|printers available|printer not found/.test(r)) return "NO_PRINTER";
  if (/cancel|invalid printer settings/.test(r)) return "REJECTED";
  return "FAILED";
}

/** `pageMode: "exact"` — sahifa AYNAN chek o'lchamida (mikron); aks holda drayver qog'ozi (avvalgi xulq). */
export function pageSizeFor(opt: { widthMm?: number; heightMm?: number; pageMode?: string }): PrintOptionsLike["pageSize"] {
  if (opt.pageMode !== "exact" || !opt.widthMm || !opt.heightMm) return undefined;
  return { width: opt.widthMm * 1000, height: opt.heightMm * 1000 };
}

async function printHtmlWindow(
  deps: PrintIpcDeps,
  html: string,
  opt: { deviceName?: string; copies: number; widthMm?: number; heightMm?: number; pageMode?: string },
): Promise<PrintResult> {
  const st: { dir: string | null; keys: string[]; w: PrintWindowLike | null; over: boolean } = {
    dir: null, keys: [], w: null, over: false,
  };
  const timeoutMs = deps.printTimeoutMs ?? PRINT_TIMEOUT_MS;
  // Muddat ENG BOSHIDA boshlanadi: fayl yuklash (`loadURL`) yoki temp yozish osilsa ham oyna 60 s da yopiladi.
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<PrintResult>((resolve) => {
    timer = setTimeout(() => resolve(rejected(`print ${timeoutMs} ms ichida tugamadi`, "TIMEOUT")), timeoutMs);
  });
  // Muddat o'tgach kechikkan qadam davom ETMAYDI: TIMEOUT qaytgan chek keyin qog'ozga chiqsa, qayta
  // urinish ikkinchi nusxani chiqarardi.
  const alive = () => {
    if (st.over) throw new Error("bekor qilindi (muddat o'tdi)");
  };
  const work = async (): Promise<PrintResult> => {
    st.dir = await fs.promises.mkdtemp(path.join(deps.tmpdir, TMP_PREFIX));
    alive();
    const file = path.join(st.dir, RECEIPT_FILE);
    await fs.promises.writeFile(file, withPrintCsp(html), "utf8");
    alive();
    // Yo'lning o'zi + haqiqiy (uzun) yo'li: Chromium qaysi shaklda so'rasa ham AYNI fayl tanilsin.
    const real = realKey(file);
    st.keys = real && real !== normPath(file) ? [normPath(file), real] : [normPath(file)];
    for (const k of st.keys) activeFiles.add(k);
    const win = new deps.BrowserWindow({
      show: false,
      width: 600,
      height: 800,
      webPreferences: {
        javascript: false, sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, spellcheck: false,
        partition: PRINT_PARTITION,
      },
    });
    st.w = win;
    guardSession(win);
    const wc = win.webContents;
    wc.on("will-navigate", (ev: { preventDefault(): void }) => ev.preventDefault());
    wc.on("will-redirect", (ev: { preventDefault(): void }) => ev.preventDefault());
    wc.setWindowOpenHandler(() => ({ action: "deny" }));
    // `loadFile` URL'ni '%' ni kodlamasdan yasaydi (`Kassa100%`, `p%20q` papkalari buzilardi) — URL'ni
    // o'zimiz kodlaymiz; himoya (printRequestAllowed) ham AYNI yo'lga qaytaradi.
    await win.loadURL(pathToFileURL(file).href);
    alive();
    return await new Promise<PrintResult>((resolve) => {
      const opts: PrintOptionsLike = {
        silent: true,
        printBackground: true,
        margins: { marginType: "none" },
        copies: opt.copies,
      };
      if (opt.deviceName) opts.deviceName = opt.deviceName;
      const pageSize = pageSizeFor(opt);
      if (pageSize) opts.pageSize = pageSize;
      win.webContents.print(opts, (success, failureReason) => {
        if (success) resolve({ ok: true });
        else resolve(rejected(String(failureReason || "failed").slice(0, 200), failureCode(failureReason)));
      });
    });
  };
  const cleanup = async () => {
    const { w, keys, dir } = st;
    st.w = null;
    st.keys = [];
    st.dir = null;
    if (w && !w.isDestroyed()) w.destroy();
    for (const k of keys) activeFiles.delete(k);
    if (dir) await fs.promises.rm(dir, { recursive: true, force: true }).catch(() => undefined);
  };
  const running = work();
  try {
    return await Promise.race([running, deadline]);
  } catch (e) {
    return rejected(`print: ${(e as Error)?.message ?? String(e)}`.slice(0, 250), "FAILED");
  } finally {
    st.over = true;
    clearTimeout(timer);
    await cleanup();
    // Muddatdan keyin tugagan qadam yaratgan oyna/fayl ham tozalansin.
    void running.then(cleanup, cleanup);
  }
}

export function registerPrintIpc(deps: PrintIpcDeps): void {
  const lan = deps.sendLan ?? sendLan;
  const spooler = deps.sendSpooler ?? sendSpooler;
  const listMs = deps.printerListTimeoutMs ?? PRINTER_LIST_TIMEOUT_MS;
  const printers = (e: IpcInvokeEventLike) => printersOf(e, listMs);

  deps.ipcMain.handle(PRINT_IPC.listPrinters, async (e: IpcInvokeEventLike) => {
    const list = await printers(e);
    return list === LIST_TIMEOUT || !list ? [] : list;
  });

  // ESKI kanal (0.7.x): {ok} qaytaradi — endi haqiqiy natija (ilgari xatoda ham ok:true edi).
  deps.ipcMain.handle(PRINT_IPC.print, async (e: IpcInvokeEventLike, raw: unknown) => {
    const v = validateLegacyPrint(raw);
    if (!v.ok) return { ok: false, error: v.error };
    const { html, deviceName } = v.value;
    // Ro'yxat har holda so'raladi: spooler osilgan bo'lsa `webContents.print` UI oqimini qotirardi.
    const list = await printers(e);
    if (list === LIST_TIMEOUT) return { ok: false, error: "TIMEOUT" };
    if (deviceName && !printerExists(deviceName, list)) return { ok: false, error: "NO_PRINTER" };
    const r = await serial(`html:${deviceName ?? ""}`, () => printHtmlWindow(deps, html, { deviceName, copies: 1 }));
    return r.ok ? { ok: true } : { ok: false, error: r.error };
  });

  deps.ipcMain.handle(PRINT_IPC.printHtml, async (e: IpcInvokeEventLike, raw: unknown): Promise<PrintResult> => {
    const v = validateHtmlRequest(raw);
    if (!v.ok) return rejected(v.error);
    const req = v.value;
    const list = await printers(e);
    if (list === LIST_TIMEOUT) return listTimedOut();
    if (req.printer) {
      if (!printerExists(req.printer, list)) return rejected(`printer topilmadi: ${req.printer}`, "NO_PRINTER");
    } else if (list && list.length === 0) {
      return rejected("tizimda printer yo'q", "NO_PRINTER");
    }
    return serial(`html:${req.printer ?? ""}`, () =>
      printHtmlWindow(deps, req.html, {
        deviceName: req.printer, copies: req.copies ?? 1, widthMm: req.widthMm, heightMm: req.heightMm, pageMode: req.pageMode,
      }));
  });

  deps.ipcMain.handle(PRINT_IPC.printEscPos, async (e: IpcInvokeEventLike, raw: unknown): Promise<PrintResult> => {
    const v = validateEscPosRequest(raw);
    if (!v.ok) return rejected(v.error);
    const req = v.value;
    const t = req.target;
    if (t.kind === "system") return rejected("ESC/POS tizim (drayver) printeriga yuborilmaydi — RAW yoki LAN tanlang");
    if (t.kind === "spooler") {
      const list = await printers(e);
      if (list === LIST_TIMEOUT) return listTimedOut();
      if (!printerExists(t.printer, list)) return rejected(`printer topilmadi: ${t.printer}`, "NO_PRINTER");
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
