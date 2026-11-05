// Server sozlamalaridan (GET /settings keshi) POS ko'rinish parametrlari.
// Dizayn prototipidagi _readPaySettings/_readFeatures'ning server-backed versiyasi.
import { CACHE, cacheGet } from "@/lib/offline";

/**
 * BIR SAVAT QATORI uchun maksimal vazn (kg).
 *
 * ⚠️  Bu APPARAT limiti EMAS — POS uchun BOSHLANG'ICH BIZNES CHEKLOVI (ega
 *     qarori). Qiymat tasodifiy tanlanmagan: tarozi etiketkasining gramm
 *     maydoni AYNAN 5 xona (`scaleBarcode.ts` — `digits.slice(7, 12)`), ya'ni
 *     sistemaning O'Z vaznli-tovar domeni 99.999 kg da tugaydi. Qo'lda kiritish
 *     shu domendan chiqmasligi kerak.
 *
 * ⚠️  KONFIGURATSIYA CHOKI. Qiymat ataylab shu modulda — `readPrefs()` server
 *     `/settings` keshidan o'qiydi, shu bois kelajakda sozlama kaliti
 *     paydo bo'lganda o'zgarish AYNAN bitta joyda bo'ladi:
 *         max: s.sales?.max_line_weight_kg ?? MAX_LINE_WEIGHT_KG
 *     Hozir server kaliti YO'Q va bu task backend'ga tegmaydi.
 *
 * ⚠️  SERVER CHEGARASI BOSHQA (va KENGROQ): `schemas/sales.py:11`
 *     `qty: le=1e9`. Ya'ni bu gard FAQAT POS kiritish nuqtasida; mobil va
 *     `/sync/push` replay bu chegaraga bo'ysunmaydi.
 */
export const MAX_LINE_WEIGHT_KG = 99.999;

export interface PosPrefs {
  karta: boolean;   // KARTA to'lov tugmasi
  qr: boolean;      // QR to'lov tugmasi
  qrMode: "manual" | "xpay"; // QR rejim: qo'lda tasdiq yoki XPAY avtomatik
  offlineCard: boolean; // Karta internetsiz ishlaydimi (qo'lda tekshirish)
  offlineQr: boolean;   // QR (qo'lda rejim) internetsiz ishlaydimi
  qarz: boolean;    // QARZ tugmasi + Mijozlar bo'limi
  returns: boolean; // Qaytarishlar bo'limi + chek barcode'i
  storeName: string;
  branchName: string;
  autoLogoutMin: number; // harakatsizlikda avto-chiqish (daqiqa, 0 = o'chiq)
}

interface RawSettings {
  payments?: { karta?: boolean; qr?: boolean; qarz?: boolean; qr_mode?: "manual" | "xpay"; offline_card?: boolean; offline_qr?: boolean };
  features?: { returns?: boolean };
  store_info?: { name?: string; branch?: string };
  security?: { auto_logout?: number };
}

// Default: hammasi yoqiq (seed shunday) — kesh hali bo'sh bo'lsa hech narsa yo'qolmasin.
export function readPrefs(): PosPrefs {
  const s = cacheGet<RawSettings>(CACHE.settings, {});
  return {
    karta: s.payments?.karta !== false,
    qr: s.payments?.qr !== false,
    qrMode: s.payments?.qr_mode === "xpay" ? "xpay" : "manual",
    // Standart O'CHIQ: karta/QR odatda internet talab qiladi; egasi Sozlamadan yoqadi.
    offlineCard: s.payments?.offline_card === true,
    offlineQr: s.payments?.offline_qr === true,
    qarz: s.payments?.qarz !== false,
    returns: s.features?.returns !== false,
    // Neytral fallback — demo nomi emas (sotiladigan mahsulot: har mijoz o'z nomini ko'radi)
    storeName: s.store_info?.name || "Do'kon",
    branchName: s.store_info?.branch || "",
    autoLogoutMin: Math.max(0, Number(s.security?.auto_logout) || 0),
  };
}
