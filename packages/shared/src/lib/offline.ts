// Offline-first qatlam: katalog keshi + sotuvlar navbati (outbox), localStorage'da.
// Native modul kerak emas — Electron renderer / brauzerda ishlaydi.

export const CACHE = {
  products: "savdoos_cache_products",
  cats: "savdoos_cache_categories",
  settings: "savdoos_cache_settings",
  outbox: "savdoos_outbox",
};

export function cacheSet(key: string, val: unknown): boolean {
  // true = saqlandi, false = xatolik (masalan localStorage to'la/kvota). Katalog keshи uchun
  // muhim emas, LEKIN outbox savdosi uchun MUHIM — chaqiruvchi false'ni ushlab, savdoni
  // JIMGINA yo'qotmasin (dead-letter'ga o'tkazsin).
  try { localStorage.setItem(key, JSON.stringify(val)); return true; } catch { return false; }
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

export function outboxAdd(item: OutboxSale): boolean {
  const a = outboxAll();
  a.push(item);
  return cacheSet(CACHE.outbox, a);   // false = saqlanmadi (kvota) — chaqiruvchi dead-letter qilsin
}

export function outboxRemove(clientUuid: string): void {
  cacheSet(CACHE.outbox, outboxAll().filter((x) => x.client_uuid !== clientUuid));
}
