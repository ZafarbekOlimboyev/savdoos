import { useSyncExternalStore } from "react";
import { get, post } from "@/lib/api";
import { CACHE, cacheSet, outboxAdd, outboxAll, outboxRemove, type OutboxSale } from "@/lib/offline";
import { useAuth } from "@/store/auth";

// ── Online holati (reaktiv) ───────────────────────────────────────────────
let online = typeof navigator !== "undefined" ? navigator.onLine : true;
let onlineListeners: (() => void)[] = [];
let pendingListeners: (() => void)[] = [];
const emitOnline = () => onlineListeners.forEach((l) => l());
const emitPending = () => pendingListeners.forEach((l) => l());

function setOnline(v: boolean) {
  if (online !== v) { online = v; emitOnline(); }
}

if (typeof window !== "undefined") {
  window.addEventListener("online", () => { setOnline(true); void flushOutbox(); });
  window.addEventListener("offline", () => setOnline(false));
}

export function useOnline(): boolean {
  return useSyncExternalStore(
    (cb) => { onlineListeners.push(cb); return () => { onlineListeners = onlineListeners.filter((l) => l !== cb); }; },
    () => online,
    () => true
  );
}

export function usePendingCount(): number {
  return useSyncExternalStore(
    (cb) => { pendingListeners.push(cb); return () => { pendingListeners = pendingListeners.filter((l) => l !== cb); }; },
    () => outboxAll().length,
    () => 0
  );
}

// ── Rad etilgan (dead-letter) savdolar — server qabul qilmagan offline savdo JIMGINA yo'qolmasin,
//    kassirga "N rad etildi" bo'lib ko'rinsin va tekshirish uchun localStorage'da saqlanadi. ──
const FAILED_KEY = "savdoos_outbox_failed";
interface FailedSale extends OutboxSale { error: string }
let failedListeners: (() => void)[] = [];
const emitFailed = () => failedListeners.forEach((l) => l());
function readFailed(): FailedSale[] {
  try { return JSON.parse(localStorage.getItem(FAILED_KEY) || "[]"); } catch { return []; }
}
function deadLetter(item: OutboxSale, error: string): void {
  try {
    const failed = readFailed();
    failed.push({ ...item, error });
    localStorage.setItem(FAILED_KEY, JSON.stringify(failed.slice(-200)));
    emitFailed();
  } catch { /* localStorage yo'q bo'lsa — e'tibor bermaymiz */ }
}
export function useFailedCount(): number {
  return useSyncExternalStore(
    (cb) => { failedListeners.push(cb); return () => { failedListeners = failedListeners.filter((l) => l !== cb); }; },
    () => readFailed().length,
    () => 0
  );
}
export function failedSales(): FailedSale[] { return readFailed(); }
export function clearFailed(): void {
  try { localStorage.removeItem(FAILED_KEY); emitFailed(); } catch { /* ignore */ }
}

function isNetworkError(e: unknown): boolean {
  const m = (e as Error)?.message?.toLowerCase() || "";
  return (
    m.includes("failed to fetch") ||
    m.includes("networkerror") ||
    m.includes("load failed") ||
    m.includes("fetch") ||
    (typeof navigator !== "undefined" && !navigator.onLine)
  );
}

// ── Katalogni keshlash (onlayn bo'lganda) ─────────────────────────────────
export async function refreshCatalog(): Promise<boolean> {
  try {
    // POS 0-qoldiq/arxiv tovarni ham topib sotishi uchun hammasini olamiz (include_archived)
    const [p, c] = await Promise.all([get("/products?include_archived=1"), get("/categories")]);
    cacheSet(CACHE.products, p);
    cacheSet(CACHE.cats, c);
    // Sozlamalar (to'lov usullari, funksiyalar, do'kon nomi) — muvaffaqiyatsizligi katalogni to'xtatmaydi
    try { cacheSet(CACHE.settings, await get("/settings")); } catch { /* eski server bo'lsa e'tibor bermaymiz */ }
    setOnline(true);
    return true;
  } catch {
    setOnline(false);
    return false;
  }
}

// ── Navbatni serverga yuborish (idempotent /sync/push) ────────────────────
// MUHIM: /sync/push HAR DOIM 200 qaytaradi; har bir yozuv holati `results[].ok` da.
// Shuning uchun faqat server QABUL QILGAN (ok:true — yangi yoki idempotent dublikat) yozuvni
// navbatdan o'chiramiz. Server RAD ETGAN (ok:false) yozuvni jimgina yo'qotmay, dead-letter
// ro'yxatiga o'tkazamiz (kassirga "N rad etildi" bo'lib ko'rinadi). Aks holda offline savdo
// izsiz yo'qolib ketardi.
type PushResult = { client_uuid?: string | null; ok?: boolean; error?: string };
export async function flushOutbox(): Promise<void> {
  // Faqat JORIY kassirning yozuvlarini yuboramiz — server chekни token egasiga yozadi,
  // boshqa kassirniki navbatда qoladi (u qayta login qilganда o'ziniki bilan ketadi).
  // owner_id'siz eski yozuvlar moslik uchun yuboriladi.
  const me = useAuth.getState().employee?.id;
  const items = outboxAll().filter((i) => !i.owner_id || !me || i.owner_id === me);
  if (!items.length) return;
  try {
    const res = await post<{ results?: PushResult[] }>("/sync/push", { sales: items.map((i) => i.payload) });
    const results = Array.isArray(res?.results) ? res.results : null;
    if (!results) {
      // 200, lekin results yo'q (mos kelmaydigan/eski server). Xavfsizlik uchun navbatni
      // O'CHIRMAYMIZ — jimgina yo'qotishdan ko'ra pending bo'lib turgani ma'qul. Joriy server
      // har doim results qaytaradi, shuning uchun bu holat amalda yuz bermaydi.
      setOnline(true);
      return;
    }
    // client_uuid'lar canonical-lowercase (crypto.randomUUID + str(uuid)) — moslik uchun kichik harf.
    const byUuid = new Map<string, PushResult>();
    for (const r of results) if (r && r.client_uuid) byUuid.set(String(r.client_uuid).toLowerCase(), r);
    for (const i of items) {
      const r = byUuid.get(i.client_uuid.toLowerCase());
      if (!r) continue;                          // server bu yozuvga javob bermadi — navbatda qoldiramiz (keyingi urinishda)
      if (r.ok) outboxRemove(i.client_uuid);     // qabul qilindi / idempotent dublikat
      else { deadLetter(i, String(r.error || "server rad etdi")); outboxRemove(i.client_uuid); } // server ANIQ rad etdi — yo'qotmaymiz, ro'yxatga o'tkazamiz
    }
    setOnline(true);
    emitPending();
  } catch (e) {
    // Bu yerga faqat BUTUN so'rovga taalluqli xato tushadi: tarmoq uzilishi, 401 (sessiya tugadi),
    // 403 yoki server 5xx (deploy/cold-start). Bularning HECH BIRI per-record rad etish EMAS —
    // haqiqiy rad etish 200+results orqali keladi. Shuning uchun HECH NARSANI dead-letter
    // qilmaymiz/o'chirmaymiz: navbat butun saqlanadi, keyingi urinishda (30s interval yoki
    // qayta online/login bo'lganda) qayta yuboriladi. Aks holda transient xato butun navbatni
    // yo'qotib yuborardi.
    if (isNetworkError(e)) setOnline(false);
  }
}

// ── Savdoni yuborish: onlayn bo'lsa darhol, aks holda navbatga ────────────
export interface SubmitResult { ok: boolean; offline: boolean; receipt_no?: string; uid?: string }

export async function submitSale(payload: { client_uuid: string; [k: string]: unknown }): Promise<SubmitResult> {
  try {
    const res = await post<{ receipt_no: string; uid: string }>("/sales", payload);
    setOnline(true);
    void flushOutbox();
    return { ok: true, offline: false, receipt_no: res.receipt_no, uid: res.uid };
  } catch (e) {
    if (isNetworkError(e)) {
      outboxAdd({ client_uuid: payload.client_uuid, payload, created_at: new Date().toISOString(),
        owner_id: useAuth.getState().employee?.id });
      setOnline(false);
      emitPending();
      return { ok: true, offline: true };
    }
    throw e; // validatsiya/auth xatosi — navbatga qo'shilmaydi
  }
}

// ── Davriy sinxronizatsiya ────────────────────────────────────────────────
let started = false;
export function startSync(): void {
  if (started) return;
  started = true;
  void refreshCatalog();
  void flushOutbox();
  setInterval(() => {
    if (typeof navigator === "undefined" || navigator.onLine) {
      void refreshCatalog();
      void flushOutbox();
    }
  }, 30000);
}
