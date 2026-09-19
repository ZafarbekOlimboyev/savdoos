// Oflayn sotuvning VAQTINCHALIK cheki — server hali ko'rmagan sotuv uchun, POS yuborgan aniq payload'dan.
//
// ⚠️  Buxgalteriya haqiqati server'da: bu chek `provisional: true` bilan chiqadi va layout uni
//     "OFLAYN — VAQTINCHALIK" banneri bilan belgilaydi. Raqam — "OFFLINE-XXXXXXXX" (client_uuid boshi),
//     haqiqiy chek raqami sinxronlangandan keyin serverdan olinadi (nusxa chop etish orqali).
import type { PayMethod, ReceiptDTO, ReceiptTemplate } from "./types";
import { decMul, decRound, decSub, decSum } from "./format";
import { normalizeTemplate } from "./layout";

export interface ProvisionalInput {
  client_uuid: string;
  lines: { name: string; qty: string; unit_price: string; weighted: boolean; unit?: string | null }[];
  payments: { method: string; amount: string }[];
  given?: string | null;
  change?: string | null;
  total: string;
  store: ReceiptDTO["store"];
  cashier: string | null;
  issued_at_local: string;
  template: ReceiptTemplate;
  /** Ixtiyoriy: ISO vaqt va zona (bo'lmasa bo'sh satr — chekda faqat `issued_at_local` chiqadi). */
  issued_at?: string;
  tz?: string;
}

export function offlineNumber(client_uuid: string): string {
  const hex = String(client_uuid ?? "").replace(/[^0-9a-fA-F]/g, "").slice(0, 8).toUpperCase();
  return hex ? `OFFLINE-${hex}` : "OFFLINE";
}

/**
 * Noto'g'ri son (masalan "abc") → Error: vaqtinchalik chek ham noto'g'ri summa ko'rsatmasin.
 * JS sonidan kelgan qoldiq ("0.35200000000000004") 3/2 xonaga ROUND_HALF_UP bilan keltiriladi.
 */
export function provisionalSaleReceipt(input: ProvisionalInput): ReceiptDTO {
  const lines = (input.lines ?? []).map((l) => {
    const qty = decRound(l.qty, 3);
    const unit_price = decRound(l.unit_price, 2);
    const gross = decMul(qty, unit_price, 2);
    return {
      name: String(l.name ?? ""), qty, unit: l.unit ?? null, weighted: !!l.weighted,
      unit_price, gross, discount: "0.00", total: gross,
    };
  });
  const subtotal = decSum(lines.map((l) => l.gross), 2);
  const total = decRound(input.total, 2);
  const payments = (input.payments ?? []).map((p) => ({
    method: p.method as PayMethod,
    amount: decRound(p.amount, 2),
    given: null as string | null,
    change: null as string | null,
  }));
  // Naqd berilgan/qaytim faqat bitta naqd to'lovda ma'lum (server ham aralashda saqlamaydi).
  const cash = payments.filter((p) => p.method === "cash");
  if (cash.length === 1 && payments.length === 1 && input.given !== null && input.given !== undefined) {
    cash[0].given = decRound(input.given, 2);
    if (input.change !== null && input.change !== undefined) cash[0].change = decRound(input.change, 2);
  }
  return {
    schema: "binos.receipt.v1",
    kind: "SALE",
    test: false,
    provisional: true,
    doc: {
      id: null,
      number: offlineNumber(input.client_uuid),
      uid: null,
      issued_at: input.issued_at ?? "",
      issued_at_local: String(input.issued_at_local ?? ""),
      tz: input.tz ?? "",
      is_offline: true,
      status: "pending",
    },
    store: { ...input.store },
    actor: { cashier: input.cashier ?? null, till_code: null, terminal: null },
    customer: null,
    lines,
    totals: {
      currency: "UZS",
      subtotal,
      line_discount: "0.00",
      doc_discount: "0.00",
      rounding: decSub(total, subtotal, 2),
      total,
    },
    payments,
    refund: null,
    original: null,
    barcode: null,
    qr: null,
    logo: null,
    template: normalizeTemplate(input.template),
  };
}
