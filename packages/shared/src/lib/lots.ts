// PARTIYA / MUDDAT — server bilan yagona shartnoma (Phase 4B).
//
// ⚠️  BU YERDA BIZNES QARORI QABUL QILINMAYDI. «Muddati o'tganmi», «tannarx
//     aniqmi», «qancha bog'lash mumkin» — hammasi SERVERDA hisoblanadi va shu
//     yerda faqat TIPLASHTIRILADI. Frontend o'z hisobini yuritsa, u filial
//     biznes sanasini va FEFO qoidalarini bilmagani uchun ekran bilan hisobot
//     BOSHQA-BOSHQA haqiqatni ko'rsatardi.
import { get, post } from "@/lib/api";

export type CostBasis = "known" | "estimated" | "unknown";
export type Bucket = "expired" | "expires_today" | "within_7_days" | "within_30_days" | "later" | "no_expiry";

export interface LotRow {
  id: string; branch_id: string; branch: string | null;
  product_id: string; product: string | null; unit_code: string | null;
  product_archived?: boolean;
  batch_number: string | null; expiry_date: string | null;
  bucket: Bucket; expired: boolean; days_left: number | null;
  received_qty: number; remaining_qty: number; unit_cost: number; value: number;
  cost_basis: CostBasis; status: string; source_type: string | null;
  supplier_id: string | null; supplier: string | null; received_at: string | null;
}

export interface LotList {
  total: number; limit: number; offset: number;
  business_dates: Record<string, string>; lots: LotRow[];
  redacted?: { purchasing: boolean };
}

export interface LotDetail extends LotRow {
  track_lots: boolean | null; track_expiry: boolean | null; business_date: string;
  created_at: string | null; updated_at: string | null;
  source: {
    type: string | null; receiving_id: string | null; purchase_item_id: string | null;
    external_lot_id: string | null;
    receiving: { id: string; source: string | null; created_at: string | null; committed_at: string | null } | null;
    purchase: { id: string; doc_no: string | null; purchase_date: string | null; total: number; status: string; supplier_id: string | null } | null;
  };
  totals: { sold_qty: number; returned_qty: number; movement_qty: number; resolved_qty: number };
  // Ro'yxatlar `history_limit` qator bilan cheklangan; jami qator soni — shu yerda.
  history_counts?: { sales: number; returns: number; movements: number; resolutions: number };
  history_limit?: number;
  // ⚠️  RUXSAT BILAN YOPILGAN qiymat null keladi (qator va kalit QOLADI). Bayroq
  //     «ko'rishga ruxsat yo'q» ni «hujjat/xodim yo'q» dan ajratadi. Ixtiyoriy —
  //     eski server ham tiplansin.
  redacted?: { purchasing: boolean; sales: boolean; staff: boolean };
  sales: { sale_id: string | null; receipt_no: string | null; sold_at: string | null; qty: number; unit_cost: number }[];
  returns: { return_id: string; return_no: string | null; created_at: string | null; qty: number; restock: boolean }[];
  movements: { movement_id: string; type: string; qty: number; reason: string | null; employee: string | null; created_at: string | null }[];
  resolutions: { id: string; shortfall_id: string; kind: string; qty: number; provisional_cost: number; actual_cost: number; variance: number; resolved_at: string | null }[];
}

export interface AlertBucket { lots: number; qty: number; value_at_risk: number }

export interface LotAlerts {
  expiry: Record<"expired" | "expires_today" | "within_7_days" | "within_30_days", AlertBucket>;
  shortfalls: { open_count: number; open_qty: number; provisional_exposure_max: number };
  cost_quality: { estimated_lots: number; unknown_cost_lots: number; tracked_products: number };
  business_dates: Record<string, string>; branches: number;
}

export interface LotAvailability {
  activation_allowed: boolean; environment: string | null; platform_environment?: string | null;
  schema_ready: boolean; schema_problem_count: number; tracked_products: number;
  // ⚠️  `schema_ready` — FAQAT sxema yaxlitligi (FK/cheklov). `activation_ready` esa
  //     `/lots/enable` darvozasining TO'LIQ to'plami: yaxlitlik + idempotentlik
  //     indekslari + uuid ustun tipi. `can_enable` aynan shunga tayanadi. Eski server
  //     bu kalitlarni yubormaydi — ixtiyoriy.
  activation_ready?: boolean;
  readiness?: { schema_integrity: boolean; idempotency: boolean; column_types: boolean };
  // ⚠️  BO'LIM KO'RINISHI — SERVER QARORI. UI `tracked_products > 0` ni o'zi
  //     hisoblasa, u na ko'rinadigan filialni, na o'chirilgan mahsulot ortidagi
  //     ochiq qarzni biladi — bo'lim jimgina g'oyib bo'lardi.
  has_lot_data: boolean; section_visible: boolean;
  permissions: { view: boolean; edit: boolean; settings: boolean; reports: boolean; purchases: boolean };
  can_enable: boolean; can_write: boolean;
  // ⚠️  `activation_allowed` (filial) — shu filialda kuzatuvni yoqish mumkinmi (server
  //     predikati: do'kon × filial ro'yxati). Eski server uni yubormaydi — ixtiyoriy.
  branches: { id: string; name: string; timezone: string | null; timezone_supported: boolean; timezone_confirmed: boolean; activation_allowed?: boolean }[];
  supported_timezones: string[];
}

export interface ShortfallRow {
  id: string; product_id: string; product: string | null; branch_id: string;
  qty: number; resolved_qty: number; open_qty: number; returned_qty: number;
  returned_unattributed_on_hand: number; unit_cost: number;
  cogs_variance: number; provisional_exposure: number; reason: string | null; created_at: string | null;
}

export interface CandidateLot {
  id: string; batch_number: string | null; expiry_date: string | null; bucket: Bucket;
  days_left: number | null; remaining_qty: number; unit_cost: number; cost_basis: CostBasis;
  source_type: string | null; own_unattributed: boolean;
  unit_variance: number; attachable_qty: number; variance_if_full: number;
}

export interface ShortfallDetail extends ShortfallRow {
  branch: string | null; unit_code: string | null; business_date: string; closed: boolean;
  resolved_real_qty: number; netted_qty: number; resolved_cost: number;
  // `sale_id`, `sale_item_id`, chek raqami, `unit_price` va `cashier` — SOTUV HUJJATI:
  // ruxsatsiz null keladi (kalit qoladi). `redacted.sales` «ruxsat yo'q» ni «chek yo'q» dan
  // ajratadi; ixtiyoriy — eski server ham tiplansin.
  sale: { sale_id: string | null; sale_item_id: string | null; receipt_no: string | null; sold_at: string | null; qty: number; unit_price: number | null; provisional_qty: number; cashier: string | null } | null;
  redacted?: { sales: boolean };
  resolutions: { id: string; kind: string; line_no: number; qty: number; stock_batch_id: string; batch_number: string | null; expiry_date: string | null; actual_unit_cost: number; variance: number; resolved_at: string | null }[];
  candidate_lots: CandidateLot[];
}

// ── So'rov qurilishi ─────────────────────────────────────────────────────────
// ⚠️  SAHIFALASH VA FILTR SERVERDA. 7137 mahsulotli katalogda «hammasini olib
//     brauzerda filtrlash» ekranni ham, serverni ham o'ldiradi.
export interface LotQuery {
  product_id?: string; branch_id?: string; expiry?: string; status?: string;
  q?: string; sort?: string; order?: string; limit?: number; offset?: number;
  tracked_only?: boolean;
}

export function lotQuery(p: LotQuery): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    u.set(k, String(v));
  }
  const s = u.toString();
  return s ? "?" + s : "";
}

export const listLots = (p: LotQuery) => get<LotList>("/lots/batches" + lotQuery(p));
export const lotDetail = (id: string) => get<LotDetail>("/lots/batches/" + id);
export const lotAlerts = (branchId?: string) =>
  get<LotAlerts>("/lots/alerts" + (branchId ? "?branch_id=" + branchId : ""));
export const lotAvailability = () => get<LotAvailability>("/lots/availability");
export const shortfallDetail = (id: string) => get<ShortfallDetail>("/lots/shortfalls/" + id);

export interface WriteoffLotIn { stock_batch_id: string; qty: number }
export interface CountLotIn { stock_batch_id: string; counted: number }
export interface CountNewLotIn { qty: number; unit_cost: number; batch_no?: string; expiry_date?: string; reason?: string }

/** Hisobdan chiqarish. `client_uuid` — ikki marta bosish qoldiqni IKKI marta kamaytirmasin. */
export const writeoff = (body: {
  product_id: string; qty: number; reason?: string; branch_id?: string;
  lots?: WriteoffLotIn[]; client_uuid: string;
}) => post<{ ok: boolean; duplicate?: boolean; cost_total?: number }>("/inventory/writeoff", body);

/** Partiya darajasidagi inventarizatsiya. */
export const countStock = (body: {
  items: { product_id: string; counted: number; lots?: CountLotIn[]; new_lots?: CountNewLotIn[] }[];
  branch_id?: string; client_uuid: string;
}) => post<{ ok: boolean; duplicate?: boolean; changed: number; results: CountResult[] }>("/inventory/count", body);

export interface CountResult {
  product: string; product_id: string; old: number; counted: number; diff: number;
  lots?: {
    decrements: { stock_batch_id: string; qty: number }[];
    surpluses: { stock_batch_id: string; qty: number }[];
    created: { stock_batch_id: string; qty: number; unit_cost: number; batch_no: string | null; expiry_date: string | null; source_type: string }[];
  };
}

/** Qarzni haqiqiy partiyalarga bog'lash (bir nechta partiya bo'lishi mumkin). */
export const resolveShortfall = (id: string, body: {
  allocations: { stock_batch_id: string; qty: number }[]; reason?: string; client_uuid: string;
}) => post<ResolveResult>(`/lots/shortfalls/${id}/resolve`, body);

export interface ResolveResult {
  ok: boolean; duplicate?: boolean; closed: boolean;
  qty_now: number; variance_now: number;
  resolved_qty: number; open_qty: number; cogs_variance: number;
}

/**
 * Miqdorni baza aniqligiga (NUMERIC(14,3)) keltiradi.
 *
 * ⚠️  FLOAT YIG'INDI. 1.1 + 2.2 brauzerda 3.3000000000000003 — u ekranda xunuk
 *     ko'rinadi va serverga shunday ketadi. Server ham kvantlaydi, lekin operator
 *     ko'rgan raqam bilan yuborilgan raqam BIR XIL bo'lishi uchun shu yerda ham.
 */
export function q3(n: number | string): number {
  // ⚠️  `n * 1000` EMAS. 0.5005 * 1000 ikkilik sonda 500.49999999999994 bo'lib,
  //     pastga yaxlitlanardi — server esa `Decimal("0.5005")` ni ROUND_HALF_UP
  //     bilan 0.501 qiladi va «yig'indi mos emas» chiqardi. O'nlik yozuvni
  //     «e3» bilan siljitish xatosiz: Number("0.5005e3") === 500.5.
  const v = Number(n);
  if (!Number.isFinite(v)) return 0;
  let str = String(v);
  // Juda kichik son `String()` da «1e-7» ko'rinishida chiqadi — «e3» qo'shib bo'lmaydi.
  if (/e/i.test(str)) str = v.toFixed(20).replace(/0+$/, "");
  const out = Math.round(Number(str + "e3")) / 1000;
  return Number.isFinite(out) ? out : 0;
}

/** Takroriy yuborishni server ANIQLASHI uchun barqaror kalit (bir marta yasaladi). */
export function newClientUuid(): string {
  const c: any = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  // Eski Electron/WebView uchun zaxira — barqarorlik muhim, kriptografik kuch emas.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (ch) => {
    const r = Math.floor(Math.random() * 16);
    const v = ch === "x" ? r : (r % 4) + 8;
    return v.toString(16);
  });
}
