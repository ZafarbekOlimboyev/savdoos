// Mahsulot holati — Products va Dashboard uchun YAGONA formula.
// Ustuvorlik: expired > out > soon > low > mid > ok (har mahsulot faqat bitta toifada).

export type StatusKey = "ok" | "mid" | "low" | "soon" | "expired" | "out";

export function daysLeft(expiry: string | null | undefined): number | null {
  if (!expiry) return null;
  return Math.ceil((new Date(expiry + "T00:00:00").getTime() - Date.now()) / 86400000);
}

export function statusOf(p: { stock: number; min_stock?: number; expiry_date?: string | null }): StatusKey {
  const dl = daysLeft(p.expiry_date);
  if (dl !== null && dl < 0) return "expired";
  if (p.stock <= 0) return "out";
  if (dl !== null && dl <= 7) return "soon";
  const min = p.min_stock || 10;
  if (p.stock <= min) return "low";
  if (p.stock <= min * 2) return "mid";
  return "ok";
}
