import { create } from "zustand";

// SavdoOS 4 tilda: Rus (ru), Qirg'iz (ky), O'zbek lotin (uz), O'zbek kirill (uzc).
// Qirg'izistonda ochilish uchun standart — Rus tili; foydalanuvchi almashtira oladi.
export type Lang = "ru" | "ky" | "uz" | "uzc";

export const LANGS: { code: Lang; label: string; native: string }[] = [
  { code: "ru", label: "Русский", native: "Русский" },
  { code: "ky", label: "Кыргызча", native: "Кыргызча" },
  { code: "uz", label: "O‘zbekcha", native: "O‘zbekcha" },
  { code: "uzc", label: "Ўзбекча", native: "Ўзбекча" },
];

function read(): Lang {
  try {
    const v = localStorage.getItem("savdoos_lang");
    if (v === "ru" || v === "ky" || v === "uz" || v === "uzc") return v;
  } catch {
    /* ignore */
  }
  return "ru";
}

function apply(l: Lang) {
  try {
    localStorage.setItem("savdoos_lang", l);
  } catch {
    /* ignore */
  }
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("lang", l);
  }
}

interface LangState {
  lang: Lang;
  set: (l: Lang) => void;
}

export const useLang = create<LangState>((set) => ({
  lang: read(),
  set: (l) => {
    apply(l);
    set({ lang: l });
  },
}));

// Boshlang'ich holatда document lang atributini o'rnatib qo'yamiz
apply(read());
