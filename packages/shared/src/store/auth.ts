import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { useCart } from "@/store/cart";

export interface Employee {
  id: string;
  full_name: string;
  phone?: string | null;
  role_code: string;
  role_name: string;
  status: string;
  permissions: string[];
}

interface AuthState {
  token: string | null;
  employee: Employee | null;
  setAuth: (token: string, employee: Employee) => void;
  logout: () => void;
}

// Electron preload ko'prigi (safeStorage — OS darajasida shifrlangan saqlash). Brauzer/dev'da yo'q.
type SecureBridge = { get: (k: string) => string | null; set: (k: string, v: string) => void; del: (k: string) => void };
function bridge(): SecureBridge | null {
  try {
    const b = (window as any).savdoosSecure;
    return b && typeof b.get === "function" ? (b as SecureBridge) : null;
  } catch {
    return null;
  }
}

// Token OCHIQ localStorage'da turmasin (umumiy POS kompyuterida 12-soatlik sir edi):
// Electron'da safeStorage (DPAPI/Keychain) orqali shifrlab diskka yozamiz; brauzer/dev fallback —
// avvalgidek localStorage. Eski o'rnatmalardagi ochiq nusxa bir marta MIGRATSIYA qilinadi va o'chiriladi.
const secureStorage = {
  getItem: (name: string): string | null => {
    const b = bridge();
    if (b) {
      const v = b.get(name);
      if (v != null && v !== "") return v;
      // migratsiya: eski ochiq localStorage nusxasi -> shifrlangan saqlashga ko'chirib, o'chiramiz
      try {
        const legacy = localStorage.getItem(name);
        if (legacy) {
          b.set(name, legacy);
          localStorage.removeItem(name);
          return legacy;
        }
      } catch { /* ignore */ }
      return null;
    }
    try { return localStorage.getItem(name); } catch { return null; }
  },
  setItem: (name: string, value: string): void => {
    const b = bridge();
    if (b) { b.set(name, value); return; }
    try { localStorage.setItem(name, value); } catch { /* ignore */ }
  },
  removeItem: (name: string): void => {
    const b = bridge();
    if (b) { b.del(name); }
    try { localStorage.removeItem(name); } catch { /* ignore */ }
  },
};

export const useAuth = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      employee: null,
      setAuth: (token, employee) => set({ token, employee }),
      // Logout'да savat ham tozalanadi — aks holда shu terminalда keyingi kassir avvalgisining
      // savat qatorlarини ko'rib, bilmasдан to'lasa savdo NOTO'G'RI xodим/tenantга yozilardi.
      logout: () => {
        // SERVER tomonda ham bekor qilamiz (sec_epoch oshadi) — nusxalangan/o'g'irlangan token
        // "Chiqish"dan keyin 12 soat tirik qolmasin (mobil bilan izchil). Best-effort: offline
        // bo'lsa jimgina lokal chiqishga o'tamiz. DIQQAT: sec_epoch global — bu hisobning BOSHQA
        // qurilmalardagi sessiyalarini ham chiqaradi (hujjatlangan xatti-harakat).
        const t = get().token;
        if (t) {
          import("@/lib/api")
            .then(({ getServerUrl }) => {
              fetch(getServerUrl().replace(/\/+$/, "") + "/api/v1/auth/logout", {
                method: "POST",
                headers: { Authorization: `Bearer ${t}` },
              }).catch(() => { /* offline — lokal chiqish yetarli */ });
            })
            .catch(() => { /* ignore */ });
        }
        try { useCart.getState().resetAll(); } catch { /* ignore */ }
        set({ token: null, employee: null });
      },
    }),
    { name: "savdoos-auth", storage: createJSONStorage(() => secureStorage) }
  )
);
