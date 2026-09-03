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
    // QA OFF-6: FAQAT joriy kassirning yozuvlarini sanaymiz (flushOutbox ham owner_id bo'yicha yuboradi) —
    // aks holda A kassir yozuvlari B ekranida "N pending" bo'lib turib, B flush qilmagani uchun HECH QACHON
    // tozalanmasdi (badge abadiy qotardi).
    () => { const me = useAuth.getState().employee?.id; return outboxAll().filter((i) => !i.owner_id || !me || i.owner_id === me).length; },
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
// QA OFF-3: boolean qaytaradi — true=dead-letter'ga YOZILDI, false=xato (kvota/localStorage yo'q).
// Chaqiruvchi FALSE'да outbox'dan O'CHIRMASLIGI kerak (aks holda savdo HAM outbox'dan HAM dead-letter'dan
// g'oyib bo'lib SILENT LOST SALE bo'lardi — kod izohidagi "jimgina yo'qotmay" kafolati buzilardi).
function deadLetter(item: OutboxSale, error: string): boolean {
  try {
    const failed = readFailed();
    failed.push({ ...item, error });
    localStorage.setItem(FAILED_KEY, JSON.stringify(failed.slice(-200)));
    emitFailed();
    return true;
  } catch { return false; /* kvota/localStorage yo'q — chaqiruvchi outbox'da qoldirsin */ }
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
  const err = e as { message?: string; name?: string };
  const m = (err?.message || "").toLowerCase();
  const name = (err?.name || "").toLowerCase();
  return (
    // QA PAY-04: fetch timeout (AbortController) — osilgan so'rov transient deb navbatga tushadi
    name === "aborterror" ||
    m.includes("aborted") ||
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
// QA OFF-1: `retry` — server TRANSIENT (409 'Kassa band'/deadlock/5xx) xatoni shu bayroq bilan qaytaradi;
// bunday yozuvni outbox'da SAQLAYMIZ (dead-letter QILMAYMIZ) — keyingi flush qayta uradi.
type PushResult = { client_uuid?: string | null; ok?: boolean; retry?: boolean; error?: string };
// QA OFF-2: server PushBody.sales max_length=1000 — navbatni 1000'lik BO'LAKLARga bo'lib yuboramiz.
const PUSH_CHUNK = 1000;
// Bir vaqtda faqat BITTA flushOutbox ishlaydi — aks holda 30s interval + online event +
// login + submitSale bir-birining ustidan yugurib, server rad etgan savdoni IKKI marta
// dead-letter qilib yuborishi mumkin (soxta "N rad etildi" / dublikat).
let flushing = false;
export async function flushOutbox(): Promise<void> {
  if (flushing) return;
  flushing = true;
  try {
    // Faqat JORIY kassirning yozuvlarini yuboramiz — server chekни token egasiga yozadi,
    // boshqa kassirniki navbatда qoladi (u qayta login qilганда o'ziniki bilan ketadi).
    // owner_id'siz eski yozuvlar moslik uchun yuboriladi.
    const me = useAuth.getState().employee?.id;
    const items = outboxAll().filter((i) => !i.owner_id || !me || i.owner_id === me);
    if (!items.length) return;
    // QA OFF-2: navbat >1000 bo'lsa BUTUN so'rov 422 bilan rad etilib navbat abadiy tiqilib qolardi
    // (infinite sync loop). 1000'lik bo'laklarга bo'lib yuboramiz — har bo'lak mustaqil.
    for (let start = 0; start < items.length; start += PUSH_CHUNK) {
      const chunk = items.slice(start, start + PUSH_CHUNK);
      try {
        // sold_at = offline yaratilган HAQIQIY vaqt — aks holда server flush vaqtини stamp qilиб
        // kunlik hisobот buzилаrди (23:30 offline savdo 00:15 keyingi kunга tushib ketardi).
        const res = await post<{ results?: PushResult[] }>("/sync/push", { sales: chunk.map((i) => ({ ...(i.payload as Record<string, unknown>), sold_at: i.created_at })) });
        const results = Array.isArray(res?.results) ? res.results : null;
        if (!results) {
          // 200, lekin results yo'q (mos kelmaydigan/eski server). Navbatni O'CHIRMAYMIZ (jimgina
          // yo'qotishdan ko'ra pending qolgani ma'qul). Joriy server doim results qaytaradi.
          setOnline(true);
          return;
        }
        // client_uuid'lar canonical-lowercase (crypto.randomUUID + str(uuid)) — moslik uchun kichik harf.
        const byUuid = new Map<string, PushResult>();
        for (const r of results) if (r && r.client_uuid) byUuid.set(String(r.client_uuid).toLowerCase(), r);
        for (const i of chunk) {
          const r = byUuid.get(i.client_uuid.toLowerCase());
          if (!r) continue;                          // server bu yozuvga javob bermadi — navbatda qoldiramiz
          if (r.ok) { outboxRemove(i.client_uuid); }  // qabul qilindi / idempotent dublikat
          else if (r.retry) { /* QA OFF-1: TRANSIENT (409/deadlock/5xx) — outbox'da SAQLAYMIZ, keyingi flush qayta uradi (LOST SALE emas) */ }
          // QA OFF-3: PERMANENT rad — dead-letter'ga YOZILGACHGINA o'chiramiz. deadLetter kvota'да false
          // qaytarsa outbox'da QOLADI (jimgina yo'qotmaymiz — silent lost sale yopiq).
          else if (deadLetter(i, String(r.error || "server rad etdi"))) outboxRemove(i.client_uuid);
        }
        setOnline(true);
        emitPending();
      } catch (e) {
        // BUTUN so'rov xatosi: tarmoq/401/403/5xx/timeout — per-record rad EMAS. HECH NARSANI dead-letter
        // qilmaymiz/o'chirmaymiz: bu bo'lak (va qolganlari) navbatда saqlanadi, keyingi flush qayta uradi.
        if (isNetworkError(e)) setOnline(false);
        break;   // qolgan bo'laklarни ham keyingi urinishга qoldiramiz (navbat butunligi)
      }
    }
  } finally {
    flushing = false;
  }
}

// ── Savdoni yuborish: onlayn bo'lsa darhol, aks holda navbatga ────────────
export interface SubmitResult { ok: boolean; offline: boolean; receipt_no?: string; uid?: string }

// opts.allowOffline=false bo'lsa (masalan karta/QR "internetsiz" o'chiq) — tarmoq
// uzilса savdo navbatga QO'SHILMAYDI, aniq xato qaytaradi (opts.offlineErr matni bilan).
// Standart true — naqd/qarz kabi doim offline ishlaydigan usullar uchun (backward-compat).
export async function submitSale(
  payload: { client_uuid: string; [k: string]: unknown },
  opts?: { allowOffline?: boolean; offlineErr?: string },
): Promise<SubmitResult> {
  try {
    const res = await post<{ receipt_no: string; uid: string }>("/sales", payload);
    setOnline(true);
    void flushOutbox();
    return { ok: true, offline: false, receipt_no: res.receipt_no, uid: res.uid };
  } catch (e) {
    // 5xx (server/cold-start/deploy) ham TRANSIENT — savdoni yo'qotmay navbatga qo'yamiz
    // (aks holда bitta 502/504 chekни butunlай yo'qotardi). 4xx (validatsiya/auth) — navbatга emas.
    const _st = (e as { status?: number })?.status;
    const _transient = isNetworkError(e) || (typeof _st === "number" && _st >= 500);
    if (_transient) {
      if (opts && opts.allowOffline === false) {
        setOnline(false);
        throw new Error(opts.offlineErr || "Internet kerak");
      }
      const _entry = { client_uuid: payload.client_uuid, payload, created_at: new Date().toISOString(),
        owner_id: useAuth.getState().employee?.id };
      const _saved = outboxAdd(_entry);
      if (!_saved) {
        // localStorage to'la/kvota — savdoni JIMGINA yo'qotmaymiz, dead-letter'ga ("N rad etildi").
        deadLetter(_entry, "localStorage to'la — navbatga saqlab bo'lmadi");
        setOnline(false);
        throw new Error(opts?.offlineErr || "Xotira to'la — savdoni saqlab bo'lmadi");
      }
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
