import { useSyncExternalStore } from "react";
import { get, post } from "@/lib/api";
import { CACHE, cacheSet, outboxAdd, outboxAll, outboxRemove } from "@/lib/offline";

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
    const [p, c] = await Promise.all([get("/products"), get("/categories")]);
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
export async function flushOutbox(): Promise<void> {
  const items = outboxAll();
  if (!items.length) return;
  try {
    await post("/sync/push", { sales: items.map((i) => i.payload) });
    items.forEach((i) => outboxRemove(i.client_uuid));
    setOnline(true);
    emitPending();
  } catch {
    setOnline(false);
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
      outboxAdd({ client_uuid: payload.client_uuid, payload, created_at: new Date().toISOString() });
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
