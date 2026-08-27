// Offline-first qatlam: katalog keshi + sotuvlar navbati (outbox), localStorage'da.
// Native modul kerak emas — Electron renderer / brauzerda ishlaydi.

export const CACHE = {
  products: "savdoos_cache_products",
  cats: "savdoos_cache_categories",
  settings: "savdoos_cache_settings",
  outbox: "savdoos_outbox",
};

export function cacheSet(key: string, val: unknown): void {
  try { localStorage.setItem(key, JSON.stringify(val)); } catch { /* to'la bo'lsa e'tibor bermaymiz */ }
}

export function cacheGet<T>(key: string, fallback: T): T {
  try {
    const s = localStorage.getItem(key);
    return s ? (JSON.parse(s) as T) : fallback;
  } catch {
    return fallback;
  }
}

export interface OutboxSale {
  client_uuid: string;
  payload: unknown;
  created_at: string;
  // Savdoni yozgan kassir (employee id). Eski yozuvlarда bo'lmasligi mumkin.
  // flushOutbox faqat JORIY kassirникини yuboradi — aks holda A kassirning offline
  // savdosi B login qilganда B nomiga yozilib ketardi (server chekни token egasiga yozadi).
  owner_id?: string;
}

export function outboxAll(): OutboxSale[] {
  return cacheGet<OutboxSale[]>(CACHE.outbox, []);
}

export function outboxAdd(item: OutboxSale): void {
  const a = outboxAll();
  a.push(item);
  cacheSet(CACHE.outbox, a);
}

export function outboxRemove(clientUuid: string): void {
  cacheSet(CACHE.outbox, outboxAll().filter((x) => x.client_uuid !== clientUuid));
}
