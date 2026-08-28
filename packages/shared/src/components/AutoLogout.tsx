import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { readPrefs } from "@/lib/prefs";
import { useAuth } from "@/store/auth";

/// Harakatsizlikda avto-chiqish (POS): Sozlamalar -> Xavfsizlik -> "Avtomatik chiqish
/// (daqiqa)". 0 = o'chiq. Har foydalanuvchi harakati (sichqoncha/klaviatura/teginish)
/// taymerni qayta boshlaydi; muddat o'tsa sessiya yopilib login sahifasiga qaytadi.
export function AutoLogout() {
  const logout = useAuth((s) => s.logout);
  const token = useAuth((s) => s.token);
  const nav = useNavigate();
  const lastActive = useRef(Date.now());

  useEffect(() => {
    if (!token) return;
    const touch = () => { lastActive.current = Date.now(); };
    const events: (keyof WindowEventMap)[] = ["mousemove", "mousedown", "keydown", "wheel", "touchstart"];
    events.forEach((e) => window.addEventListener(e, touch, { passive: true }));
    // Sozlama har tekshiruvda qayta o'qiladi — Sozlamalarda o'zgartirilsa darhol amal qiladi
    const timer = setInterval(() => {
      const min = readPrefs().autoLogoutMin;
      if (!min) return;
      if (Date.now() - lastActive.current >= min * 60_000) {
        logout();
        nav("/login");
      }
    }, 10_000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, touch));
      clearInterval(timer);
    };
  }, [token, logout, nav]);

  return null;
}
