import { create } from "zustand";
import { persist } from "zustand/middleware";
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

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      employee: null,
      setAuth: (token, employee) => set({ token, employee }),
      // Logout'да savat ham tozalanadi — aks holда shu terminalда keyingi kassir avvalgisining
      // savat qatorlarини ko'rib, bilmasдан to'lasa savdo NOTO'G'RI xodим/tenantга yozilardi.
      logout: () => { try { useCart.getState().resetAll(); } catch { /* ignore */ } set({ token: null, employee: null }); },
    }),
    { name: "savdoos-auth" }
  )
);
