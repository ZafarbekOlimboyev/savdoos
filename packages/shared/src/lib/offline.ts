// Offline-first qatlam: katalog keshi + sotuvlar navbati (outbox), localStorage'da.
// Native modul kerak emas — Electron renderer / brauzerda ishlaydi.

export const CACHE = {
  products: "savdoos_cache_products",
  cats: "savdoos_cache_categories",
  settings: "savdoos_cache_settings",
  outbox: "savdoos_outbox",
};

// ── SERVER BO'YICHA AJRATISH (namespace) ────────────────────────────────────
// Bitta .exe istalgan serverga ulanishi mumkin (login ekranida manzil o'zgartiriladi).
// Ilgari navbat va kesh GLOBAL kalitlarda edi: production'da ishlagan kassa staging'ga
// qaratilsa, PRODUCTION uchun yozilgan offline cheklar STAGING serveriga yuborilardi
// (va teskarisi) — bu haqiqiy savdoni noto'g'ri bazaga tushirardi. Katalog keshi ham
// aralashib, boshqa do'konning narxlari ko'rinardi.
//
// Endi har kalit server manzili bilan belgilanadi. Server almashsa — navbat ham, kesh ham
// ALMASHADI: bir muhitning ma'lumoti boshqasiga O'TMAYDI.
function serverTag(): string {
  let origin = "";
  try {
    origin = localStorage.getItem("savdoos_api_url") || "default";
  } catch {
    origin = "default";
  }
  // Qisqa, barqaror belgi (kalit o'qilishi uchun) — kriptografik hash SHART EMAS.
  let h = 0;
  for (let i = 0; i < origin.length; i++) h = (h * 31 + origin.charCodeAt(i)) | 0;
  return Math.abs(h).toString(36);
}

/** Kalitning SHU serverga tegishli nomi. Chaqiruv PAYTIDA hisoblanadi — server
 *  seans o'rtasida o'zgarsa ham to'g'ri kalit ishlatiladi. */
export function nsKey(base: string): string {
  return `${base}@${serverTag()}`;
}

// Eski (global) kalitlardan bir martalik ko'chirish. Mavjud o'rnatmalarda navbatdagi
// cheklar YO'QOLMASLIGI shart: bugungi kunga barcha ma'lumot JORIY serverga tegishli,
// shu bois uni aynan shu serverning nom maydoniga ko'chiramiz.
function migrateLegacyKeys(): void {
  try {
    for (const base of Object.values(CACHE)) {
      const legacy = localStorage.getItem(base);
      if (legacy !== null && localStorage.getItem(nsKey(base)) === null) {
        localStorage.setItem(nsKey(base), legacy);
        localStorage.removeItem(base);
      }
    }
  } catch {
    /* ignore */
  }
}
migrateLegacyKeys();

export function cacheSet(key: string, val: unknown): boolean {
  // true = saqlandi, false = xatolik (masalan localStorage to'la/kvota). Katalog keshи uchun
  // muhim emas, LEKIN outbox savdosi uchun MUHIM — chaqiruvchi false'ni ushlab, savdoni
  // JIMGINA yo'qotmasin (dead-letter'ga o'tkazsin).
  try { localStorage.setItem(nsKey(key), JSON.stringify(val)); return true; } catch { return false; }
}

export function cacheGet<T>(key: string, fallback: T): T {
  try {
    const s = localStorage.getItem(nsKey(key));
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
