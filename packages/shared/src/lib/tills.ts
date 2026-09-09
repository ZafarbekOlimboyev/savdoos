// FIZIK kassa (TILL) identifikatsiyasi — POS uchun yagona manba.
//
// SHARTNOMA (server bilan izchil): T0 (cutover)'dan KEYIN server kassani TAXMIN QILMAYDI —
// "filialda bitta kassa bor" degan sabab ham YETARLI EMAS. Smena ochishda klient AYNAN
// `till_id` yuborishi SHART; keyingi smenaga bog'langan naqd amallar Shift.till_id'ni MEROS
// oladi. Shu bois bitta kassa bo'lganda ham UI uni AVTOMATIK tanlashi mumkin, LEKIN so'rovda
// id ANIQ yuborilishi kerak.
import { get } from "@/lib/api";

export interface Till {
  id: string;                  // UUID — smena ochishda AYNAN shu yuboriladi
  branch_id: string;
  type: "TILL" | "SAFE";
  code: string | null;         // (filial doirasida) barqaror identity, masalan "TILL-01"
  label: string | null;        // mashina-formati ("TILL code=... terminal=...") — UI'da ko'rsatilmaydi
  terminal_id: string | null;  // ixtiyoriy joriy qurilma bog'lanishi (custody identity EMAS)
  currency: string;
  status: "ACTIVE" | "ARCHIVED";
  active: boolean;
}

export interface TillsResult {
  /** false = cash quyi tizimi bu serverda YO'Q (SQLite/dev): TILL tushunchasi mavjud emas,
   *  smena eski yo'l bilan (till_id'siz) ochiladi. Bu "kassa topilmadi" bilan BIR XIL EMAS. */
  available: boolean;
  tills: Till[];
}

/** Kassirning JORIY filialidagi FAQAT ACTIVE kassalar (server tomonda filial + tenant bo'yicha
 *  cheklanadi). ARCHIVED yoki boshqa filial kassasi ro'yxatga TUSHMAYDI — aks holda tanlash
 *  mumkin bo'lib, server keyin rad etardi.
 *
 *  DIQQAT: cash quyi tizimi FAQAT Postgres'da. SQLite/dev serverda `/tills` 400 qaytaradi —
 *  bu XATO emas, "bu o'rnatmada kassa tushunchasi yo'q" degani. Shu holatni ALOHIDA qaytaramiz,
 *  aks holda POS dev muhitida smena ocholmay qolardi. */
export async function listActiveTills(): Promise<TillsResult> {
  try {
    const rows = await get<Till[]>("/tills?mine=true&active_only=true");
    return { available: true, tills: (rows || []).filter((t) => t.active && t.type === "TILL") };
  } catch (e: any) {
    if (isCashDisabled(e)) return { available: false, tills: [] };
    throw e;
  }
}

function isCashDisabled(e: any): boolean {
  const m = String(e?.message || "");
  return /cash/i.test(m) && /(yoqilmagan|не включ|not enabled|disabled)/i.test(m);
}

/** UI'da ko'rsatiladigan nom. `label` mashina-formati, shu bois `code` afzal. */
export function tillName(t: Till): string {
  return (t.code && t.code !== "LEGACY" ? t.code : null) || t.id.slice(0, 8);
}


export interface SafesResult { available: boolean; safes: Till[] }

/** Kassirning JORIY filialidagi ACTIVE SEYFLAR. Bo'sh ro'yxat QONUNIY holat: seyf MAJBURIY EMAS,
 *  u faqat inkassa (TILL->SAFE) uchun kerak. Seyf yo'q bo'lsa inkassa amali BERKITILADI —
 *  bir oyoqli OUT (pul manzilsiz chiqib ketishi) HECH QACHON yozilmasin. */
export async function listActiveSafes(): Promise<SafesResult> {
  try {
    const rows = await get<Till[]>("/safes?mine=true&active_only=true");
    return { available: true, safes: (rows || []).filter((s) => s.active && s.type === "SAFE") };
  } catch (e: any) {
    if (isCashDisabled(e)) return { available: false, safes: [] };
    throw e;
  }
}
