// Qurilma telemetriyasi — kassa serverga O'ZI haqida xabar beradi.
//
// NEGA: buzuvchi naqd relizidan oldin operator "barcha kassalar kerakli versiyadami?" degan
// savolga javob bera olishi kerak. Ilgari server buni BILMASDI — yagona yo'l kassirdan
// "Sozlamalar" ekranidagi versiyani og'zaki so'rash edi.
//
// FAQAT HISOBOT: bu yerdan hech narsa boshqarilmaydi. Server ham sonlarni O'YLAB TOPMAYDI —
// biz yubormasak `null` bo'lib qoladi ("bilmayman"), nol EMAS.

import { post } from "@/lib/api";
import { outboxAll } from "@/lib/offline";
import { failedSales } from "@/lib/sync";
import { useAuth } from "@/store/auth";

// Vite build vaqtida package.json'dan quyiladi (vite.config.ts > define).
declare const __APP_VERSION__: string;
declare const __APP_NAME__: string;

const DEVICE_KEY = "savdoos_device_uuid";

/** Shu o'rnatma uchun BARQAROR qurilma identifikatori (localStorage'da qoladi).
 *  Mashina "barmoq izi" OLINMAYDI — operatorga kerak bo'lgani shunchaki barqaror kalit. */
export function deviceUuid(): string {
  try {
    const saved = localStorage.getItem(DEVICE_KEY);
    if (saved) return saved;
    const v: string = (crypto as any)?.randomUUID?.() ||
      `dev-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(DEVICE_KEY, v);
    return v;
  } catch {
    return "unknown-device";
  }
}

export function appVersion(): string {
  try { return typeof __APP_VERSION__ === "string" ? __APP_VERSION__ : "unknown"; } catch { return "unknown"; }
}
function appName(): string {
  try { return typeof __APP_NAME__ === "string" ? __APP_NAME__ : "pos"; } catch { return "pos"; }
}

let lastSent = 0;
const MIN_INTERVAL_MS = 10 * 60 * 1000;   // 10 daqiqa — server bu ma'lumotni tez-tez talab qilmaydi

/** Serverga bir marta xabar beradi. Xatolar YUTILADI: telemetriya savdoni to'xtatmasligi shart. */
export async function sendHeartbeat(force = false): Promise<void> {
  const st = useAuth.getState();
  if (!st.token) return;                       // login qilinmagan — yuboradigan kontekst yo'q
  const now = Date.now();
  if (!force && now - lastSent < MIN_INTERVAL_MS) return;
  lastSent = now;
  try {
    await post("/fleet/heartbeat", {
      device_uuid: deviceUuid(),
      app_version: appVersion(),
      app_name: appName(),
      platform: (window as any)?.savdoos?.platform || "unknown",
      // branch_id ATAYLAB yuborilmaydi: server uni autentifikatsiyalangan xodimdan oladi.
      // Mijozdan kelgan filialga ishonish qurilmaga o'zini boshqa filialniki deb ko'rsatishga
      // yo'l ochardi; server tomondagi manba bittagina va ishonchli.
      // HAQIQIY sonlar — taxmin emas
      pending_ops: outboxAll().length,
      failed_ops: failedSales().length,
    });
  } catch {
    /* jim: telemetriya hech qachon kassani to'xtatmaydi */
  }
}

/** Ilova ishga tushganda chaqiriladi: darhol bir marta + davriy. */
export function startFleetHeartbeat(): () => void {
  void sendHeartbeat(true);
  const t = setInterval(() => void sendHeartbeat(), MIN_INTERVAL_MS);
  return () => clearInterval(t);
}
