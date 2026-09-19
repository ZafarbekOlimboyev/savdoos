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
// ⚠️  ASL chek (server id'si ma'lum) qog'ozga chiqishdan OLDIN serverda BAND qilinadi (`/print-jobs`
//     PENDING, `ux_print_jobs_original` qaror qiladi): 409 → NUSXA. Server javob bermasa — faqat o'z
//     sotuvi (client_uuid / avto) ASL bo'lib chiqadi, boshqa joy (Manager, Sotuvlarim) NUSXA (yopiq xato):
//     ortiqcha "NUSXA" banneri zararsiz, bannersiz ikkinchi asl chek — yo'q.
// ⚠️  BAND — har urinishda YANGI `claim_token` (yozuvda saqlanadi, yakuniy hisobot ham shu token bilan).
//     Server boshqa token bilan jonli band (PENDING) turgan yozuvni 409 PRINT_JOB_BUSY bilan rad etadi:
//     bu — "asl chek boshqa qurilmada chiqmoqda/chiqqan" → NUSXA; o'sha yozuv endi hech qachon ASL emas.
//     (Shu id'ni o'zlashtirgan ikkinchi qurilma ham, birinchisining PRINTED hisoboti kechiksa ham.)
// ⚠️  Jurnal localStorage'da SERVER bo'yicha ajratilgan (`cacheGet/cacheSet` → `@<serverTag>`), yakuniy
//     holat hisoboti chop etishdan KEYIN; tarmoq bo'lmasa `flushPrintReports` keyinroq yuboradi — faqat
//     yozuv EGASI (kassir) tokeni bilan (boshqa kassirning 403/404 i yozuvni "yuborildi" qilmaydi).
// ⚠️  Eski (5F dan oldingi) server: chek marshruti yo'q (FastAPI "Not Found") — faqat shunda chaqiruvchi
//     bergan `fallbackDto` chop etiladi. Ilova 404/403 i ("Chek topilmadi") — baribir NO_DATA.
// ⚠️  `printTestReceipt` hech qanday YOZISH endpoint'ini chaqirmaydi va jurnalga tushmaydi.
import { useMemo, useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import { cacheGet, cacheSet } from "@/lib/offline";
import { useAuth } from "@/store/auth";
import { useLang } from "@/store/lang";
import {
  layoutReceipt, normalizeTemplate, pageSizeMm, renderHtml, sampleReceipt,
  type LogoVariant, type PaperWidth, type ReceiptDTO, type ReceiptDoc, type ReceiptLang, type ReceiptTemplate,
  type SampleKind,
} from "@/receipt";
import type {
  PrintErrorCode, PrintHtmlRequest, PrintPageMode, PrintResult, PrintTarget, VirtualPrintRequest,
} from "@/print/bridge";
import { LIMITS } from "@/print/node/validate";
import {
  effectiveProfile, effectiveWidth, hasElectronPrint, pageSizeOf, readPrinterConfig, type PrinterDeviceConfig,
} from "@/lib/printerConfig";

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
  /**
   * Yozuvni yaratgan/oxirgi chop etgan xodim — hisobot faqat UNING tokeni bilan yuboriladi (flushOutbox
   * qoidasi). Eski (5F.1 dan oldingi) yozuvlarda yo'q — egasiz, istalgan kassir yuboradi.
   */
  owner_id?: string | null;
  /**
   * ASL chekni serverda band qilgan urinishning tokeni (har band — yangi). Yakuniy hisobot ham shu token
   * bilan: server boshqa qurilmaning jonli bandini shu bilan ajratadi (409 PRINT_JOB_BUSY).
   */
  claim_token?: string | null;
}

/** Chek DTO'si; `legacy` — eski serverda mijoz bergan zaxira DTO'dan chizilgan (layout e'tiborsiz qoldiradi). */
type PrintableDTO = ReceiptDTO & { legacy?: boolean };

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
const PRE_TIMEOUT_MS = 4000; // chop etishdan OLDINGI so'rovlar (nusxa raqami, server jurnali, asl band)
const REPORT_TIMEOUT_MS = 8000;
const FLUSH_BATCH = 50;
// Electron ko'prigi (IPC) javobi — main tomonidagi chegaralardan (ro'yxat 10 s + oyna 60 s) UZUNROQ:
// sekin, lekin muvaffaqiyatli chop etish "xato" deb qayta urinishda ikkinchi marta chiqmasin.
export const BRIDGE_TIMEOUT_MS = 90_000;
// HTML sahifa balandligi (mm): hisoblangan balandlik + kichik zaxira; main tekshiruvi oralig'ida.
// Oflayn sotuv client_uuid → server id xaritasi (sinxronlangandan keyin bosilgan "Chop etish" uchun).
const BOUND_KEY = "savdoos_print_bound";
const BOUND_CAP = 500;
const ORIGINAL_EXISTS = "PRINT_ORIGINAL_EXISTS";
// Ayni ASL yozuvni boshqa qurilma (boshqa token bilan) hozir band qilib turibdi — "boshqa joyda bor".
const JOB_BUSY = "PRINT_JOB_BUSY";
// Boshqa filial logosi keshi (localStorage, server bo'yicha ajratilgan): oflayn nusxada ham logo chiqsin.
const LOGO_CACHE_KEY = "savdoos_print_logos";
const LOGO_CACHE_CAP = 8;

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

/** `withTimeout` dan farqi: rad etish (xato) TIMEOUT'ga aylanmaydi — asl xato matni jurnalga tushsin. */
function bounded<T>(run: () => T | Promise<T>, ms: number, onTimeout: T): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = setTimeout(() => resolve(onTimeout), ms);
    Promise.resolve().then(run).then(
      (v) => { clearTimeout(t); resolve(v); },
      (e) => { clearTimeout(t); reject(e); },
    );
  });
}

type ApiError = Error & { status?: number; code?: string };
const errStatus = (e: unknown) => (e as ApiError)?.status;
const errCode = (e: unknown) => (e as ApiError)?.code;
/**
 * Marshrut YO'Q (5F dan oldingi server): FastAPI'ning standart 404 "Not Found" i, kodsiz. Ilovaning o'z
 * 404 lari ("Chek topilmadi", "Qaytarish topilmadi") boshqa matn — ular hujjat yo'q/ko'rinmaydi degani.
 */
const routeMissing = (e: unknown) => errStatus(e) === 404 && !errCode(e) && (e as Error)?.message === "Not Found";
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

/** Hujjatning shu qurilmadagi eng so'nggi yozuvi (istalgan nusxa turi). */
function findLatest(t: PrintDocType, doc_id: string | null, client_uuid: string | null): LocalPrintJob | null {
  const all = loadJobs().sort(byCreated).filter((j) => sameDoc(j, t, doc_id, client_uuid));
  return all.length ? all[all.length - 1] : null;
}

function newJob(p: {
  t: PrintDocType; doc_id: string | null; client_uuid: string | null; copy: PrintCopy; id?: string;
  status?: JobStatus; attempts?: number; copy_no?: number | null; reported?: boolean; claim_token?: string | null;
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
    owner_id: ownerId(),
    claim_token: p.claim_token ?? null,
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
const PROVIDED_CAP = 50;

function dtoStore(key: string) {
  const mem = new Map<string, ReceiptDTO>();
  const load = (): Record<string, { at: string; dto: ReceiptDTO }> => {
    const v = cacheGet<Record<string, { at: string; dto: ReceiptDTO }>>(key, {});
    return v && typeof v === "object" ? v : {};
  };
  return {
    remember(id: string, dto: ReceiptDTO): void {
      mem.set(id, dto);
      try {
        const all = load();
        all[id] = { at: stamp(), dto };
        const keep = Object.entries(all).sort((a, b) => (a[1].at < b[1].at ? 1 : -1)).slice(0, PROVIDED_CAP);
        cacheSet(key, Object.fromEntries(keep));
      } catch { /* kvota — seans xotirasi baribir bor */ }
    },
    get(id: string): ReceiptDTO | null {
      const m = mem.get(id);
      if (m) return m;
      const hit = load()[id]?.dto;
      return hit && isDto(hit) ? hit : null;
    },
    forget(id: string): void {
      mem.delete(id);
      try {
        const all = load();
        if (id in all) {
          delete all[id];
          cacheSet(key, all);
        }
      } catch { /* ignore */ }
    },
    clearMem(): void {
      mem.clear();
    },
  };
}

// Oflayn (vaqtinchalik) DTO — server DTO olinmasa (istalgan sabab) ishlatiladi.
const provided = dtoStore("savdoos_print_dtos");
// Eski server zaxirasi — FAQAT chek marshruti yo'q bo'lsa (routeMissing) ishlatiladi.
const fallbacks = dtoStore("savdoos_print_fallback");
const rememberProvided = provided.remember;
const providedFor = provided.get;

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

/** Eski server (`/receipt/profile` marshruti yo'q) aniqlangan vaqt — TTL davomida qayta so'ralmaydi. */
let profileRouteMissingAt: number | null = null;

export function getReceiptProfile(opts?: { force?: boolean; branch_id?: string }): Promise<ReceiptProfile | null> {
  const bkey = opts?.branch_id ?? "";
  const cached = readProfileEntry(bkey);
  if (cached && !opts?.force && isFresh(cached)) return Promise.resolve(cached.profile);
  if (!loggedIn()) return Promise.resolve(cached?.profile ?? null);
  // Eski server: profil yo'q (null) — har chop etish/sikl 404 bilan urmasin (5 daqiqada bir tekshiramiz).
  if (profileRouteMissingAt !== null && !opts?.force && Date.now() - profileRouteMissingAt < PROFILE_TTL_MS) {
    return Promise.resolve(null);
  }
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
      profileRouteMissingAt = null;
      if (r && r.unchanged === true && cached && r.etag === cached.profile.etag) {
        writeProfileEntry(bkey, { ...cached, emp, fetched_at: Date.now() });
        return cached.profile;
      }
      if (isProfile(r)) {
        writeProfileEntry(bkey, { owner, emp, fetched_at: Date.now(), profile: r });
        return r;
      }
    } catch (e) {
      if (routeMissing(e)) {
        profileRouteMissingAt = Date.now();
        return null; // eski server — 5F profili yo'q (avto-chop etish ham yo'q)
      }
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

// Boshqa filial logosi (Manager nusxasi) — `GET /receipt/logos/{id}`; seans xotirasi + localStorage
// (logo id'si o'zgarmas: yangi rasm — yangi id, eskisi keshda eskirmaydi).
type LogoSet = Partial<Record<"58" | "80", LogoVariant>>;
const logoCache = new Map<string, LogoSet | null>();

function isVariant(v: unknown): v is LogoVariant {
  const x = v as LogoVariant;
  return !!x && typeof x === "object" && typeof x.width === "number" && typeof x.height === "number" &&
    typeof x.raster_b64 === "string" && typeof x.png_data_uri === "string";
}

function cleanLogoSet(v: unknown): LogoSet | null {
  if (!v || typeof v !== "object") return null;
  const r = v as Record<string, unknown>;
  const out: LogoSet = {};
  if (isVariant(r["58"])) out["58"] = r["58"];
  if (isVariant(r["80"])) out["80"] = r["80"];
  return out["58"] || out["80"] ? out : null;
}

function storedLogo(id: string): LogoSet | null {
  const all = cacheGet<Record<string, { at?: number; variants?: unknown }>>(LOGO_CACHE_KEY, {});
  return all && typeof all === "object" ? cleanLogoSet(all[id]?.variants) : null;
}

function storeLogo(id: string, variants: LogoSet): void {
  try {
    const all = { ...cacheGet<Record<string, { at: number; variants: LogoSet }>>(LOGO_CACHE_KEY, {}) };
    all[id] = { at: Date.now(), variants };
    const keys = Object.keys(all).sort((a, b) => (all[b]?.at ?? 0) - (all[a]?.at ?? 0));
    for (const k of keys.slice(LOGO_CACHE_CAP)) delete all[k];
    cacheSet(LOGO_CACHE_KEY, all);
  } catch { /* kvota — seans xotirasi baribir bor */ }
}

async function logoVariants(id: string): Promise<LogoSet | null> {
  if (logoCache.has(id)) return logoCache.get(id) ?? null;
  const stored = storedLogo(id);
  if (stored) {
    logoCache.set(id, stored);
    return stored;
  }
  if (!loggedIn()) return null;
  try {
    const r = await api<{ variants?: unknown }>(`/receipt/logos/${encodeURIComponent(id)}`, {}, PRE_TIMEOUT_MS);
    const v = cleanLogoSet(r?.variants);
    logoCache.set(id, v);
    if (v) storeLogo(id, v);
    return v;
  } catch (e) {
    // Ruxsat yo'q/topilmadi — qayta so'ramaymiz; tarmoq xatosi — keyingi safar yana urinib ko'ramiz.
    if (errStatus(e) === 403 || errStatus(e) === 404) logoCache.set(id, null);
    return null;
  }
}

/**
 * Chekdagi logo. Server DTO'si (sotuv/qaytarish, server namunasi, chaqiruvchi bergan DTO) — FAQAT
 * `dto.logo` havolasi bo'yicha: `null` — logo yo'q (kompaniya namunasiga xodim filiali logosi tushmasin).
 * `profileAssets` — DTO mijozda qurilgan (oflayn chek, mahalliy namuna): havola yo'q, profil logosi.
 * `missing` — havola bor, lekin rasm olinmadi (403/404/oflayn): chek logosiz chiqadi, ogohlantirish bilan.
 */
async function logoFor(
  dto: ReceiptDTO, width: PaperWidth, t: ReceiptTemplate, prof: ReceiptProfile | null, profileAssets: boolean,
): Promise<{ logo: LogoVariant | null; missing: boolean }> {
  if (!t.show_logo) return { logo: null, missing: false };
  const w = String(width) as "58" | "80";
  if (dto.logo && typeof dto.logo.id === "string") {
    const set = prof?.logo?.id === dto.logo.id ? prof.logo.variants ?? null : await logoVariants(dto.logo.id);
    const logo = set?.[w] ?? null;
    return { logo, missing: !logo };
  }
  if (profileAssets && prof?.logo) return { logo: prof.logo.variants?.[w] ?? null, missing: false };
  return { logo: null, missing: false };
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

/** Logo havolasi bor, rasm olinmadi — chek logosiz chiqdi (natija ogohlantirishi, jurnal xatosi EMAS). */
function withLogoWarning(d: Delivery, missing: boolean): Delivery {
  if (!missing) return d;
  const warnings = [...(d.result.warnings ?? []), "logo_unavailable"];
  return { ...d, result: { ...d.result, warnings } };
}

async function deliver(
  dto: ReceiptDTO,
  copy: { kind: PrintCopy; no?: number } | null,
  cfg: PrinterDeviceConfig,
  branch_id?: string,
  opts?: { profileAssets?: boolean },
): Promise<Delivery> {
  const template = normalizeTemplate(dto.template);
  // Kenglik BITTA joyda hal qilinadi (layout va ESC/POS profili bir xil ustun soni ko'rsin).
  const width: PaperWidth = effectiveWidth(cfg, template.width_mm);
  const prof = await profileForPrint(branch_id);
  // Profil logosi/QR'i faqat MIJOZDA qurilgan DTO'ga (oflayn chek, mahalliy namuna) — server DTO'si
  // o'zi hal qilgan: `logo: null`/`qr: null` — yo'q degani.
  const profileAssets = opts?.profileAssets === true;
  let d = dto;
  if (profileAssets && !dto.qr && template.qr_mode === "store_url" && prof?.store_qr) {
    d = { ...dto, qr: { kind: "store_url", ...prof.store_qr } };
  }
  const lg = await logoFor(d, width, template, prof, profileAssets);
  if (lg.missing) console.warn(`[print] logo olinmadi (${d.logo?.id ?? "?"}) — chek logosiz`);
  const doc = layoutReceipt(d, { width_mm: width, lang: template.lang ?? uiLang(), template, logo: lg.logo, copy });
  return withLogoWarning(await send(doc, d, copy, cfg, template), lg.missing);
}

/** Tayyor hujjatni uzatadi (virtual / Electron / brauzer). */
async function send(
  doc: ReceiptDoc, d: ReceiptDTO, copy: { kind: PrintCopy; no?: number } | null, cfg: PrinterDeviceConfig,
  template: ReceiptTemplate,
): Promise<Delivery> {
  const width = doc.width_mm;
  const copies = template.copies;
  const escpos = cfg.transport === "escpos_lan" || cfg.transport === "escpos_spooler";
  const profile = effectiveProfile(cfg, template.width_mm);
  const title = `${d.doc?.number ?? ""}`.slice(0, 60) || "Receipt";
  // HTML sahifa: "exact" — CSS `@page` va Electron pageSize AYNAN chek o'lchamida; "driver" — ikkalasi ham
  // yo'q (drayver qog'ozi, 1:1 yuqoridan — 5F'dan oldingi xulq). Chromium chegarasidan (3276 mm) uzun
  // chek aniq o'lchamda oxirgi sahifasi 3 m bo'sh qog'oz bo'lardi — u ham drayver qog'ozida.
  const page = pageSizeMm(doc);
  const pageMode: PrintPageMode = page.height_mm >= LIMITS.pageHeightMaxMm ? "driver" : pageSizeOf(cfg);
  // Hech bir chaqiruv navbatni abadiy to'smasin: javobsiz ko'prik → TIMEOUT (yozuv FAILED, navbat davom).
  const timedOut: PrintResult = { ok: false, code: "TIMEOUT", error: `printer ${BRIDGE_TIMEOUT_MS / 1000} s ichida javob bermadi` };

  const virtual = typeof window !== "undefined" ? window.__BINOS_VIRTUAL_PRINTER__ : undefined;
  if (typeof virtual === "function") {
    const req: VirtualPrintRequest = { kind: escpos ? "escpos" : "html", doc, copy, copies };
    if (escpos) req.profile = profile;
    else req.html = renderHtml(doc, { title, pageMode });
    try {
      const r = await bounded<unknown>(() => virtual(req), BRIDGE_TIMEOUT_MS, timedOut);
      return { result: normalizeResult(r), transport: "virtual", printer: null, doc };
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
      const escReq = { doc: stripPng(doc), profile, target, copies, cut: template.auto_cut };
      const r = await bounded<unknown>(() => bridge.printEscPos(escReq), BRIDGE_TIMEOUT_MS, timedOut);
      return { result: normalizeResult(r), transport: cfg.transport, printer, doc };
    }
    if (bridge && cfg.transport !== "browser") {
      const printer = cfg.printer ?? null;
      if (typeof bridge.printHtml === "function") {
        // "exact": Electron pageSize = CSS `@page` = `pageSizeMm` (AYNI formula — hech qachon ajralmasin).
        const html = renderHtml(doc, { title, pageMode });
        const htmlReq: PrintHtmlRequest = { html, printer: printer ?? undefined, widthMm: width, pageMode, copies };
        if (pageMode === "exact") htmlReq.heightMm = page.height_mm;
        const r = await bounded<unknown>(() => bridge.printHtml(htmlReq), BRIDGE_TIMEOUT_MS, timedOut);
        return { result: normalizeResult(r), transport: "system", printer, doc };
      }
      // Eski ko'prik (0.7.x) pageSize bermaydi — HTML ham o'lchamsiz (aks holda Chromium sahifani qisardi).
      const html = renderHtml(doc, { title, pageMode: "driver" });
      const r = await bounded<unknown>(() => bridge.print(html, printer ?? undefined), BRIDGE_TIMEOUT_MS, timedOut);
      const legacy = r === timedOut ? timedOut : (r as { ok?: boolean } | null)?.ok ? { ok: true } : { ok: false, code: "FAILED" };
      return { result: normalizeResult(legacy), transport: "system", printer, doc };
    }
  } catch (e) {
    return { result: { ok: false, code: "FAILED", error: errText(e) }, transport: cfg.transport, printer: cfg.printer ?? null, doc };
  }
  const r = await printViaIframe(renderHtml(doc, { title, pageMode }));
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
interface PrintJobOut { id: string; copy?: string; copy_no?: number; status?: string; attempts?: number }
type ReportOutcome = "ok" | "skipped" | "network" | "final";
/** Ishlayotgan hisobotlar: qaysi holat (`updated_at`) yuborilayotgani bilan. */
const reporting = new Map<string, { p: Promise<ReportOutcome>; snapshot: string | null }>();

function reportBody(j: LocalPrintJob): Record<string, unknown> {
  const err = j.code && j.error && !j.error.startsWith(j.code) ? `${j.code}: ${j.error}` : j.error ?? j.code;
  const body: Record<string, unknown> = {
    status: j.status,
    attempts: j.attempts,
    error: err ? err.slice(0, 300) : null,
    printer: j.printer ? j.printer.slice(0, 120) : null,
    transport: j.transport,
  };
  // ASL yozuv hisoboti o'sha bandning tokeni bilan: boshqa qurilma bandini eskirgan holat bilan ochmasin.
  if (j.copy === "ORIGINAL" && j.claim_token) body.claim_token = j.claim_token;
  return body;
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
    // Boshqa kassirning yozuvi — faqat o'zi yuboradi: B ning tokeni bilan A ning qaytarishi 404 bo'lib,
    // yozuv "yuborildi" deb abadiy tashlanardi (server ASL chekni bilmay qolardi).
    if (j.owner_id && j.owner_id !== ownerId()) return "skipped";
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
      // AYNI id serverda allaqachon PRINTED (boshqa qurilma o'zlashtirib chop etgan), bu yerda esa yo'q.
      const takenHere = code === "PRINT_JOB_FINAL" && j.copy === "ORIGINAL" && j.status !== "PRINTED";
      // AYNI id'ni boshqa qurilma (boshqa token) hozir band qilgan — bu yozuv ham ASL bo'lib qolmaydi.
      const busy = code === JOB_BUSY && j.copy === "ORIGINAL";
      if (st === 409 && (code === ORIGINAL_EXISTS || takenHere || busy)) {
        // Boshqa qurilma asl chekni allaqachon yozgan: qayd etamiz, AVTOMATIK qayta chop ETMAYMIZ;
        // bu yozuv endi hech qachon ASL bo'lib chiqmaydi (keyingi bosish — NUSXA).
        mutate(id, (x) => { x.reported = true; x.error = ORIGINAL_EXISTS; x.code = ORIGINAL_EXISTS; }, false);
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
    // Zaxira: sinxronlash bilan chop etish ustma-ust tushib, bog'lanmay qolgan oflayn yozuvlar.
    rebindFromMap();
    const me = ownerId();
    // Faqat JORIY kassirning (yoki egasiz eski) yozuvlari — flushOutbox qoidasi bilan bir xil.
    const todo = loadJobs()
      .filter((j) => !j.reported && j.doc_id && (!j.owner_id || j.owner_id === me))
      .sort(byCreated)
      .slice(0, FLUSH_BATCH);
    for (const j of todo) {
      if ((await report(j.id)) === "network") break;
    }
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}

// ── oflayn sotuv → server id (client_uuid xaritasi) ─────────────────────────
function loadBound(): Record<string, string> {
  const v = cacheGet<unknown>(BOUND_KEY, {});
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, string>) : {};
}

/** Sinxronlangan oflayn sotuvning server id'si (yo'q — null). */
function boundIdFor(client_uuid: string): string | null {
  const id = loadBound()[client_uuid.toLowerCase()];
  return typeof id === "string" && id ? id : null;
}

/** Jurnal yozuvlarini bog'laydi: BITTA o'qish, ko'pi bilan BITTA yozish (N×J emas). */
function rebindJobs(pairs: Map<string, string>): number {
  if (!pairs.size) return 0;
  const jobs = loadJobs();
  let n = 0;
  let now: string | null = null;
  for (const j of jobs) {
    if (j.doc_id || !j.client_uuid) continue;
    const id = pairs.get(j.client_uuid.toLowerCase());
    if (!id) continue;
    now = now ?? stamp();
    j.doc_id = id;
    j.key = docKey(j.doc_type, id);
    j.reported = false;
    j.updated_at = now;
    n++;
  }
  if (n) saveJobs(jobs);
  return n;
}

function rebindFromMap(): void {
  const jobs = loadJobs().filter((j) => !j.doc_id && j.client_uuid);
  if (!jobs.length) return;
  const bound = loadBound();
  const pairs = new Map<string, string>();
  for (const j of jobs) {
    const k = (j.client_uuid as string).toLowerCase();
    if (typeof bound[k] === "string" && bound[k]) pairs.set(k, bound[k]);
  }
  rebindJobs(pairs);
}

/**
 * Oflayn sotuvlar sinxronlandi — server id'lari ma'lum. Xaritaga HAR DOIM yoziladi (yozuv hali bo'lmasa
 * ham: kassir "Chop etish" ni sinxronlashdan KEYIN bossa chek serverdan, hisobot bilan chiqsin), mavjud
 * jurnal yozuvlari esa shu hujjatga bog'lanadi. Xarita va jurnal — har biri bir marta o'qiladi/yoziladi.
 * Qaytaradi: bog'langan jurnal yozuvlari soni.
 */
export function bindDocIds(pairs: Map<string, string>): number {
  const clean = new Map<string, string>();
  for (const [cu, id] of pairs) {
    if (typeof cu === "string" && cu && typeof id === "string" && id) clean.set(cu.toLowerCase(), id);
  }
  if (!clean.size) return 0;
  try {
    const m = loadBound();
    for (const [cu, id] of clean) {
      delete m[cu]; // eng yangisi oxirida (kesishda eskisi ketadi)
      m[cu] = id;
    }
    const keys = Object.keys(m);
    for (const k of keys.slice(0, Math.max(0, keys.length - BOUND_CAP))) delete m[k];
    cacheSet(BOUND_KEY, m);
  } catch { /* kvota — mavjud yozuvlar baribir bog'lanadi */ }
  return rebindJobs(clean);
}

/** Bitta oflayn sotuv sinxronlandi (`bindDocIds` ning qisqa shakli). */
export function bindDocId(client_uuid: string, doc_id: string): void {
  if (!client_uuid || !doc_id) return;
  bindDocIds(new Map([[client_uuid, doc_id]]));
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

// ── ASL chekni chop etishdan OLDIN band qilish ──────────────────────────────
type ClaimOutcome = { outcome: "ok"; copy_no: number } | { outcome: "exists" } | { outcome: "unverified" };

/**
 * Server `ux_print_jobs_original` qaror qiladi: POST (yangi id) yoki PATCH (server biladigan id) PENDING,
 * shu urinishning `claim_token` i bilan. 201/200 — bu qurilma asl chekni chop etadi; 409
 * PRINT_ORIGINAL_EXISTS / PRINT_JOB_FINAL / PRINT_JOB_BUSY — asl chek boshqa joyda (ayni id boshqa
 * qurilmada chop etilgan yoki hozir band) → NUSXA. Qolgani (tarmoq, 5xx, muddat, 403, 404) — "tekshirib
 * bo'lmadi": chaqiruvchi hal qiladi (o'z sotuvi — ASL, boshqasi — NUSXA).
 */
async function claimOriginal(j: {
  id: string; doc_type: PrintDocType; doc_id: string; copy_no: number | null; attempts: number; claim_token: string;
}): Promise<ClaimOutcome> {
  if (!loggedIn()) return { outcome: "unverified" };
  const body = { status: "PENDING", attempts: j.attempts, error: null, claim_token: j.claim_token };
  const create = () =>
    api<PrintJobOut>("/print-jobs", {
      method: "POST",
      body: JSON.stringify({ id: j.id, doc_type: j.doc_type, doc_id: j.doc_id, copy: "ORIGINAL", ...body }),
    }, PRE_TIMEOUT_MS);
  try {
    let out: PrintJobOut;
    if (j.copy_no !== null) {
      try {
        out = await api<PrintJobOut>(`/print-jobs/${encodeURIComponent(j.id)}`, { method: "PATCH", body: JSON.stringify(body) }, PRE_TIMEOUT_MS);
      } catch (e) {
        if (errStatus(e) !== 404 || routeMissing(e)) throw e;
        out = await create();
      }
    } else {
      out = await create();
    }
    return { outcome: "ok", copy_no: typeof out?.copy_no === "number" ? out.copy_no : 0 };
  } catch (e) {
    const code = errCode(e);
    if (errStatus(e) === 409 && (code === ORIGINAL_EXISTS || code === "PRINT_JOB_FINAL" || code === JOB_BUSY)) {
      return { outcome: "exists" };
    }
    return { outcome: "unverified" };
  }
}

/** Bu yozuv hech qachon ASL bo'lib chiqmaydi: asl chek boshqa joyda (serverda) bor. */
function markOriginalExists(id: string): void {
  mutate(id, (x) => {
    if (x.status !== "PRINTED") x.status = "FAILED";
    x.code = ORIGINAL_EXISTS;
    x.error = ORIGINAL_EXISTS;
    x.reported = true; // serverda boshqa ASL bor — bu yozuvni yuborish yana 409 bo'lardi
  });
}

// ── bitta urinish ───────────────────────────────────────────────────────────
async function attempt(id: string, dto0?: ReceiptDTO | null, fallback?: ReceiptDTO | null): Promise<LocalPrintJob> {
  if (dto0) rememberProvided(id, dto0);
  if (fallback) fallbacks.remember(id, fallback);
  const me = ownerId();
  const start = mutate(id, (j) => {
    j.status = "PENDING";
    j.attempts += 1;
    j.error = null;
    j.code = null;
    j.reported = false;
    if (me) j.owner_id = me; // kim chop etsa — hisobot o'shaniki
  });
  if (!start) throw new Error("chop etish yozuvi topilmadi");

  let dto: PrintableDTO | null = null;
  let fetchError: string | null = null;
  let missing = false;
  if (start.doc_id) {
    try {
      dto = await fetchDto(start.doc_type, start.doc_id);
    } catch (e) {
      fetchError = errText(e);
      missing = routeMissing(e);
    }
  }
  if (!dto && missing) {
    // Eski server (marshrut yo'q): chaqiruvchining zaxira DTO'si — vaqtinchalik EMAS (haqiqiy raqam bilan).
    const fb = fallbacks.get(id);
    if (fb) dto = { ...fb, provisional: false, legacy: true };
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
      // Oflayn (mijozda qurilgan) chekda logo/QR havolasi yo'q — kassaning profil keshidan.
      delivery = await deliver(dto, copy, readPrinterConfig(), undefined, { profileAssets: dto.provisional === true });
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
  if (r.ok) {
    provided.forget(id);
    fallbacks.forget(id);
  }
  await report(id);
  return getJob(id) as LocalPrintJob;
}

async function reprint(
  t: PrintDocType, doc_id: string | null, client_uuid: string | null, dto?: ReceiptDTO | null, fallback?: ReceiptDTO | null,
): Promise<LocalPrintJob> {
  if (doc_id) {
    // Server NUSXA'ni ASL'siz ko'rmasin: shu qurilmadagi yuborilmagan asl chek hisoboti oldin ketadi.
    const orig = findOriginal(t, doc_id, client_uuid);
    if (orig && !orig.reported && orig.doc_id) await report(orig.id, PRE_TIMEOUT_MS);
  }
  const job = newJob({ t, doc_id, client_uuid, copy: "REPRINT" });
  // Nusxa raqami qog'ozda bo'lsin ("NUSXA #2") — server yozuvini chop etishdan OLDIN ochamiz (qisqa kutish).
  if (doc_id) await report(job.id, PRE_TIMEOUT_MS);
  return attempt(job.id, dto, fallback);
}

/**
 * Mavjud ASL yozuvni (FAILED / uzilib qolgan PENDING / o'zlashtirilgan server yozuvi) chop etish:
 * avval serverda band qilinadi. `own` — hujjatni shu qurilma yaratgan (tekshirib bo'lmasa ham ASL).
 */
async function printOriginal(
  id: string, own: boolean, dto?: ReceiptDTO | null, fallback?: ReceiptDTO | null,
): Promise<LocalPrintJob> {
  let j = getJob(id);
  if (!j) throw new Error("chop etish yozuvi topilmadi");
  // O'z bandimizning xatosi (FAILED) serverga yetmagan: avval o'sha token bilan yuboramiz — aks holda
  // serverda bandimiz ochiq (PENDING) qolib, yangi token bilan band o'zimizga PRINT_JOB_BUSY bo'lardi.
  if (j.copy === "ORIGINAL" && j.status === "FAILED" && !j.reported && j.doc_id && j.claim_token && j.code !== ORIGINAL_EXISTS) {
    await report(id, PRE_TIMEOUT_MS);
    j = getJob(id) ?? j;
  }
  const { doc_type, doc_id, client_uuid } = j;
  const asCopy = () => reprint(doc_type, doc_id, client_uuid, dto ?? providedFor(id), fallback ?? fallbacks.get(id));
  if (j.code === ORIGINAL_EXISTS) return asCopy(); // asl chek boshqa joyda — bu yozuv hech qachon ASL emas
  if (j.doc_id) {
    // Har band — yangi token, chop etishdan OLDIN yozuvda (ilova shu yerda yopilsa ham hisobot o'sha token bilan).
    const claim_token = newId();
    mutate(id, (x) => { x.claim_token = claim_token; }, false);
    const c = await claimOriginal({
      id: j.id, doc_type: j.doc_type, doc_id: j.doc_id, copy_no: j.copy_no, attempts: j.attempts, claim_token,
    });
    if (c.outcome === "exists") {
      markOriginalExists(id);
      return asCopy();
    }
    if (c.outcome === "unverified" && !own) return asCopy(); // yopiq xato: banner zararsiz, dublikat — yo'q
    if (c.outcome === "ok") mutate(id, (x) => { x.copy_no = c.copy_no; }, false);
  }
  return attempt(id, dto, fallback);
}

/** Bu qurilmada ASL yozuv yo'q — yangi ASL (server id'si ma'lum bo'lsa avval band qilinadi). */
async function newOriginal(
  t: PrintDocType, doc_id: string | null, client_uuid: string | null, own: boolean,
  dto?: ReceiptDTO | null, fallback?: ReceiptDTO | null,
): Promise<LocalPrintJob> {
  if (!doc_id) return attempt(newJob({ t, doc_id, client_uuid, copy: "ORIGINAL" }).id, dto, fallback);
  const id = newId();
  const claim_token = newId();
  const c = await claimOriginal({ id, doc_type: t, doc_id, copy_no: null, attempts: 0, claim_token });
  if (c.outcome === "exists" || (c.outcome === "unverified" && !own)) return reprint(t, doc_id, client_uuid, dto, fallback);
  const copy_no = c.outcome === "ok" ? c.copy_no : null;
  return attempt(newJob({ t, doc_id, client_uuid, copy: "ORIGINAL", id, copy_no, claim_token }).id, dto, fallback);
}

async function runPrintDoc(
  mode: "auto" | "manual", t: PrintDocType, doc_id: string | null, client_uuid: string | null,
  dto?: ReceiptDTO, fallback?: ReceiptDTO,
): Promise<LocalPrintJob> {
  // O'z hujjati: POS o'z sotuvini client_uuid bilan chop etadi; avto-chop etish faqat hujjatni endigina
  // yaratgan ekranda ishlaydi. Server javob bermasa faqat shular ASL chiqaradi.
  const own = !!client_uuid || mode === "auto";
  const existing = findOriginal(t, doc_id, client_uuid);
  if (mode === "auto") {
    if (existing) return existing; // asl chek bor (istalgan holatda) — avto qayta chop etilmaydi
    // Asl chek boshqa joyda edi (409 → NUSXA chiqqan) — avto ikkinchi marta hech narsa chiqarmaydi.
    const any = findLatest(t, doc_id, client_uuid);
    if (any) return any;
    return newOriginal(t, doc_id, client_uuid, own, dto, fallback);
  }
  if (existing) {
    if (existing.status === "PRINTED") return reprint(t, existing.doc_id ?? doc_id, existing.client_uuid ?? client_uuid, dto, fallback);
    // FAILED yoki uzilib qolgan PENDING — AYNAN o'sha asl chek (serverda band qilinib).
    return printOriginal(existing.id, own || !!existing.client_uuid, dto, fallback);
  }
  if (doc_id) {
    // Bu qurilmada yozuv yo'q (masalan Manager nusxasi) — server jurnali: asl chek boshqa joyda chiqqanmi?
    const list = await serverJobs(t, doc_id);
    if (list === null) {
      // Jurnalni o'qib bo'lmadi: o'z sotuvi — band qilishga urinadi; boshqa joy — NUSXA (yopiq xato).
      if (!own) return reprint(t, doc_id, client_uuid, dto, fallback);
    } else {
      const rows = list.filter((j) => !!j && typeof j.id === "string");
      // HAR QANDAY nusxa yozuvi — asl chek chop etilganining isboti (asl hisobot kechikkan bo'lsa ham).
      const printedSomewhere = rows.some((j) => j.copy === "REPRINT" || (j.copy === "ORIGINAL" && j.status !== "FAILED"));
      if (printedSomewhere) return reprint(t, doc_id, client_uuid, dto, fallback);
      const failed = rows.find((j) => j.copy === "ORIGINAL" && j.status === "FAILED");
      if (failed) {
        // O'zlashtirish: ayni id ikki qurilmada — band O'Z tokenimiz bilan; boshqa qurilma shu orada band
        // qilgan (yoki keyin qiladi) bo'lsa server PRINT_JOB_BUSY → ikkinchisi NUSXA.
        const attempts = Number(failed.attempts) || 0;
        const adopted = newJob({ t, doc_id, client_uuid, copy: "ORIGINAL", id: failed.id, status: "FAILED", attempts, copy_no: 0, reported: true });
        return printOriginal(adopted.id, own, dto, fallback);
      }
    }
  }
  return newOriginal(t, doc_id, client_uuid, own, dto, fallback);
}

export async function printDoc(req: {
  doc_type: PrintDocType;
  doc_id?: string | null;
  client_uuid?: string | null;
  dto?: ReceiptDTO;
  /**
   * Eski server zaxirasi: FAQAT `GET /sales|returns/{id}/receipt` marshruti yo'q bo'lsa (FastAPI 404
   * "Not Found") chop etiladi — `provisional: false`. Ilova 404/403 ida ishlatilmaydi (NO_DATA).
   */
  fallbackDto?: ReceiptDTO;
  mode: "auto" | "manual";
}): Promise<LocalPrintJob> {
  const t = req.doc_type;
  if (t !== "SALE" && t !== "RETURN") throw new Error("printDoc: doc_type SALE yoki RETURN");
  const client_uuid = req.client_uuid || null;
  // Oflayn sotuv allaqachon sinxronlangan — server id'si xaritadan: chek serverdan, hisobot bilan.
  const doc_id = req.doc_id || (client_uuid ? boundIdFor(client_uuid) : null) || null;
  if (!doc_id && !client_uuid) throw new Error("printDoc: doc_id yoki client_uuid kerak");
  const keys = jobKeys(t, doc_id, client_uuid);
  for (const k of keys) {
    const p = inflight.get(k);
    if (p) return p;
  }
  const mode = req.mode === "auto" ? "auto" : "manual";
  const fallback = req.fallbackDto && isDto(req.fallbackDto) ? req.fallbackDto : undefined;
  return track(keys, enqueue(() => runPrintDoc(mode, t, doc_id, client_uuid, req.dto, fallback)));
}

/**
 * Xato bilan tugagan (yoki uzilib qolgan) yozuvni AYNAN o'sha id bilan qayta chop etadi. ASL yozuv
 * `printDoc(manual)` kabi serverda band qilinadi: asl chek boshqa joyda bo'lsa — NUSXA.
 */
export async function retryJob(id: string): Promise<LocalPrintJob> {
  const j = getJob(id);
  if (!j) throw new Error("retryJob: yozuv topilmadi");
  const keys = jobKeys(j.doc_type, j.doc_id, j.client_uuid);
  for (const k of keys) {
    const p = inflight.get(k);
    if (p) return p;
  }
  if (j.status === "PRINTED") return j; // chop etilgani qayta chiqmaydi — nusxa uchun printDoc(manual)
  if (j.copy === "ORIGINAL") return track(keys, enqueue(() => printOriginal(id, !!j.client_uuid)));
  return track(keys, enqueue(() => attempt(id)));
}

/**
 * Sinov cheki: DTO `GET /receipt/sample` (yoki oflayn `sampleReceipt()`), "TEST" banneri bilan.
 * `opts.dto` — chaqiruvchi (Manager oldindan ko'rishi) bergan DTO AYNAN chop etiladi: server namunasi
 * so'ralmaydi, profil logosi/QR'i qo'shilmaydi (qog'oz ekrandagi bilan bir xil).
 * ⚠️  Hech qanday yozish so'rovi yo'q (POST/PUT/PATCH) va jurnalga tushmaydi.
 */
export function printTestReceipt(
  kind: SampleKind = "sale",
  opts?: { branch_id?: string; scope?: "company"; dto?: ReceiptDTO },
): Promise<PrintResult> {
  const k: SampleKind = kind === "mixed" || kind === "return" || kind === "long" ? kind : "sale";
  const given = opts?.dto;
  if (given !== undefined && !isDto(given)) {
    return Promise.resolve({ ok: false, code: "FAILED", error: "namuna chek ma'lumoti noto'g'ri" });
  }
  const company = opts?.scope === "company";
  return enqueue(async () => {
    let dto: ReceiptDTO | null = given ?? null;
    // Profil logosi/QR'i faqat mahalliy namunaga (server/chaqiruvchi DTO'si o'zi hal qilgan).
    let profileAssets = false;
    if (!dto && loggedIn()) {
      const q = new URLSearchParams({ kind: k });
      // Kompaniya standarti tahrirlanayotganda namuna FILIAL override'isiz bo'lsin (server faqat
      // cheklovsiz xodimga beradi; aks holda 403 → pastdagi mahalliy namuna).
      if (company) q.set("scope", "company");
      else if (opts?.branch_id) q.set("branch_id", opts.branch_id);
      try {
        const r = await api<unknown>(`/receipt/sample?${q.toString()}`, {}, PROFILE_TIMEOUT_MS);
        if (isDto(r)) dto = r;
      } catch {
        /* oflayn — mahalliy namuna */
      }
    }
    if (!dto) {
      // Kompaniya doirasi: keshdagi profil — xodim FILIALI (ustama shablon, logo, QR) — ishlatilmaydi.
      const prof = company ? null : cachedReceiptProfile(opts?.branch_id);
      dto = sampleReceipt(k, prof?.store, prof?.effective);
      profileAssets = !company;
    }
    if (!dto.test) dto = { ...dto, test: true }; // TEST banneri har holda (sotuv cheki bilan adashmasin)
    try {
      const d = await deliver(dto, null, readPrinterConfig(), opts?.branch_id, { profileAssets });
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
  provided.clearMem();
  fallbacks.clearMem();
  profileRouteMissingAt = null;
  logoCache.clear(); // localStorage keshi qoladi (ilova qayta ishga tushgandek)
  profileInflight.clear();
  reporting.clear();
  memJobs = null;
  chain = Promise.resolve();
  flushing = null;
  emit();
}
