// Mahsulot holati — Products va Dashboard uchun YAGONA formula.
// Ustuvorlik: expired > out > soon > low > mid > ok (har mahsulot faqat bitta toifada).

export type StatusKey = "ok" | "mid" | "low" | "soon" | "expired" | "out";

export function daysLeft(expiry: string | null | undefined): number | null {
  if (!expiry) return null;
  return Math.ceil((new Date(expiry + "T00:00:00").getTime() - Date.now()) / 86400000);
}

/**
 * Mahsulot darajasida ISHONSA BO'LADIGAN muddat.
 *
 * ⚠️  KUZATUVLI TOVARDA — HECH QACHON. `products.expiry_date` faqat katalog
 *     formasidan yoziladi; kirim esa muddatni PARTIYAGA yozadi
 *     (`stock_batches.expiry_date`), kuzatuv yoqilganda ham eski sana
 *     o'chirilmaydi va yangilanmaydi. Ya'ni kuzatuv yoqilgach bu ustun MUZLAB
 *     qoladi: eski sana abadiy «muddati o'tgan» bo'lib turaverardi, bo'sh sana
 *     esa muddati o'tgan partiyani «yo'q» qilib ko'rsatardi. Bunday tovarning
 *     muddat haqiqati — `/lots/alerts` va «Yaroqlilik muddati» ekrani.
 */
export function productExpiry(p: { expiry_date?: string | null; track_lots?: boolean }): string | null {
  return p.track_lots ? null : (p.expiry_date ?? null);
}

export function statusOf(p: { stock: number; min_stock?: number; expiry_date?: string | null; track_lots?: boolean }): StatusKey {
  const dl = daysLeft(productExpiry(p));
  if (dl !== null && dl < 0) return "expired";
  if (p.stock <= 0) return "out";
  if (dl !== null && dl <= 7) return "soon";
  const min = p.min_stock || 10;
  if (p.stock <= min) return "low";
  if (p.stock <= min * 2) return "mid";
  return "ok";
}
