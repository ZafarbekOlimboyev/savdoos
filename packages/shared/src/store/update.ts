import { create } from "zustand";

// Ilova yangilanish holati — Electron main'dan IPC orqali keladi (preload ko'prigi).
// Telegram uslubi: sidebar pastida "Yangilanish" tugmasi ko'rinadi.

export interface UpdateStatus {
  state: "idle" | "downloading" | "ready";
  version?: string;
  percent?: number;
}

declare global {
  interface Window {
    savdoosUpdate?: {
      onStatus: (cb: (data: UpdateStatus) => void) => void;
      install: () => void;
    };
  }
}

interface UpdateState extends UpdateStatus {
  install: () => void;
}

export const useUpdate = create<UpdateState>((set) => {
  // Bir marta obuna bo'lamiz (brauzer/dev rejimda savdoosUpdate yo'q — idle qoladi)
  if (typeof window !== "undefined" && window.savdoosUpdate) {
    window.savdoosUpdate.onStatus((data) => set({ ...data }));
  }
  return {
    state: "idle",
    version: undefined,
    percent: 0,
    install: () => window.savdoosUpdate?.install(),
  };
});
