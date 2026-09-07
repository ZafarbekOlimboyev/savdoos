// JORIY smena identifikatsiyasi (shift_id + till_id + branch_id) — smena ochilgandan keyin
// SAQLANADI va smena yopilgunga qadar O'ZGARMAYDI.
//
// NEGA STORE KERAK: UI'dagi tanlov (select) smena ochilgandan keyin ISHONCHLI manba EMAS —
// ekran almashadi, ilova qayta yuklanadi, offline navbat keyinroq yuboriladi. Smenaga bog'langan
// har bir naqd amal identity'ni SHU saqlangan holatdan oladi. Kassir smena o'rtasida kassani
// ALMASHTIRA OLMAYDI: buning uchun smenani yopib, boshqa kassada yangi smena ochish kerak.
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export interface ShiftIdentity {
  shift_id: string;
  till_id: string;
  branch_id: string;
  till_code: string | null;
}

interface ShiftState {
  current: ShiftIdentity | null;
  setCurrent: (s: ShiftIdentity) => void;
  clear: () => void;
}

export const useShift = create<ShiftState>()(
  persist(
    (set) => ({
      current: null,
      setCurrent: (s) => set({ current: s }),
      clear: () => set({ current: null }),
    }),
    { name: "savdoos-shift", storage: createJSONStorage(() => localStorage) }
  )
);

/** Smenaga bog'langan so'rovlar uchun AYNAN kassa id (yo'q bo'lsa undefined — TAXMIN QILINMAYDI). */
export function currentTillId(): string | undefined {
  return useShift.getState().current?.till_id || undefined;
}
