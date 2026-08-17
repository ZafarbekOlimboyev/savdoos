import { create } from "zustand";
import { persist } from "zustand/middleware";

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
      logout: () => set({ token: null, employee: null }),
    }),
    { name: "savdoos-auth" }
  )
);
