import { create } from "zustand";

export type Theme = "light" | "dark";

function read(): Theme {
  try {
    return (localStorage.getItem("savdoos_theme") as Theme) === "dark" ? "dark" : "light";
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
  toggle: () => void;
  set: (t: Theme) => void;
}

export const useTheme = create<ThemeState>((set, get) => ({
  theme: read(),
  toggle: () => {
    const next: Theme = get().theme === "dark" ? "light" : "dark";
    apply(next);
    set({ theme: next });
  },
  set: (t) => {
    apply(t);
    set({ theme: t });
  },
}));
