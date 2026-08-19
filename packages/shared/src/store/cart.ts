import { create } from "zustand";

export interface CartLine {
  id: string;
  name: string;
  price: number;
  qty: number;
  article?: string;
}

interface CartState {
  items: CartLine[];
  add: (p: { id: string; name: string; price: number; article?: string; qty?: number }) => void;
  delta: (id: string, d: number) => void;
  remove: (id: string) => void;
  clear: () => void;
  subtotal: () => number;
  count: () => number;
}

export const useCart = create<CartState>((set, get) => ({
  items: [],
  add: (p) =>
    set((s) => {
      const q = p.qty ?? 1;
      const ex = s.items.find((i) => i.id === p.id);
      return ex
        ? { items: s.items.map((i) => (i.id === p.id ? { ...i, qty: i.qty + q } : i)) }
        : { items: [...s.items, { id: p.id, name: p.name, price: p.price, article: p.article, qty: q }] };
    }),
  delta: (id, d) =>
    set((s) => ({
      items: s.items
        .map((i) => (i.id === id ? { ...i, qty: i.qty + d } : i))
        .filter((i) => i.qty > 0),
    })),
  remove: (id) => set((s) => ({ items: s.items.filter((i) => i.id !== id) })),
  clear: () => set({ items: [] }),
  subtotal: () => get().items.reduce((t, i) => t + i.qty * i.price, 0),
  count: () => get().items.reduce((t, i) => t + i.qty, 0),
}));
