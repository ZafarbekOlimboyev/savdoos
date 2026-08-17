import { create } from "zustand";

// Kassa ekranidagi hamburger → drawer menyu holati (dizayn: yashirin sidebar).
interface NavState {
  open: boolean;
  openNav: () => void;
  closeNav: () => void;
}

export const useNav = create<NavState>((set) => ({
  open: false,
  openNav: () => set({ open: true }),
  closeNav: () => set({ open: false }),
}));
