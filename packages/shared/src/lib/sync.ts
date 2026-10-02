import { useSyncExternalStore } from "react";
import { get, post } from "@/lib/api";
import { CACHE, cacheGet, cacheSet, nsKey, outboxAdd, outboxAll, outboxRemove, type OutboxSale } from "@/lib/offline";
import { bindDocIds, flushPrintReports, getReceiptProfile } from "@/lib/printing";
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
  // Tarmoq qaytdi: avval navbat (oflayn sotuv id'lari bog'lanadi), keyin chek hisobotlari.
  window.addEventListener("online", () => {
    setOnline(true);
    void flushOutbox().then(() => flushPrintReports()).catch(() => undefined);
  });
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
// Dead-letter ham SERVER bo'yicha ajratiladi (offline.ts dagi bir xil qoida): bir muhitda
// rad etilgan chek boshqa muhit ekranida ko'rinib qolmasin.
const FAILED_BASE = "savdoos_outbox_failed";
const FAILED_KEY_FN = () => nsKey(FAILED_BASE);
// `code` — server bergan BARQAROR sabab (`X-Error-Code`, masalan `OPEN_SHIFT_REQUIRED`).
// Matn tilga bog'liq va o'zgaruvchan; yarashtirish uchun MASHINA O'QIYDIGAN sabab kerak.
interface FailedSale extends OutboxSale { error: string; code?: string | null }
let failedListeners: (() => void)[] = [];
const emitFailed = () => failedListeners.forEach((l) => l());
function readFailed(): FailedSale[] {
  try { return JSON.parse(localStorage.getItem(FAILED_KEY_FN()) || "[]"); } catch { return []; }
}
// QA OFF-3: boolean qaytaradi — true=dead-letter'ga YOZILDI, false=xato (kvota/localStorage yo'q).
// Chaqiruvchi FALSE'да outbox'dan O'CHIRMASLIGI kerak (aks holda savdo HAM outbox'dan HAM dead-letter'dan
// g'oyib bo'lib SILENT LOST SALE bo'lardi — kod izohidagi "jimgina yo'qotmay" kafolati buzilardi).
function deadLetter(item: OutboxSale, error: string, code?: string | null): boolean {
  try {
    const failed = readFailed();
    failed.push({ ...item, error, code: code ?? null });
    localStorage.setItem(FAILED_KEY_FN(), JSON.stringify(failed.slice(-200)));
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
  try { localStorage.removeItem(FAILED_KEY_FN()); emitFailed(); } catch { /* ignore */ }
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
// `id` / `receipt_no` (Phase 5F): server sotuv id'si — oflayn chek jurnalini hujjatga bog'lash uchun.
// Eski server yubormaydi -> bog'lanmaydi (jurnal yozuvi mahalliy qoladi, sotuv baribir o'chiriladi).
type PushResult = { client_uuid?: string | null; ok?: boolean; retry?: boolean; error?: string;
                    code?: string | null; id?: string | null; receipt_no?: string };

/**
 * Oflayn sotuvlar serverda yozildi -> chop etish jurnali (client_uuid kaliti) server id'lariga bog'lanadi.
 * BO'LAK bo'yicha BITTA chaqiruv (har sotuvga emas): jurnal bir marta o'qilib/yoziladi — 500 ta sotuv
 * qayta ulanganda UI qotib qolmasin.
 * ⚠️  Outbox o'chirilgandan KEYIN va try/catch ichida: jurnal xatosi navbat holatiga HECH QACHON
 *     ta'sir qilmaydi (savdo qayta yuborilmaydi ham, yo'qolmaydi ham). Qaytaradi: bog'langan yozuvlar.
 */
function bindPrinted(pairs: Map<string, string>): number {
  if (!pairs.size) return 0;
  try {
    return bindDocIds(pairs);
  } catch {
    return 0;
  }
}
// QA OFF-2: server PushBody.sales max_length=1000 — navbatni 1000'lik BO'LAKLARga bo'lib yuboramiz.
const PUSH_CHUNK = 1000;
// Bir vaqtda faqat BITTA flushOutbox ishlaydi — aks holda 30s interval + online event +
// login + submitSale bir-birining ustidan yugurib, server rad etgan savdoni IKKI marta
// dead-letter qilib yuborishi mumkin (soxta "N rad etildi" / dublikat).
let flushing = false;
export async function flushOutbox(): Promise<void> {
  if (flushing) return;
  flushing = true;
  let bound = 0;
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
        const pairs = new Map<string, string>();   // client_uuid -> server id (chek jurnali uchun)
        for (const i of chunk) {
          const r = byUuid.get(i.client_uuid.toLowerCase());
          if (!r) continue;                          // server bu yozuvga javob bermadi — navbatda qoldiramiz
          if (r.ok) {                                 // qabul qilindi / idempotent dublikat
            outboxRemove(i.client_uuid);
            if (typeof r.id === "string" && r.id) pairs.set(i.client_uuid, r.id);
          }
          else if (r.retry) { /* QA OFF-1: TRANSIENT (409/deadlock/5xx) — outbox'da SAQLAYMIZ, keyingi flush qayta uradi (LOST SALE emas) */ }
          // QA OFF-3: PERMANENT rad — dead-letter'ga YOZILGACHGINA o'chiramiz. deadLetter kvota'да false
          // qaytarsa outbox'da QOLADI (jimgina yo'qotmaymiz — silent lost sale yopiq).
          else if (deadLetter(i, String(r.error || "server rad etdi"), r.code)) outboxRemove(i.client_uuid);
        }
        bound += bindPrinted(pairs);
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
    // Bog'langan oflayn cheklar hisobotini kutmasdan yuboramiz (keyingi 30s siklni kutmaydi).
    if (bound > 0) void flushPrintReports().catch(() => undefined);
  }
}

// ── OFFLINE SAVDO SIYOSATI (P9) ───────────────────────────────────────────────
// MUAMMO. `security.force_shift` yoqilgan do'konda server ochiq smenasiz savdoni RAD
// etadi (`services/sales.py`). Kassa esa `security` kalitini KO'RMAYDI (server uni
// kassirga bermaydi — `settings.py::_UI_KEYS`), shu bois offline chekni mahalliy
// yakunlab, PULNI OLIB, mijozni jo'natib yuborardi. Tarmoq qaytganda `/sync/push` uni
// 400 bilan rad etib dead-letter'ga tashlardi: pul olingan, savdo yo'q, naqd yozuvi
// yo'q, stok chiqimi yo'q. Buni PUL OLINISHIDAN OLDIN to'sish kerak.
//
// YECHIM. Qarorni SERVER beradi (`GET /shifts/offline-sale-policy` -> `{mode, reason}`)
// va u vaqt muhri bilan keshlanadi. Offline paytda oxirgi tasdiq ishlatiladi.
//
// NEGA BU ISHONCHLI. Serverdagi replay smenani TARIXIY izlaydi (`opened_at <= sold_at`
// va `closed_at IS NULL OR closed_at >= sold_at`), ya'ni savdo olingan paytda ochiq
// bo'lgan smena keyin yopilsa ham chek qabul qilinadi. Smenani esa FAQAT egasi yopadi
// va buning uchun internet kerak. Shu bois «hozir ochiq smena bor» tasdig'i offline
// davomida ham kuchda qoladi.
//
// NEGA MAHALLIY `useShift` YARAMAYDI. U ikki tomonga ham yolg'on: till'siz serverda
// smena OCHIQ bo'lsa ham bo'sh qoladi (`Shift.tsx` da `setCurrent` faqat till tanlansa
// yoziladi), va server smenani yopgan bo'lsa ham «ochiq» bo'lib turadi (u hech qachon
// `/shifts/current` bilan solishtirilmaydi). Darvoza server tasdig'iga tayanadi.
//
// FAIL-CLOSED. Tasdiq YO'Q, ESKIRGAN, BOSHQA kassirga tegishli yoki shakli notanish
// bo'lsa — offline yakunlash TO'SILADI. Qiymatning yo'qligi HECH QACHON ruxsat bermaydi.
export type OfflineSaleMode = "ALLOWED" | "BLOCKED";
interface OfflinePolicy { mode: OfflineSaleMode; reason: string | null; at: number; owner_id?: string }

// Tasdiq qancha vaqt kuchda? Onlaynda har 30 s yangilanadi, ya'ni uzilish boshlanganda
// muhr eng ko'pi 30 s eski bo'ladi. 8 soat — BITTA smena uzunligi: uzoq elektr/internet
// uzilishida savdo to'xtamasin, lekin kunlar oldin olingan tasdiq «tasdiq» sanalmasin.
export const OFFLINE_POLICY_TTL_MS = 8 * 60 * 60 * 1000;

function readPolicy(): OfflinePolicy | null {
  const p = cacheGet<OfflinePolicy | null>(CACHE.offlinePolicy, null);
  // Shakl tekshiruvi: buzilgan/eski yozuv «ruxsat» bo'lib o'qilmasin.
  if (!p || typeof p !== "object") return null;
  if (p.mode !== "ALLOWED" && p.mode !== "BLOCKED") return null;
  if (typeof p.at !== "number" || !isFinite(p.at)) return null;
  return p;
}

/** Oxirgi rad etilish sababi (`OPEN_SHIFT_REQUIRED` yoki null) — xabar matni uchun. */
export function offlineSaleReason(): string | null {
  const p = readPolicy();
  return p && p.mode === "BLOCKED" ? p.reason : null;
}

/**
 * Offline savdoni YAKUNLASH mumkinmi? FAQAT server AYNAN shu kassir uchun ALLOWED
 * degan va tasdiq hali eskirmagan bo'lsa — true. Qolgan hamma holatda false.
 */
export function offlineSaleAllowed(now: number = Date.now()): boolean {
  const p = readPolicy();
  if (!p || p.mode !== "ALLOWED") return false;
  // Tasdiq BOSHQA kassirga tegishli bo'lsa ishlatilmaydi (bir qurilmada smena almashadi).
  const me = useAuth.getState().employee?.id;
  if (!me || p.owner_id !== me) return false;
  // Soat ORQAGA surilsa (CMOS batareyasi, qo'lda o'zgartirish, xato NTP qadami) `now - at`
  // MANFIY bo'lib, tasdiq ABADIY «yangi» bo'lib qolardi. Kelajakdagi muhr — ishonchsiz.
  if (now < p.at) return false;
  return now - p.at <= OFFLINE_POLICY_TTL_MS;
}

/**
 * Siyosatni serverdan yangilaydi (har `syncTick`da). Xato/eski server (404) da kesh
 * TEGILMAYDI — mavjud tasdiq o'z TTL'i bo'yicha eskiradi va keyin darvoza yopiladi.
 * Ya'ni server bilan aloqa yo'qolishi ruxsatni CHO'ZMAYDI.
 */
export async function refreshOfflinePolicy(now: number = Date.now()): Promise<void> {
  const emp = useAuth.getState().employee;
  if (!useAuth.getState().token || !emp) return;
  // Savdo yo'li bilan AYNAN bir xil ruxsat — ruxsatsiz xodim serverni 403 bilan urmasin.
  const perms = Array.isArray(emp.permissions) ? emp.permissions : [];
  if (!perms.includes("kassa.sell")) return;
  try {
    // `client_time` — QURILMA soati. Server uni o'z soati va smena oynasi bilan solishtirib
    // qaror qiladi: xato soat chekni smena oynasidan chiqarib yuboradi va replay 400 oladi.
    // Qarorni SERVER beradi — klient o'zining soatiga o'zi hukm chiqarmaydi.
    const r = await get<{ mode?: string; reason?: string | null }>(
      `/shifts/offline-sale-policy?client_time=${encodeURIComponent(new Date(now).toISOString())}`);
    const mode: OfflineSaleMode | null =
      r?.mode === "ALLOWED" ? "ALLOWED" : r?.mode === "BLOCKED" ? "BLOCKED" : null;
    // Notanish javob shakli (yangi/boshqa server) — TAXMIN QILMAYMIZ, keshni tegmaymiz.
    if (!mode) return;
    cacheSet(CACHE.offlinePolicy, {
      mode, reason: typeof r?.reason === "string" ? r.reason : null, at: now, owner_id: emp.id,
    } satisfies OfflinePolicy);
  } catch { /* tarmoq/404/5xx — mavjud tasdiq TTL bo'yicha eskiradi (fail-closed) */ }
}

/** Sinovlar va logout uchun: saqlangan tasdiqni bekor qiladi. */
export function clearOfflinePolicy(): void {
  cacheSet(CACHE.offlinePolicy, null);
}

// ── Savdoni yuborish: onlayn bo'lsa darhol, aks holda navbatga ────────────
// `id` / `sold_at` (Phase 5F): server SaleOut'dan — chek shu id bo'yicha serverdan olinadi (printDoc).
// Oflayn: `id` yo'q, `sold_at` = navbat yozuvi vaqti (flush'da serverga ham AYNAN shu yuboriladi).
export interface SubmitResult { ok: boolean; offline: boolean; receipt_no?: string; uid?: string; id?: string; sold_at?: string }

// opts.allowOffline=false bo'lsa (masalan karta/QR "internetsiz" o'chiq) — tarmoq
// uzilса savdo navbatga QO'SHILMAYDI, aniq xato qaytaradi (opts.offlineErr matni bilan).
// Standart true — naqd/qarz kabi doim offline ishlaydigan usullar uchun (backward-compat).
export async function submitSale(
  payload: { client_uuid: string; [k: string]: unknown },
  opts?: { allowOffline?: boolean; offlineErr?: string },
): Promise<SubmitResult> {
  try {
    const res = await post<{ id?: string; receipt_no: string; uid: string; sold_at?: string }>("/sales", payload);
    setOnline(true);
    void flushOutbox();
    return {
      ok: true, offline: false, receipt_no: res.receipt_no, uid: res.uid,
      id: typeof res?.id === "string" ? res.id : undefined,
      sold_at: typeof res?.sold_at === "string" ? res.sold_at : undefined,
    };
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
      return { ok: true, offline: true, sold_at: _entry.created_at };
    }
    throw e; // validatsiya/auth xatosi — navbatga qo'shilmaydi
  }
}

// ── Chek profili (shablon + logo) keshi — oflayn chek uchun ─────────────
// Profil etag bilan keshlanadi (lib/printing.ts); bu yerda faqat URINISH chastotasi cheklanadi:
// 5 daqiqada ko'pi bilan bir marta (xato/403 bo'lsa ham har 30s so'rov yog'dirmaydi).
export const PROFILE_REFRESH_MS = 5 * 60 * 1000;
// Server `GET /receipt/profile` ruxsatlari bilan AYNAN bir xil — ruxsatsiz xodim 403 bilan urmasin.
const PROFILE_PERMS = ["kassa.sell", "sotuvlar.view", "sozlamalar.view", "qaytarishlar.create"];
let lastProfileTry = -Infinity;

function refreshReceiptProfile(now: number): void {
  const emp = useAuth.getState().employee;
  if (!useAuth.getState().token || !emp) return;
  const perms = Array.isArray(emp.permissions) ? emp.permissions : [];
  if (!PROFILE_PERMS.some((p) => perms.includes(p))) return;
  if (now - lastProfileTry < PROFILE_REFRESH_MS) return;
  lastProfileTry = now;
  void getReceiptProfile().catch(() => null);
}

/**
 * Bitta sinxronlash qadami: katalog, navbat, keyin chek hisobotlari (navbat BIRINCHI — oflayn sotuv
 * server id'si bog'lansin, so'ng uning chop etish yozuvi hisobot qilinsin) va chek profili.
 * Chop etish qadamlari mustaqil: ularning xatosi katalog/navbatga ta'sir qilmaydi.
 */
export async function syncTick(now: number = Date.now()): Promise<void> {
  const catalog = refreshCatalog();
  // P9: offline savdo siyosati — navbatdan OLDIN yangilanadi, chunki kassir keyingi chekni
  // navbat yuborilishini kutmasdan urishi mumkin. Xatosi qolgan qadamlarni to'xtatmaydi.
  const policy = refreshOfflinePolicy(now).catch(() => undefined);
  try {
    await flushOutbox();
  } catch { /* flushOutbox o'zi xatoni yutadi — bu qo'shimcha himoya */ }
  try {
    await flushPrintReports();
  } catch { /* hisobot keyingi siklda */ }
  try {
    refreshReceiptProfile(now);
  } catch { /* profil keyingi siklda */ }
  await policy;
  await catalog;
}

/** Sinovlar uchun: profil yangilash taymerini tiklaydi. */
export function _resetSyncTimers(): void {
  lastProfileTry = -Infinity;
}

let started = false;
export function startSync(): void {
  if (started) return;
  started = true;
  void syncTick();
  setInterval(() => {
    if (typeof navigator === "undefined" || navigator.onLine) void syncTick();
  }, 30000);
}
