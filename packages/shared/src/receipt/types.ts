// Chek kutubxonasi turlari (Phase 5F) — server `binos.receipt.v1` DTO'si bilan AYNAN bir xil shakl.
//
// ⚠️  Bu papka (`receipt/`) Electron MAIN jarayoniga ham yig'iladi (vite-plugin-electron, alias YO'Q):
//     faqat nisbiy importlar; React, `@/`, window/document/localStorage, zustand TAQIQLANGAN.
//     `tests/receipt-purity.test.ts` buni statik tekshiradi va paketni alias'siz yig'ib ko'radi.

export type ReceiptLang = "uz" | "uzc" | "ru" | "ky";
export type PaperWidth = 58 | 80;

/** Pul: aniq 2 kasr xonali satr ("4224.00"). Float EMAS — yaxlitlash xatosi chekka chiqmasin. */
export type Money = string;
/** Miqdor: aniq 3 kasr xonali satr ("0.352"). */
export type Qty = string;

export type PayMethod = "cash" | "card" | "qr" | "credit";
export type QrMode = "none" | "receipt_id" | "store_url";

/** Samarali shablon: §1 maydonlari (printer/logo_id/qr_url dan tashqari). */
export interface ReceiptTemplate {
  header: string | null;
  footer: string | null;
  show_barcode: boolean;
  store_display_name: string | null;
  address: string | null;
  phone: string | null;
  width_mm: PaperWidth;
  lang: ReceiptLang | null;
  show_logo: boolean;
  show_branch: boolean;
  show_stir: boolean;
  show_cashier: boolean;
  show_till: boolean;
  show_payment_breakdown: boolean;
  show_discount: boolean;
  show_customer: boolean;
  qr_mode: QrMode;
  auto_cut: boolean;
  copies: number;
  auto_print: boolean;
}

/** Server BUILTIN standarti (§1) — oflayn namuna va vaqtinchalik chek shu bilan quriladi. */
export const BUILTIN_TEMPLATE: Readonly<ReceiptTemplate> = Object.freeze({
  header: null,
  footer: null,
  show_barcode: false,
  store_display_name: null,
  address: null,
  phone: null,
  width_mm: 80,
  lang: null,
  show_logo: true,
  show_branch: true,
  show_stir: true,
  show_cashier: true,
  show_till: false,
  show_payment_breakdown: true,
  show_discount: true,
  show_customer: false,
  qr_mode: "none",
  auto_cut: true,
  copies: 1,
  auto_print: false,
});

export interface ReceiptLine {
  name: string;
  qty: Qty;
  unit: string | null;
  weighted: boolean;
  unit_price: Money;
  gross: Money;
  discount: Money;
  total: Money;
}

export interface ReceiptPayment {
  method: PayMethod;
  amount: Money;
  given: Money | null;
  change: Money | null;
}

export interface ReceiptDTO {
  schema: "binos.receipt.v1";
  kind: "SALE" | "RETURN";
  /** Faqat /receipt/sample uchun true. */
  test: boolean;
  /** Faqat mijozda qurilgan oflayn chek uchun true. */
  provisional: boolean;
  doc: {
    id: string | null;
    number: string;
    uid: string | null;
    issued_at: string;
    issued_at_local: string;
    tz: string;
    is_offline: boolean;
    status: string;
  };
  store: {
    name: string;
    branch_name: string | null;
    address: string | null;
    phone: string | null;
    stir: string | null;
  };
  actor: { cashier: string | null; till_code: string | null; terminal: string | null };
  /** show_customer VA sotuvda xaridor bo'lsagina; aks holda null (maxfiylik). */
  customer: { name: string } | null;
  lines: ReceiptLine[];
  totals: {
    currency: string;
    subtotal: Money;
    line_discount: Money;
    doc_discount: Money;
    rounding: Money;
    total: Money;
  };
  payments: ReceiptPayment[];
  /** RETURN: pul qaysi usulda qaytarildi (musbat summa). */
  refund: { method: PayMethod; amount: Money } | null;
  /** RETURN: asl chekka havola; chekSIZ qaytarishda null. */
  original: { id: string | null; number: string; uid: string | null; issued_at_local: string | null } | null;
  barcode: { format: "CODE128"; payload: string; modules: string } | null;
  qr: { kind: "receipt_id" | "store_url"; payload: string; size: number; matrix: string[] } | null;
  logo: { id: string; sha256: string } | null;
  template: ReceiptTemplate;
}

export interface PrinterProfile {
  id: string;
  label: string;
  width_mm: PaperWidth;
  dots: number;
  cols: number;
  cut: "none" | "partial" | "full";
  qr: "native" | "raster" | "none";
  barcode: "native" | "raster" | "none";
  raster: boolean;
  codepage: { name: "cp866" | "cp1251"; escT: number };
  status_query: boolean;
  feed_lines: number;
  /**
   * Har nusxa boshida GS ( D bilan real-vaqt DLE DC4 fn 1/2 (pul qutisi, o'chirish) ni o'chirish. Faqat
   * buyruqni hujjatlashtirgan modelda (Epson TM): klon printer noma'lum buyruqni matn qilib chiqarishi mumkin.
   */
  realtime_disable?: boolean;
}

export interface LogoVariant {
  width: number;
  height: number;
  png_data_uri: string;
  raster_b64: string;
}

export type Block =
  | { t: "logo"; width: number; height: number; raster_b64: string; png_data_uri?: string }
  | { t: "line"; text: string; bold?: boolean; size?: 1 | 2 } // text allaqachon tekislangan, uzunligi <= cols/size
  | { t: "rule"; char: "-" | "=" }
  | { t: "qr"; payload: string; size: number; matrix: string[] }
  | { t: "barcode"; payload: string; modules: string }
  | { t: "feed"; lines: number }
  | { t: "cut"; kind: "partial" | "full" };

export interface ReceiptDoc {
  width_mm: PaperWidth;
  cols: number;
  blocks: Block[];
  warnings: string[];
}

export interface RenderOptions {
  width_mm: PaperWidth;
  lang: ReceiptLang;
  template: ReceiptTemplate;
  logo?: LogoVariant | null;
  copy?: { kind: "ORIGINAL" | "REPRINT"; no?: number } | null;
}

/** Qog'oz kengligi → belgilar soni (Font A, 12×24) va chop nuqtalari (203 dpi). */
export const COLS: Readonly<Record<PaperWidth, number>> = Object.freeze({ 58: 32, 80: 48 });
export const DOTS: Readonly<Record<PaperWidth, number>> = Object.freeze({ 58: 384, 80: 576 });
