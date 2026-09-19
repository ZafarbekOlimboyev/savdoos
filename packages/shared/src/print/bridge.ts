// Renderer ↔ Electron main chop etish shartnomasi (Phase 5F) — FAQAT turlar va kanal nomlari.
//
// ⚠️  Bu fayl Electron MAIN'ga ham yig'iladi (`print/node/ipc.ts` import qiladi; vite-plugin-electron
//     alias'siz): faqat nisbiy importlar, React/DOM/localStorage yo'q.
// ⚠️  Renderer HECH QACHON xom bayt yubormaydi: ESC/POS uchun `ReceiptDoc` (bloklar) + profil yuboriladi,
//     baytlarni main jarayon oq ro'yxatli kodlovchi (`receipt/escpos.ts`) bilan o'zi yasaydi. Aks holda
//     buzilgan/begona sahifa printerga istalgan buyruqni (masalan pul qutisini ochish) yubora olardi.
import type { PrinterProfile, ReceiptDoc } from "../receipt/types";

export type PrintTarget =
  | { kind: "system"; printer?: string }
  | { kind: "lan"; host: string; port: number }
  | { kind: "spooler"; printer: string };

// NO_DATA — chek ma'lumoti yo'q (server DTO olinmadi va oflayn DTO saqlanmagan); printer aybsiz.
export type PrintErrorCode = "NO_PRINTER" | "OFFLINE" | "TIMEOUT" | "PAPER_OUT" | "REJECTED" | "FAILED" | "NO_DATA";

export interface PrintResult {
  ok: boolean;
  error?: string;
  code?: PrintErrorCode;
  warnings?: string[];
}

export interface PrinterInfo {
  name: string;
  displayName?: string;
  isDefault?: boolean;
}

/**
 * `pageMode: "exact"` — main `webContents.print` ga `pageSize` = `widthMm × heightMm` beradi (sahifa chek
 * o'lchamida, bo'linmaydi). `"driver"` yoki yo'q (eski renderer) — drayverning standart qog'ozi (avvalgi xulq);
 * renderer bunda HTML `@page` ga ham o'lcham YOZMAYDI (aks holda Chromium sahifani qisib, o'rtaga qo'yardi).
 * 3276 mm dan uzun chek "exact" sozlamada ham "driver" bo'lib ketadi (oxirgi sahifa 3 m bo'sh bo'lmasin).
 */
export type PrintPageMode = "exact" | "driver";

export interface PrintHtmlRequest {
  html: string;
  printer?: string;
  widthMm: 58 | 80;
  /** Chek balandligi (mm, butun, 20..3276) — `pageMode: "exact"` uchun. */
  heightMm?: number;
  pageMode?: PrintPageMode;
  copies?: number;
}

export interface PrintEscPosRequest {
  doc: ReceiptDoc;
  profile: PrinterProfile;
  target: PrintTarget;
  copies?: number;
  cut?: boolean;
}

export interface SavdoosPrintBridge {
  listPrinters(): Promise<PrinterInfo[]>;
  /** ESKI (0.7.x) — saqlanadi; yangi kod `printHtml` ishlatadi. */
  print(html: string, deviceName?: string): Promise<{ ok: boolean }>;
  printHtml(req: PrintHtmlRequest): Promise<PrintResult>;
  printEscPos(req: PrintEscPosRequest): Promise<PrintResult>;
}

/** Sinov/e2e "virtual printer": bor bo'lsa haqiqiy printer o'rniga shu chaqiriladi. */
export interface VirtualPrintRequest {
  kind: "html" | "escpos";
  html?: string;
  doc: ReceiptDoc;
  copy: { kind: "ORIGINAL" | "REPRINT"; no?: number } | null;
  profile?: PrinterProfile;
  copies?: number;
}
export type VirtualPrinter = (req: VirtualPrintRequest) => PrintResult | void | Promise<PrintResult | void>;

/** IPC kanal nomlari — main (`ipc.ts`) va preload bir xil satrni ishlatsin (sinov solishtiradi). */
export const PRINT_IPC = Object.freeze({
  listPrinters: "savdoos:list-printers",
  print: "savdoos:print",
  printHtml: "savdoos:print-html",
  printEscPos: "savdoos:print-escpos",
} as const);

declare global {
  interface Window {
    savdoosPrint?: SavdoosPrintBridge;
    __BINOS_VIRTUAL_PRINTER__?: VirtualPrinter;
  }
}
