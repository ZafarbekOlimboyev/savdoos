import { create } from "zustand";

// 9 mavzu — mobil ilova bilan bir xil palitralar. "light" = Sof oq, "dark" = Tungi
// (eski saqlangan qiymatlar bilan orqaga mos).
export type Theme =
  | "light" | "dark" | "aurora" | "okean" | "ormon" | "grafit" | "kosmos" | "osmon" | "yalpiz";

// Tanlagich uchun metadata: mini-namuna ranglari (nomlar i18n'da: theme.<id>)
export const THEMES: { id: Theme; dark: boolean; bg: string; card: string; accent: string }[] = [
  { id: "dark",   dark: true,  bg: "#0f1420", card: "#151b28", accent: "#a99cf0" },
  { id: "aurora", dark: true,  bg: "#141334", card: "#151b28", accent: "#c5b9ff" },
  { id: "okean",  dark: true,  bg: "#0a1e33", card: "#0e2a44", accent: "#56c5f5" },
  { id: "ormon",  dark: true,  bg: "#0a1d16", card: "#0e2a20", accent: "#4fe0a0" },
  { id: "grafit", dark: true,  bg: "#17181c", card: "#202228", accent: "#7fb0ff" },
  { id: "kosmos", dark: true,  bg: "#0b1030", card: "#141636", accent: "#8b9cff" },
  { id: "light",  dark: false, bg: "#f4f6fb", card: "#ffffff", accent: "#6d5dd3" },
  { id: "osmon",  dark: false, bg: "#eef4ff", card: "#ffffff", accent: "#2563eb" },
  { id: "yalpiz", dark: false, bg: "#eff7f3", card: "#ffffff", accent: "#0e9f6e" },
];

const IDS = new Set(THEMES.map((t) => t.id));

function read(): Theme {
  try {
    const v = localStorage.getItem("savdoos_theme") as Theme | null;
    return v && IDS.has(v) ? v : "light";
  } catch {
    return "light";
  }
}

function apply(t: Theme) {
  try {
    localStorage.setItem("savdoos_theme", t);
  } catch {
    /* ignore */
  }
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-theme", t);
  }
}

interface ThemeState {
  theme: Theme;
  toggle: () => void; // tez kun/tun almashtirish (light <-> dark)
  set: (t: Theme) => void;
}

export const useTheme = create<ThemeState>((set, get) => ({
  theme: read(),
  toggle: () => {
    const cur = THEMES.find((x) => x.id === get().theme);
    const next: Theme = cur?.dark ? "light" : "dark";
    apply(next);
    set({ theme: next });
  },
  set: (t) => {
    apply(t);
    set({ theme: t });
  },
}));

// Ishga tushganda saqlangan mavzuni qo'llash (index.html'dagi inline skriptni to'ldiradi).
apply(read());
