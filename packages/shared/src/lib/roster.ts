import { get, getCompanyCode, getServerUrl } from "@/lib/api";

/**
 * Kassir tanlash ro'yxati — qurilmada keshlanadi.
 *
 * ⚠️  NEGA UMUMAN KESH KERAK. PIN login endi `employee_id` talab qiladi: server
 *     PIN'ni do'kondagi HAR BIR xodim bilan qiyoslamaydi (u yo'l bitta
 *     autentifikatsiyasiz so'rovga 100 xodimli do'konda ~22 CPU-soniya turardi).
 *     Demak POS kassirni AVVAL tanlashi kerak.
 *
 * ⚠️  RO'YXAT ANONIM OLINMAYDI. `/auth/pin-roster` autentifikatsiya talab qiladi:
 *     qurilmani ega/menejer bir marta parol bilan sozlaydi, ro'yxat shu yerda
 *     saqlanadi va keyin kassirlar undan tanlaydi. Anonim foydalanuvchi do'kon
 *     kodi bilan xodimlar ro'yxatini OLA OLMAYDI.
 */
export type RosterItem = { id: string; full_name: string; branch_name?: string | null };

const KEY = "savdoos_pin_roster";

type Cached = { server: string; code: string; items: RosterItem[] };

function scope() {
  return { server: getServerUrl(), code: getCompanyCode() };
}

/** Keshdagi ro'yxat — server yoki do'kon kodi o'zgargan bo'lsa BO'SH qaytadi. */
export function getRoster(): RosterItem[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const c = JSON.parse(raw) as Cached;
    const s = scope();
    // Boshqa serverga yoki boshqa do'konga ulanilgan bo'lsa — eski ro'yxat
    // ishlatilmaydi (u yerda bu ID'lar umuman boshqa xodimlarga tegishli).
    if (c.server !== s.server || c.code !== s.code) return [];
    if (!Array.isArray(c.items)) return [];
    // ⚠️  ELEMENT SHAKLI ham tekshiriladi. Ilgari faqat "massivmi" tekshirilardi va
    //     qiymat to'g'ridan-to'g'ri RosterItem[] deb ishlatilardi: kesh buzilgan
    //     bo'lsa (masalan `items: [null]`) login ekrani `r.id` da yiqilib, OQ EKRAN
    //     berardi — ya'ni qurilmadagi bitta yozuv butun kassani to'xtatardi.
    return c.items.filter(
      (x): x is RosterItem =>
        !!x && typeof x === "object" && typeof (x as any).id === "string" &&
        typeof (x as any).full_name === "string",
    );
  } catch {
    return [];
  }
}

export function saveRoster(items: RosterItem[]): void {
  try {
    const s = scope();
    localStorage.setItem(KEY, JSON.stringify({ ...s, items } satisfies Cached));
  } catch {
    /* ignore */
  }
}

export function clearRoster(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Ro'yxatni serverdan yangilaydi. Faqat KIRGANDAN keyin chaqiriladi (token kerak).
 * Xato bo'lsa jim o'tadi: kesh eskirsa ham kassir ishlashda davom etsin —
 * oflayn do'konda tarmoq yo'qligi kassani to'xtatmasligi kerak.
 */
export async function refreshRoster(): Promise<RosterItem[]> {
  try {
    const items = await get<RosterItem[]>("/auth/pin-roster");
    if (Array.isArray(items)) {
      saveRoster(items);
      return items;
    }
  } catch {
    /* tarmoq yo'q / ruxsat yo'q — keshdagi ro'yxat qoladi */
  }
  return getRoster();
}
