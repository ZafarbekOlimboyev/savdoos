// Chek chop etish runtime'i (renderer, Phase 5F): navbat, jurnal, profil keshi, uzatish.
//
// ⚠️  CHOP ETISH — SOTUVDAN KEYINGI YON TA'SIR. Bu modul sotuv/qaytarish yozish yo'lida chaqirilmaydi;
//     printer xatosi sotuv holatini, savatni yoki kassani O'ZGARTIRMAYDI — faqat shu jurnal yozuvi FAILED.
// ⚠️  BUXGALTERIYA HAQIQATI SERVERDA: onlayn hujjat cheki HAR DOIM `GET /sales|returns/{id}/receipt`
//     DTO'sidan chiziladi. Mijozda qurilgan DTO faqat oflayn (`provisional: true`) — chekda
//     "OFLAYN — VAQTINCHALIK" banneri bilan chiqadi (layout.ts).
// ⚠️  ASL CHEK BITTA: `mode: "auto"` hujjat uchun ASL chek yozuvi bo'lsa (istalgan holatda) qayta
//     chop etmaydi (StrictMode ikki marta mount, qayta render — xavfsiz). Qo'lda bosilganda: asl chek
//     chop etilmagan bo'lsa AYNAN o'sha yozuv qayta urinadi; chop etilgan bo'lsa — NUSXA (banner bilan).
// ⚠️  Jurnal localStorage'da SERVER bo'yicha ajratilgan (`cacheGet/cacheSet` → `@<serverTag>`), serverga
//     hisobot (`/print-jobs`) chop etishdan KEYIN; tarmoq bo'lmasa `flushPrintReports` keyinroq yuboradi.
// ⚠️  `printTestReceipt` hech qanday YOZISH endpoint'ini chaqirmaydi va jurnalga tushmaydi.
import { useMemo, useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import { cacheGet, cacheSet } from "@/lib/offline";
import { useAuth } from "@/store/auth";
import { useLang } from "@/store/lang";
import {
  layoutReceipt, normalizeTemplate, renderHtml, sampleReceipt,
  type LogoVariant, type PaperWidth, type ReceiptDTO, type ReceiptDoc, type ReceiptLang, type ReceiptTemplate,
  type SampleKind,
} from "@/receipt";
import type { PrintErrorCode, PrintResult, PrintTarget, VirtualPrintRequest } from "@/print/bridge";
import { effectiveProfile, hasElectronPrint, readPrinterConfig, type PrinterDeviceConfig } from "@/lib/printerConfig";

export type { PrintResult, PrintErrorCode } from "@/print/bridge";

export type JobStatus = "PENDING" | "PRINTED" | "FAILED";
export type PrintDocType = "SALE" | "RETURN";
export type PrintCopy = "ORIGINAL" | "REPRINT";

export interface LocalPrintJob {
  id: string;
  key: string;
  doc_type: PrintDocType;
  doc_id: string | null;
  client_uuid: string | null;
  copy: PrintCopy;
  copy_no: number | null;
  status: JobStatus;
  attempts: number;
  error: string | null;
  code: string | null;
  transport: string | null;
  printer: string | null;
  created_at: string;
  updated_at: string;
  printed_at: string | null;
  reported: boolean;
  provisional: boolean;
}

/** `GET /receipt/profile` javobi (kassa oflayn chop etishi uchun keshlanadi). */
export interface ReceiptProfile {
  etag: string;
  branch_id: string;
  effective: ReceiptTemplate & { printer?: string | null; logo_id?: string | null; qr_url?: string | null };
  store: ReceiptDTO["store"];
  logo: { id: string; sha256: string; variants: Partial<Record<"58" | "80", LogoVariant>> } | null;
  store_qr: { payload: string; size: number; matrix: string[] } | null;
}

export const PRINT_JOBS_KEY = "savdoos_print_jobs";
export const RECEIPT_PROFILE_KEY = "savdoos_cache_receipt_profile";
export const PRINT_ERROR_CODES: readonly PrintErrorCode[] = ["NO_PRINTER", "OFFLINE", "TIMEOUT", "PAPER_OUT", "REJECTED", "FAILED"];

const KEEP_JOBS = 300;
const HARD_CAP_JOBS = 1000; // hisobot berilmaganlar ham cheksiz o'smasin (localStorage kvotasi)
const PROFILE_TTL_MS = 5 * 60 * 1000;
const PROFILE_TIMEOUT_MS = 8000;
const PROFILE_WAIT_ON_PRINT_MS = 2500; // chop etish profilni kutib qotmasin
const DTO_TIMEOUT_MS = 10_000;
const DTO_DELAYS_MS = [0, 300, 900];
const PRE_TIMEOUT_MS = 4000; // chop etishdan OLDINGI so'rovlar (nusxa raqami, server jurnali)
const REPORT_TIMEOUT_MS = 8000;
const FLUSH_BATCH = 50;

// ── yordamchilar ────────────────────────────────────────────────────────────
let lastStamp = 0;
/** Qat'iy o'suvchi vaqt belgisi: bir millisekundda ikki o'zgarish ham farqlansin (hisobot poygasi). */
function stamp(): string {
  let t = Date.now();
  if (t <= lastStamp) t = lastStamp + 1;
  lastStamp = t;
  return new Date(t).toISOString();
}

function newId(): string {
  const c: { randomUUID?: () => string } | undefined = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (ch) => {
    const r = Math.floor(Math.random() * 16);
    return (ch === "x" ? r : (r % 4) + 8).toString(16);
  });
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function withTimeout<T>(p: Promise<T>, ms: number, fallback: T): Promise<T> {
  return new Promise<T>((resolve) => {
    const t = setTimeout(() => resolve(fallback), ms);
    p.then((v) => { clearTimeout(t); resolve(v); }, () => { clearTimeout(t); resolve(fallback); });
  });
}

type ApiError = Error & { status?: number; code?: string };
const errStatus = (e: unknown) => (e as ApiError)?.status;
const errCode = (e: unknown) => (e as ApiError)?.code;
const errText = (e: unknown) => String((e as Error)?.message ?? e ?? "").slice(0, 250);
const loggedIn = () => !!useAuth.getState().token;
const ownerId = () => useAuth.getState().employee?.id ?? null;
/** Profil keshi egasi — do'kon (kompaniya kodi): boshqa do'kon logosi/manzili hech qachon chiqmasin. */
const tenantKey = (): string | null => {
  const e = useAuth.getState().employee;
  if (!e) return null;
  return e.company_code ? `c:${e.company_code}` : `e:${e.id}`;
};
const uiLang = (): ReceiptLang => useLang.getState().lang;

export function docKey(doc_type: PrintDocType, id: string): string {
  return `${doc_type}:${id}`;
}

// ── jurnal (localStorage, server bo'yicha ajratilgan) ───────────────────────
let version = 0;
const listeners = new Set<() => void>();
let memJobs: LocalPrintJob[] | null = null; // localStorage to'lsa — seans davomida xotirada

function emit() {
  version++;
  for (const l of Array.from(listeners)) l();
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

if (typeof window !== "undefined") {
  // Boshqa oyna (masalan ikkinchi Manager oynasi) jurnalni o'zgartirsa ham ko'rinish yangilansin.
  window.addEventListener("storage", (e) => {
    if (e.key === null || e.key.startsWith(PRINT_JOBS_KEY)) emit();
  });
}

function isJob(v: unknown): v is LocalPrintJob {
  const j = v as LocalPrintJob;
  return !!j && typeof j === "object" && typeof j.id === "string" && typeof j.key === "string" &&
    (j.doc_type === "SALE" || j.doc_type === "RETURN") && (j.copy === "ORIGINAL" || j.copy === "REPRINT") &&
    (j.status === "PENDING" || j.status === "PRINTED" || j.status === "FAILED") && typeof j.created_at === "string";
}

function loadJobs(): LocalPrintJob[] {
  if (memJobs) return memJobs.map((j) => ({ ...j }));
  const raw = cacheGet<unknown>(PRINT_JOBS_KEY, []);
  return Array.isArray(raw) ? raw.filter(isJob) : [];
}

const byCreated = (a: LocalPrintJob, b: LocalPrintJob) =>
  a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0;

/** Oxirgi 300 ta; hisobot berilmagani (serverga yetmagan PENDING/FAILED/PRINTED) o'chirilmaydi. */
function trimJobs(jobs: LocalPrintJob[]): LocalPrintJob[] {
  if (jobs.length <= KEEP_JOBS) return jobs;
  const sorted = [...jobs].sort(byCreated);
  let excess = sorted.length - KEEP_JOBS;
  const drop = new Set<string>();
  for (const j of sorted) {
    if (excess <= 0) break;
    if (j.reported) {
      drop.add(j.id);
      excess--;
    }
  }
  let kept = sorted.filter((j) => !drop.has(j.id));
  if (kept.length > HARD_CAP_JOBS) kept = kept.slice(kept.length - HARD_CAP_JOBS);
  return kept;
}

function saveJobs(jobs: LocalPrintJob[]) {
  const trimmed = trimJobs(jobs);
  memJobs = cacheSet(PRINT_JOBS_KEY, trimmed) ? null : trimmed.map((j) => ({ ...j }));
  emit();
}

function getJob(id: string): LocalPrintJob | null {
  return loadJobs().find((j) => j.id === id) ?? null;
}

/** O'zgartirish; `touch` — `updated_at` yangilanadi (hisobot poygasini aniqlash uchun). */
function mutate(id: string, fn: (j: LocalPrintJob) => void, touch = true): LocalPrintJob | null {
  const jobs = loadJobs();
  const j = jobs.find((x) => x.id === id);
  if (!j) return null;
  fn(j);
  if (touch) j.updated_at = stamp();
  saveJobs(jobs);
  return { ...j };
}

function insertJob(j: LocalPrintJob): LocalPrintJob {
  const jobs = loadJobs().filter((x) => x.id !== j.id);
  jobs.push(j);
  saveJobs(jobs);
  return { ...j };
}

function matchesKey(j: LocalPrintJob, key: string): boolean {
  return j.key === key || (!!j.doc_id && docKey(j.doc_type, j.doc_id) === key) ||
    (!!j.client_uuid && docKey(j.doc_type, j.client_uuid) === key);
}

/** Jurnal (xronologik). `key` — `docKey(...)`; oflayn sotuv uchun client_uuid kaliti ham mos keladi. */
export function listJobs(filter?: { key?: string }): LocalPrintJob[] {
  const jobs = loadJobs().sort(byCreated);
  if (!filter) return jobs;
  // Bo'sh kalit — "hech biri" (hammasi EMAS): hujjati hali noma'lum ekran boshqa cheklarni ko'rmasin.
  if (filter.key === "" ) return [];
  return filter.key ? jobs.filter((j) => matchesKey(j, filter.key as string)) : jobs;
}

export function usePrintJobs(key: string): LocalPrintJob[] {
  const v = useSyncExternalStore(subscribe, () => version, () => 0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => listJobs({ key }), [v, key]);
}

function sameDoc(j: LocalPrintJob, t: PrintDocType, doc_id: string | null, client_uuid: string | null): boolean {
  return j.doc_type === t && ((!!doc_id && j.doc_id === doc_id) || (!!client_uuid && j.client_uuid === client_uuid));
}

function findOriginal(t: PrintDocType, doc_id: string | null, client_uuid: string | null): LocalPrintJob | null {
  return loadJobs().sort(byCreated).find((j) => j.copy === "ORIGINAL" && sameDoc(j, t, doc_id, client_uuid)) ?? null;
}

function newJob(p: {
  t: PrintDocType; doc_id: string | null; client_uuid: string | null; copy: PrintCopy; id?: string;
  status?: JobStatus; attempts?: number; copy_no?: number | null; reported?: boolean;
}): LocalPrintJob {
  const now = stamp();
  return insertJob({
    id: p.id ?? newId(),
    key: docKey(p.t, (p.doc_id ?? p.client_uuid) as string),
    doc_type: p.t,
    doc_id: p.doc_id,
    client_uuid: p.client_uuid,
    copy: p.copy,
    copy_no: p.copy_no ?? null,
    status: p.status ?? "PENDING",
    attempts: p.attempts ?? 0,
    error: null,
    code: null,
    transport: null,
    printer: null,
    created_at: now,
    updated_at: now,
    printed_at: null,
    reported: p.reported ?? false,
    provisional: false,
  });
}

// ── navbat: bir vaqtda bitta chek (printer va jurnal poygasiz) ──────────────
let chain: Promise<unknown> = Promise.resolve();
function enqueue<T>(fn: () => Promise<T>): Promise<T> {
  const run = chain.then(fn, fn);
  chain = run.then(() => undefined, () => undefined);
  return run;
}

/** Hujjat bo'yicha ishlayotgan chop etish — ikkinchi bosish/ikkinchi mount O'SHA va'dani oladi. */
const inflight = new Map<string, Promise<LocalPrintJob>>();
/** Mijozda qurilgan (oflayn) DTO — qayta urinish uchun. Seans xotirasi + localStorage (server bo'yicha
 *  ajratilgan): ilova oflayn sotuvdan keyin qayta ishga tushsa ham "Qayta urinish" chekni chiza olsin.
 *  Muvaffaqiyatli chop etishdan keyin o'chiriladi; ko'pi bilan PROVIDED_CAP ta (eng yangilari) saqlanadi. */
const providedDtos = new Map<string, ReceiptDTO>();
const PROVIDED_KEY = "savdoos_print_dtos";
const PROVIDED_CAP = 50;

function loadProvided(): Record<string, { at: string; dto: ReceiptDTO }> {
  const v = cacheGet<Record<string, { at: string; dto: ReceiptDTO }>>(PROVIDED_KEY, {});
  return v && typeof v === "object" ? v : {};
}

function rememberProvided(id: string, dto: ReceiptDTO): void {
  providedDtos.set(id, dto);
  try {
    const all = loadProvided();
    all[id] = { at: stamp(), dto };
    const keep = Object.entries(all).sort((a, b) => (a[1].at < b[1].at ? 1 : -1)).slice(0, PROVIDED_CAP);
    cacheSet(PROVIDED_KEY, Object.fromEntries(keep));
  } catch { /* kvota — seans xotirasi baribir bor */ }
}

function providedFor(id: string): ReceiptDTO | null {
  const m = providedDtos.get(id);
  if (m) return m;
  const hit = loadProvided()[id]?.dto;
  return hit && isDto(hit) ? hit : null;
}

function forgetProvided(id: string): void {
  providedDtos.delete(id);
  try {
    const all = loadProvided();
    if (id in all) {
      delete all[id];
      cacheSet(PROVIDED_KEY, all);
    }
  } catch { /* ignore */ }
}

function track(keys: string[], p: Promise<LocalPrintJob>): Promise<LocalPrintJob> {
  for (const k of keys) inflight.set(k, p);
  const clear = () => {
    for (const k of keys) if (inflight.get(k) === p) inflight.delete(k);
  };
  p.then(clear, clear);
  return p;
}

function jobKeys(t: PrintDocType, doc_id: string | null, client_uuid: string | null): string[] {
  const out: string[] = [];
  if (doc_id) out.push(docKey(t, doc_id));
  if (client_uuid) out.push(docKey(t, client_uuid));
  return out;
}

// ── profil (shablon + do'kon + logo bitlari), etag bilan kesh ───────────────
interface ProfileEntry { owner: string | null; emp: string | null; fetched_at: number; profile: ReceiptProfile }
const profileInflight = new Map<string, Promise<ReceiptProfile | null>>();

function readProfileEntry(bkey: string): ProfileEntry | null {
  const all = cacheGet<Record<string, ProfileEntry>>(RECEIPT_PROFILE_KEY, {});
  const e = all && typeof all === "object" ? all[bkey] : undefined;
  // Boshqa do'kon keshi (shu serverda boshqa login) — ishlatilmaydi. Ayni do'konning boshqa kassiri —
  // ishlatiladi (oflayn chekda logo/shablon yo'qolmasin), lekin eskirgan hisoblanadi (filiali boshqa bo'lishi mumkin).
  if (!e || typeof e !== "object" || !e.profile || e.owner !== tenantKey()) return null;
  return e;
}

const isFresh = (e: ProfileEntry) => e.emp === ownerId() && Date.now() - e.fetched_at < PROFILE_TTL_MS;

function writeProfileEntry(bkey: string, e: ProfileEntry) {
  const all = { ...cacheGet<Record<string, ProfileEntry>>(RECEIPT_PROFILE_KEY, {}) };
  all[bkey] = e;
  const keys = Object.keys(all).sort((a, b) => (all[b]?.fetched_at ?? 0) - (all[a]?.fetched_at ?? 0));
  for (const k of keys.slice(8)) delete all[k];
  cacheSet(RECEIPT_PROFILE_KEY, all);
}

function isProfile(v: unknown): v is ReceiptProfile {
  const p = v as ReceiptProfile;
  return !!p && typeof p === "object" && typeof p.etag === "string" && !!p.effective && typeof p.effective === "object" &&
    !!p.store && typeof p.store === "object";
}

/** Keshdagi profil (tarmoqsiz). */
export function cachedReceiptProfile(branch_id?: string): ReceiptProfile | null {
  return readProfileEntry(branch_id ?? "")?.profile ?? null;
}

export function getReceiptProfile(opts?: { force?: boolean; branch_id?: string }): Promise<ReceiptProfile | null> {
  const bkey = opts?.branch_id ?? "";
  const cached = readProfileEntry(bkey);
  if (cached && !opts?.force && isFresh(cached)) return Promise.resolve(cached.profile);
  if (!loggedIn()) return Promise.resolve(cached?.profile ?? null);
  const running = profileInflight.get(bkey);
  if (running) return running;
  const owner = tenantKey();
  const emp = ownerId();
  const p = (async () => {
    const q = new URLSearchParams();
    if (opts?.branch_id) q.set("branch_id", opts.branch_id);
    if (cached) q.set("known_etag", cached.profile.etag);
    const qs = q.toString();
    try {
      const r = await api<Record<string, unknown>>(`/receipt/profile${qs ? "?" + qs : ""}`, {}, PROFILE_TIMEOUT_MS);
      if (r && r.unchanged === true && cached && r.etag === cached.profile.etag) {
        writeProfileEntry(bkey, { ...cached, emp, fetched_at: Date.now() });
        return cached.profile;
      }
      if (isProfile(r)) {
        writeProfileEntry(bkey, { owner, emp, fetched_at: Date.now(), profile: r });
        return r;
      }
    } catch {
      /* oflayn — eski kesh bilan davom etamiz */
    }
    return cached?.profile ?? null;
  })();
  profileInflight.set(bkey, p);
  const clear = () => {
    if (profileInflight.get(bkey) === p) profileInflight.delete(bkey);
  };
  p.then(clear, clear);
  return p;
}

/** Chop etish paytida: kesh darhol; eskirgan bo'lsa fonda yangilanadi; umuman yo'q bo'lsa qisqa kutish. */
async function profileForPrint(branch_id?: string): Promise<ReceiptProfile | null> {
  const e = readProfileEntry(branch_id ?? "");
  if (e) {
    if (!isFresh(e)) void getReceiptProfile({ branch_id });
    return e.profile;
  }
  return withTimeout(getReceiptProfile({ branch_id }), PROFILE_WAIT_ON_PRINT_MS, null);
}

// Boshqa filial logosi (Manager nusxasi) — `GET /receipt/logos/{id}`; seans xotirasida.
const logoCache = new Map<string, Partial<Record<"58" | "80", LogoVariant>> | null>();

async function logoVariants(id: string): Promise<Partial<Record<"58" | "80", LogoVariant>> | null> {
  if (logoCache.has(id)) return logoCache.get(id) ?? null;
  if (!loggedIn()) return null;
  try {
    const r = await api<{ variants?: Partial<Record<"58" | "80", LogoVariant>> }>(
      `/receipt/logos/${encodeURIComponent(id)}`, {}, PRE_TIMEOUT_MS);
    const v = r && r.variants && typeof r.variants === "object" ? r.variants : null;
    logoCache.set(id, v);
    return v;
  } catch (e) {
    // Ruxsat yo'q/topilmadi — qayta so'ramaymiz; tarmoq xatosi — keyingi safar yana urinib ko'ramiz.
    if (errStatus(e) === 403 || errStatus(e) === 404) logoCache.set(id, null);
    return null;
  }
}

async function logoFor(dto: ReceiptDTO, width: PaperWidth, t: ReceiptTemplate, prof: ReceiptProfile | null) {
  if (!t.show_logo) return null;
  const w = String(width) as "58" | "80";
  if (dto.logo && typeof dto.logo.id === "string") {
    if (prof?.logo?.id === dto.logo.id) return prof.logo.variants?.[w] ?? null;
    return (await logoVariants(dto.logo.id))?.[w] ?? null;
  }
  // Oflayn/namuna DTO'da logo havolasi yo'q — kassaning keshdagi profil logosi.
  if ((dto.provisional || dto.test) && prof?.logo) return prof.logo.variants?.[w] ?? null;
  return null;
}

// ── uzatish (virtual / Electron / brauzer) ──────────────────────────────────
interface Delivery { result: PrintResult; transport: string | null; printer: string | null; doc: ReceiptDoc | null }

function normalizeResult(v: unknown): PrintResult {
  if (v === undefined || v === null) return { ok: true };
  const r = v as PrintResult;
  if (typeof r !== "object" || typeof r.ok !== "boolean") return { ok: false, code: "FAILED", error: "noto'g'ri javob" };
  const out: PrintResult = { ok: r.ok };
  if (!r.ok) out.code = PRINT_ERROR_CODES.includes(r.code as PrintErrorCode) ? r.code : "FAILED";
  if (typeof r.error === "string" && r.error) out.error = r.error.slice(0, 250);
  if (Array.isArray(r.warnings)) out.warnings = r.warnings.filter((x) => typeof x === "string").slice(0, 50);
  return out;
}

/**
 * ESC/POS so'roviga PNG kerak emas (main faqat raster bitlarini oladi) — IPC yengil bo'lsin. Layout
 * ogohlantirishlari ham yuborilmaydi: main ularni tashlaydi, buzilgan DTO'da esa ro'yxat chegaradan oshardi.
 */
function stripPng(doc: ReceiptDoc): ReceiptDoc {
  return {
    width_mm: doc.width_mm,
    cols: doc.cols,
    warnings: [],
    blocks: doc.blocks.map((b) => (b.t === "logo" ? { t: "logo", width: b.width, height: b.height, raster_b64: b.raster_b64 } : b)),
  };
}

function printViaIframe(html: string): Promise<PrintResult> {
  return new Promise<PrintResult>((resolve) => {
    try {
      const iframe = document.createElement("iframe");
      iframe.setAttribute("aria-hidden", "true");
      iframe.tabIndex = -1;
      iframe.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;";
      document.body.appendChild(iframe);
      const w = iframe.contentWindow;
      const d = w?.document;
      if (!w || !d) {
        iframe.remove();
        resolve({ ok: false, code: "FAILED", error: "iframe" });
        return;
      }
      d.open();
      d.write(html);
      d.close();
      setTimeout(() => {
        try {
          w.focus();
          w.print();
          // Brauzer dialogi natijani aytmaydi — "yuborildi" (tasdiqlanmagan), transport "browser".
          resolve({ ok: true });
        } catch (e) {
          resolve({ ok: false, code: "FAILED", error: errText(e) });
        } finally {
          setTimeout(() => iframe.remove(), 1500);
        }
      }, 300);
    } catch (e) {
      resolve({ ok: false, code: "FAILED", error: errText(e) });
    }
  });
}

async function deliver(
  dto: ReceiptDTO,
  copy: { kind: PrintCopy; no?: number } | null,
  cfg: PrinterDeviceConfig,
  branch_id?: string,
): Promise<Delivery> {
  const template = normalizeTemplate(dto.template);
  const width: PaperWidth = cfg.width_mm === 58 || cfg.width_mm === 80 ? cfg.width_mm : template.width_mm;
  const prof = await profileForPrint(branch_id);
  let d = dto;
  // Oflayn/namuna chekda do'kon QR'i serverdan kelmagan — profil keshidagi tayyor matritsa.
  if ((dto.provisional || dto.test) && !dto.qr && template.qr_mode === "store_url" && prof?.store_qr) {
    d = { ...dto, qr: { kind: "store_url", ...prof.store_qr } };
  }
  const logo = await logoFor(d, width, template, prof);
  const doc = layoutReceipt(d, { width_mm: width, lang: template.lang ?? uiLang(), template, logo, copy });
  const copies = template.copies;
  const escpos = cfg.transport === "escpos_lan" || cfg.transport === "escpos_spooler";
  const profile = effectiveProfile(cfg, width);
  const title = `${d.doc?.number ?? ""}`.slice(0, 60) || "Receipt";

  const virtual = typeof window !== "undefined" ? window.__BINOS_VIRTUAL_PRINTER__ : undefined;
  if (typeof virtual === "function") {
    const req: VirtualPrintRequest = { kind: escpos ? "escpos" : "html", doc, copy, copies };
    if (escpos) req.profile = profile;
    else req.html = renderHtml(doc, { title });
    try {
      return { result: normalizeResult(await virtual(req)), transport: "virtual", printer: null, doc };
    } catch (e) {
      return { result: { ok: false, code: "FAILED", error: errText(e) }, transport: "virtual", printer: null, doc };
    }
  }

  const bridge = typeof window !== "undefined" ? window.savdoosPrint : undefined;
  try {
    if (bridge && escpos && typeof bridge.printEscPos === "function") {
      let target: PrintTarget;
      let printer: string | null;
      if (cfg.transport === "escpos_lan") {
        if (!cfg.host) return { result: { ok: false, code: "NO_PRINTER", error: "LAN printer manzili yo'q" }, transport: cfg.transport, printer: null, doc };
        const port = cfg.port ?? 9100;
        target = { kind: "lan", host: cfg.host, port };
        printer = `${cfg.host}:${port}`;
      } else {
        if (!cfg.printer) return { result: { ok: false, code: "NO_PRINTER", error: "printer tanlanmagan" }, transport: cfg.transport, printer: null, doc };
        target = { kind: "spooler", printer: cfg.printer };
        printer = cfg.printer;
      }
      const r = await bridge.printEscPos({ doc: stripPng(doc), profile, target, copies, cut: template.auto_cut });
      return { result: normalizeResult(r), transport: cfg.transport, printer, doc };
    }
    if (bridge && cfg.transport !== "browser") {
      const html = renderHtml(doc, { title });
      const printer = cfg.printer ?? null;
      if (typeof bridge.printHtml === "function") {
        const r = await bridge.printHtml({ html, printer: printer ?? undefined, widthMm: width, copies });
        return { result: normalizeResult(r), transport: "system", printer, doc };
      }
      const r = await bridge.print(html, printer ?? undefined);
      return { result: normalizeResult(r?.ok ? { ok: true } : { ok: false, code: "FAILED" }), transport: "system", printer, doc };
    }
  } catch (e) {
    return { result: { ok: false, code: "FAILED", error: errText(e) }, transport: cfg.transport, printer: cfg.printer ?? null, doc };
  }
  const r = await printViaIframe(renderHtml(doc, { title }));
  return { result: r, transport: "browser", printer: null, doc };
}

// ── server DTO ──────────────────────────────────────────────────────────────
function isDto(v: unknown): v is ReceiptDTO {
  const d = v as ReceiptDTO;
  return !!d && typeof d === "object" && d.schema === "binos.receipt.v1" && !!d.doc && Array.isArray(d.lines);
}

async function fetchDto(t: PrintDocType, id: string): Promise<ReceiptDTO> {
  const path = `/${t === "SALE" ? "sales" : "returns"}/${encodeURIComponent(id)}/receipt`;
  let last: unknown = null;
  for (const delay of DTO_DELAYS_MS) {
    if (delay) await sleep(delay);
    try {
      const r = await api<unknown>(path, {}, DTO_TIMEOUT_MS);
      if (isDto(r)) return r;
      throw new Error("chek ma'lumoti noto'g'ri shaklda");
    } catch (e) {
      last = e;
      const st = errStatus(e);
      // 4xx — qayta urinish foydasiz (topilmadi/ruxsat yo'q); tarmoq/5xx — qayta.
      if (st !== undefined && st < 500) break;
    }
  }
  throw last instanceof Error ? last : new Error("chek olinmadi");
}

// ── server jurnali (`/print-jobs`) ──────────────────────────────────────────
interface PrintJobOut { id: string; copy_no?: number; status?: string }
type ReportOutcome = "ok" | "skipped" | "network" | "final";
/** Ishlayotgan hisobotlar: qaysi holat (`updated_at`) yuborilayotgani bilan. */
const reporting = new Map<string, { p: Promise<ReportOutcome>; snapshot: string | null }>();

function reportBody(j: LocalPrintJob): Record<string, unknown> {
  const err = j.code && j.error && !j.error.startsWith(j.code) ? `${j.code}: ${j.error}` : j.error ?? j.code;
  return {
    status: j.status,
    attempts: j.attempts,
    error: err ? err.slice(0, 300) : null,
    printer: j.printer ? j.printer.slice(0, 120) : null,
    transport: j.transport,
  };
}

function report(id: string, timeoutMs = REPORT_TIMEOUT_MS): Promise<ReportOutcome> {
  const running = reporting.get(id);
  if (running) {
    // Ishlayotgan hisobot ESKIROQ holatni yubormoqda (masalan flush PENDING'ni, chop etish esa tugadi) —
    // u tugagach yangi holat ham yuboriladi; aks holda o'sha va'dani qaytaramiz (takroriy so'rov yo'q).
    const cur = getJob(id);
    if (cur && cur.updated_at !== running.snapshot) return running.p.then(() => report(id, timeoutMs));
    return running.p;
  }
  const snap0 = getJob(id)?.updated_at ?? null;
  const p = (async (): Promise<ReportOutcome> => {
    const j = getJob(id);
    if (!j || j.reported || !j.doc_id || !loggedIn()) return "skipped";
    const snapshot = j.updated_at;
    const body = reportBody(j);
    const create = () =>
      api<PrintJobOut>("/print-jobs", {
        method: "POST",
        body: JSON.stringify({ id: j.id, doc_type: j.doc_type, doc_id: j.doc_id, copy: j.copy, ...body }),
      }, timeoutMs);
    try {
      let out: PrintJobOut;
      if (j.copy_no !== null) {
        // Server bu yozuvni biladi (copy_no oldingi javobdan) — faqat holat o'tishi.
        try {
          out = await api<PrintJobOut>(`/print-jobs/${encodeURIComponent(j.id)}`, { method: "PATCH", body: JSON.stringify(body) }, timeoutMs);
        } catch (e) {
          if (errStatus(e) !== 404) throw e;
          out = await create();
        }
      } else {
        out = await create();
      }
      mutate(id, (x) => {
        if (typeof out?.copy_no === "number") x.copy_no = out.copy_no;
        if (x.updated_at === snapshot) x.reported = true;
      }, false);
      return "ok";
    } catch (e) {
      const st = errStatus(e);
      const code = errCode(e);
      if (st === 409 && code === "PRINT_ORIGINAL_EXISTS") {
        // Boshqa qurilma asl chekni allaqachon yozgan: qayd etamiz, AVTOMATIK qayta chop ETMAYMIZ.
        mutate(id, (x) => { x.reported = true; x.error = code; x.code = code; }, false);
        return "final";
      }
      if (st === 409 || st === 400 || st === 403 || st === 404) {
        // Doimiy rad (yakunlangan holat, hujjat ko'rinmaydi, noto'g'ri so'rov) — qayta yuborish foydasiz.
        mutate(id, (x) => { x.reported = true; }, false);
        return "final";
      }
      return "network"; // tarmoq/5xx/muddat — flushPrintReports keyinroq
    }
  })();
  reporting.set(id, { p, snapshot: snap0 });
  const clear = () => {
    if (reporting.get(id)?.p === p) reporting.delete(id);
  };
  p.then(clear, clear);
  return p;
}

let flushing: Promise<void> | null = null;

/** Hisobot berilmagan yozuvlarni yuboradi (sinxronlash sikli chaqiradi). Tarmoq xatosida to'xtaydi. */
export function flushPrintReports(): Promise<void> {
  if (flushing) return flushing;
  flushing = (async () => {
    if (!loggedIn()) return;
    if (typeof navigator !== "undefined" && navigator.onLine === false) return;
    const todo = loadJobs().filter((j) => !j.reported && j.doc_id).sort(byCreated).slice(0, FLUSH_BATCH);
    for (const j of todo) {
      if ((await report(j.id)) === "network") break;
    }
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}

/** Oflayn sotuv sinxronlandi — server id ma'lum: jurnal yozuvlari shu hujjatga bog'lanadi. */
export function bindDocId(client_uuid: string, doc_id: string): void {
  if (!client_uuid || !doc_id) return;
  const jobs = loadJobs();
  let changed = false;
  for (const j of jobs) {
    if (j.client_uuid === client_uuid && !j.doc_id) {
      j.doc_id = doc_id;
      j.key = docKey(j.doc_type, doc_id);
      j.reported = false;
      j.updated_at = stamp();
      changed = true;
    }
  }
  if (changed) saveJobs(jobs);
}

async function serverJobs(t: PrintDocType, doc_id: string): Promise<PrintJobOut[] | null> {
  if (!loggedIn()) return null;
  try {
    const r = await api<PrintJobOut[]>(`/print-jobs?doc_type=${t}&doc_id=${encodeURIComponent(doc_id)}`, {}, PRE_TIMEOUT_MS);
    return Array.isArray(r) ? r : null;
  } catch {
    return null;
  }
}

// ── bitta urinish ───────────────────────────────────────────────────────────
async function attempt(id: string, provided?: ReceiptDTO | null): Promise<LocalPrintJob> {
  if (provided) rememberProvided(id, provided);
  const start = mutate(id, (j) => {
    j.status = "PENDING";
    j.attempts += 1;
    j.error = null;
    j.code = null;
    j.reported = false;
  });
  if (!start) throw new Error("chop etish yozuvi topilmadi");

  let dto: ReceiptDTO | null = null;
  let fetchError: string | null = null;
  if (start.doc_id) {
    try {
      dto = await fetchDto(start.doc_type, start.doc_id);
    } catch (e) {
      fetchError = errText(e);
    }
  }
  dto = dto ?? providedFor(id);

  let delivery: Delivery;
  if (!dto) {
    delivery = {
      result: { ok: false, code: "NO_DATA", error: fetchError || "chek ma'lumoti yo'q" },
      transport: null, printer: null, doc: null,
    };
  } else {
    const copy = start.copy === "REPRINT"
      ? { kind: "REPRINT" as const, ...(typeof start.copy_no === "number" && start.copy_no > 0 ? { no: start.copy_no } : {}) }
      : { kind: "ORIGINAL" as const };
    try {
      delivery = await deliver(dto, copy, readPrinterConfig());
    } catch (e) {
      delivery = { result: { ok: false, code: "FAILED", error: errText(e) }, transport: null, printer: null, doc: null };
    }
  }
  const r = delivery.result;
  const provisional = !!dto?.provisional;
  mutate(id, (j) => {
    j.status = r.ok ? "PRINTED" : "FAILED";
    j.error = r.ok ? null : r.error ?? r.code ?? "FAILED";
    j.code = r.ok ? null : r.code ?? "FAILED";
    j.transport = delivery.transport ?? j.transport;
    j.printer = delivery.printer;
    j.provisional = provisional;
    if (r.ok && !j.printed_at) j.printed_at = stamp();
  });
  if (r.ok) forgetProvided(id);
  await report(id);
  return getJob(id) as LocalPrintJob;
}

async function reprint(t: PrintDocType, doc_id: string | null, client_uuid: string | null, dto?: ReceiptDTO): Promise<LocalPrintJob> {
  const job = newJob({ t, doc_id, client_uuid, copy: "REPRINT" });
  // Nusxa raqami qog'ozda bo'lsin ("NUSXA #2") — server yozuvini chop etishdan OLDIN ochamiz (qisqa kutish).
  if (doc_id) await report(job.id, PRE_TIMEOUT_MS);
  return attempt(job.id, dto);
}

async function runPrintDoc(
  mode: "auto" | "manual", t: PrintDocType, doc_id: string | null, client_uuid: string | null, dto?: ReceiptDTO,
): Promise<LocalPrintJob> {
  const existing = findOriginal(t, doc_id, client_uuid);
  if (mode === "auto") {
    if (existing) return existing; // asl chek bor (istalgan holatda) — avto qayta chop etilmaydi
    return attempt(newJob({ t, doc_id, client_uuid, copy: "ORIGINAL" }).id, dto);
  }
  if (existing) {
    if (existing.status === "PRINTED") return reprint(t, existing.doc_id ?? doc_id, existing.client_uuid ?? client_uuid, dto);
    return attempt(existing.id, dto); // FAILED yoki uzilib qolgan PENDING — AYNAN o'sha asl chek
  }
  if (doc_id) {
    // Bu qurilmada yozuv yo'q (masalan Manager nusxasi) — server jurnali: asl chek boshqa joyda chiqqanmi?
    const orig = (await serverJobs(t, doc_id))?.find((j) => j && (j as { copy?: string }).copy === "ORIGINAL");
    if (orig && typeof orig.id === "string") {
      if (orig.status === "FAILED") {
        const attempts = Number((orig as { attempts?: number }).attempts) || 0;
        const adopted = newJob({ t, doc_id, client_uuid, copy: "ORIGINAL", id: orig.id, status: "FAILED", attempts, copy_no: 0, reported: true });
        return attempt(adopted.id, dto);
      }
      return reprint(t, doc_id, client_uuid, dto);
    }
  }
  return attempt(newJob({ t, doc_id, client_uuid, copy: "ORIGINAL" }).id, dto);
}

export async function printDoc(req: {
  doc_type: PrintDocType;
  doc_id?: string | null;
  client_uuid?: string | null;
  dto?: ReceiptDTO;
  mode: "auto" | "manual";
}): Promise<LocalPrintJob> {
  const t = req.doc_type;
  if (t !== "SALE" && t !== "RETURN") throw new Error("printDoc: doc_type SALE yoki RETURN");
  const doc_id = req.doc_id || null;
  const client_uuid = req.client_uuid || null;
  if (!doc_id && !client_uuid) throw new Error("printDoc: doc_id yoki client_uuid kerak");
  const keys = jobKeys(t, doc_id, client_uuid);
  for (const k of keys) {
    const p = inflight.get(k);
    if (p) return p;
  }
  const mode = req.mode === "auto" ? "auto" : "manual";
  return track(keys, enqueue(() => runPrintDoc(mode, t, doc_id, client_uuid, req.dto)));
}

/** Xato bilan tugagan (yoki uzilib qolgan) yozuvni AYNAN o'sha id bilan qayta chop etadi. */
export async function retryJob(id: string): Promise<LocalPrintJob> {
  const j = getJob(id);
  if (!j) throw new Error("retryJob: yozuv topilmadi");
  const keys = jobKeys(j.doc_type, j.doc_id, j.client_uuid);
  for (const k of keys) {
    const p = inflight.get(k);
    if (p) return p;
  }
  if (j.status === "PRINTED") return j; // chop etilgani qayta chiqmaydi — nusxa uchun printDoc(manual)
  return track(keys, enqueue(() => attempt(id)));
}

/**
 * Sinov cheki: DTO `GET /receipt/sample` (yoki oflayn `sampleReceipt()`), "TEST" banneri bilan.
 * ⚠️  Hech qanday yozish so'rovi yo'q (POST/PUT/PATCH) va jurnalga tushmaydi.
 */
export function printTestReceipt(kind: SampleKind = "sale", opts?: { branch_id?: string }): Promise<PrintResult> {
  const k: SampleKind = kind === "mixed" || kind === "return" || kind === "long" ? kind : "sale";
  return enqueue(async () => {
    let dto: ReceiptDTO | null = null;
    if (loggedIn()) {
      const q = new URLSearchParams({ kind: k });
      if (opts?.branch_id) q.set("branch_id", opts.branch_id);
      try {
        const r = await api<unknown>(`/receipt/sample?${q.toString()}`, {}, PROFILE_TIMEOUT_MS);
        if (isDto(r)) dto = r;
      } catch {
        /* oflayn — mahalliy namuna */
      }
    }
    if (!dto) {
      const prof = cachedReceiptProfile(opts?.branch_id);
      dto = sampleReceipt(k, prof?.store, prof?.effective);
    }
    if (!dto.test) dto = { ...dto, test: true }; // TEST banneri har holda (sotuv cheki bilan adashmasin)
    try {
      const d = await deliver(dto, null, readPrinterConfig(), opts?.branch_id);
      return d.result;
    } catch (e) {
      return { ok: false, code: "FAILED", error: errText(e) } as PrintResult;
    }
  });
}

/** Electron ilovasidami (tizim/LAN/RAW printerga to'g'ridan-to'g'ri chop eta oladimi). */
export function canPrintSilently(): boolean {
  return hasElectronPrint();
}

/** Sinovlar uchun: modul xotirasidagi navbat va keshlarni tozalaydi (localStorage'ga tegmaydi). */
export function _resetPrintRuntime(): void {
  inflight.clear();
  providedDtos.clear();
  logoCache.clear();
  profileInflight.clear();
  reporting.clear();
  memJobs = null;
  chain = Promise.resolve();
  flushing = null;
  emit();
}
