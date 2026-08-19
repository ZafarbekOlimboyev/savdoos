// Server sozlamalaridan (GET /settings keshi) POS ko'rinish parametrlari.
// Dizayn prototipidagi _readPaySettings/_readFeatures'ning server-backed versiyasi.
import { CACHE, cacheGet } from "@/lib/offline";

export interface PosPrefs {
  karta: boolean;   // KARTA to'lov tugmasi
  qr: boolean;      // QR to'lov tugmasi
  qrMode: "manual" | "xpay"; // QR rejim: qo'lda tasdiq yoki XPAY avtomatik
  qarz: boolean;    // QARZ tugmasi + Mijozlar bo'limi
  returns: boolean; // Qaytarishlar bo'limi + chek barcode'i
  storeName: string;
  branchName: string;
}

interface RawSettings {
  payments?: { karta?: boolean; qr?: boolean; qarz?: boolean; qr_mode?: "manual" | "xpay" };
  features?: { returns?: boolean };
  store_info?: { name?: string; branch?: string };
}

// Default: hammasi yoqiq (seed shunday) — kesh hali bo'sh bo'lsa hech narsa yo'qolmasin.
export function readPrefs(): PosPrefs {
  const s = cacheGet<RawSettings>(CACHE.settings, {});
  return {
    karta: s.payments?.karta !== false,
    qr: s.payments?.qr !== false,
    qrMode: s.payments?.qr_mode === "xpay" ? "xpay" : "manual",
    qarz: s.payments?.qarz !== false,
    returns: s.features?.returns !== false,
    storeName: s.store_info?.name || "Oltin Do'kon",
    branchName: s.store_info?.branch || "Chilonzor filiali",
  };
}
