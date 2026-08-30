import { create } from "zustand";

export interface CartLine {
  id: string;
  name: string;
  price: number;
  qty: number;
  article?: string;
  weighted?: boolean; // tarozi mahsuloti — qty kasr (kg), ±1 stepper qo'llanmaydi
}

// ── Ko'p savat (parallel mijozlar) ──────────────────────────────────────
// Kassir bir vaqtda bir nechta mijozga xizmat qiladi: mijoz #1 mahsulot olib
// kelguncha #2 ga o'tadi, keyin qaytadi. `items` doim FAOL savat — eski API
// (add/delta/remove/clear/subtotal/count) o'zgarishsiz ishlayveradi.
const LS_KEY = "savdoos_pos_carts";
const MAX_CARTS = 6;

function load(): { carts: CartLine[][]; active: number } {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const d = JSON.parse(raw);
      if (Array.isArray(d.carts) && d.carts.length > 0) {
        const active = Math.min(Math.max(0, d.active | 0), d.carts.length - 1);
        return { carts: d.carts, active };
      }
    }
  } catch { /* ignore */ }
  return { carts: [[]], active: 0 };
}

function persist(carts: CartLine[][], active: number) {
  try { localStorage.setItem(LS_KEY, JSON.stringify({ carts, active })); } catch { /* ignore */ }
}

interface CartState {
  carts: CartLine[][];
  active: number;
  items: CartLine[]; // = carts[active] (oyna uchun ko'zgu)
  add: (p: { id: string; name: string; price: number; article?: string; qty?: number; weighted?: boolean }) => void;
  delta: (id: string, d: number) => void;
  remove: (id: string) => void;
  clear: () => void;          // faol savatni tozalaydi
  newCart: () => void;        // yangi mijoz savati (max 6)
  switchCart: (i: number) => void;
  closeCart: (i: number) => void;   // savatni yopadi (oxirgisi bo'lsa tozalaydi)
  finishActive: () => void;   // to'lov o'tdi: faol savat yopiladi/tozalanadi
  subtotal: () => number;
  count: () => number;
}

const init = load();

export const useCart = create<CartState>((set, get) => {
  // Faol savatni o'zgartirib, carts+items+localStorage'ni birga yangilaydi
  const mutate = (fn: (items: CartLine[]) => CartLine[]) =>
    set((s) => {
      const next = fn(s.carts[s.active] || []);
      const carts = s.carts.map((c, i) => (i === s.active ? next : c));
      persist(carts, s.active);
      return { carts, items: next };
    });

  return {
    carts: init.carts,
    active: init.active,
    items: init.carts[init.active] || [],
    add: (p) =>
      mutate((items) => {
        const q = p.qty ?? 1;
        const ex = items.find((i) => i.id === p.id);
        return ex
          ? items.map((i) => (i.id === p.id ? { ...i, qty: i.qty + q } : i))
          : [...items, { id: p.id, name: p.name, price: p.price, article: p.article, qty: q, weighted: p.weighted }];
      }),
    delta: (id, d) =>
      mutate((items) => items.map((i) => (i.id === id ? { ...i, qty: i.qty + d } : i)).filter((i) => i.qty > 0)),
    remove: (id) => mutate((items) => items.filter((i) => i.id !== id)),
    clear: () => mutate(() => []),
    newCart: () =>
      set((s) => {
        if (s.carts.length >= MAX_CARTS) return s;
        const carts = [...s.carts, []];
        const active = carts.length - 1;
        persist(carts, active);
        return { carts, active, items: [] };
      }),
    switchCart: (i) =>
      set((s) => {
        if (i < 0 || i >= s.carts.length) return s;
        persist(s.carts, i);
        return { active: i, items: s.carts[i] };
      }),
    closeCart: (i) =>
      set((s) => {
        if (i < 0 || i >= s.carts.length) return s;
        if (s.carts.length === 1) {
          persist([[]], 0);
          return { carts: [[]], active: 0, items: [] };
        }
        const carts = s.carts.filter((_, j) => j !== i);
        const active = Math.min(s.active > i ? s.active - 1 : s.active, carts.length - 1);
        persist(carts, active);
        return { carts, active, items: carts[active] };
      }),
    finishActive: () => get().closeCart(get().active),
    subtotal: () => get().items.reduce((t, i) => t + i.qty * i.price, 0),
    count: () => get().items.reduce((t, i) => t + i.qty, 0),
  };
});
