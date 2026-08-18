// Chek chop etish — yashirin iframe orqali (80mm termal printerga mos).
import { fmt } from "@/lib/format";

export interface ReceiptData {
  receipt_no: string;
  offline: boolean;
  store: string;
  branch: string;
  cashier: string;
  items: { name: string; qty: number; price: number; line: number }[];
  total: number;
  method: string;
  given: number;
  change: number;
  date: string;
  uid?: string;
  address?: string;
  phone?: string;
  header?: string;
  footer?: string;
}

const METHOD: Record<string, string> = { cash: "Naqd", card: "Karta", qr: "QR", credit: "Qarz (nasiya)" };

// Do'kon ma'lumotlari — Sozlamalar keshidan (chekda manzil/telefon/shior/footer ko'rinsin).
function shopInfo(): { address?: string; phone?: string; header?: string; footer?: string } {
  try {
    const s = JSON.parse(localStorage.getItem("savdoos_cache_settings") || "{}");
    return {
      address: s.store_info?.address,
      phone: s.store_info?.phone,
      header: s.receipt?.header,
      footer: s.receipt?.footer,
    };
  } catch {
    return {};
  }
}

export function printReceipt(input: ReceiptData): void {
  const info = shopInfo();
  const r: ReceiptData = {
    ...input,
    address: input.address ?? info.address,
    phone: input.phone ?? info.phone,
    header: input.header ?? info.header,
    footer: input.footer ?? info.footer,
  };
  const rows = r.items
    .map(
      (it) =>
        `<tr><td class="n">${escapeHtml(it.name)}</td><td class="q">${it.qty}×${fmt(it.price)}</td><td class="t">${fmt(it.line)}</td></tr>`
    )
    .join("");

  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    @page { size: 80mm auto; margin: 0; }
    * { font-family: "Consolas", monospace; }
    body { width: 76mm; margin: 0 auto; padding: 4mm 2mm; color: #000; font-size: 12px; }
    h1 { font-size: 16px; text-align: center; margin: 0 0 2px; }
    .sub { text-align: center; font-size: 11px; margin-bottom: 6px; }
    .line { border-top: 1px dashed #000; margin: 6px 0; }
    table { width: 100%; border-collapse: collapse; }
    td { padding: 1px 0; vertical-align: top; }
    td.q { text-align: center; font-size: 10px; color: #333; white-space: nowrap; padding: 0 4px; }
    td.t { text-align: right; white-space: nowrap; }
    td.n { word-break: break-word; }
    .tot { display: flex; justify-content: space-between; font-size: 15px; font-weight: bold; margin-top: 4px; }
    .row { display: flex; justify-content: space-between; font-size: 11px; }
    .foot { text-align: center; font-size: 11px; margin-top: 8px; }
    .badge { text-align:center; font-size:10px; border:1px dashed #000; padding:2px; margin-top:6px; }
  </style></head><body>
    ${r.header ? `<div class="sub" style="font-weight:bold;">${escapeHtml(r.header)}</div>` : ""}
    <h1>${escapeHtml(r.store)}</h1>
    <div class="sub">${escapeHtml(r.branch)}${r.address ? `<br/>${escapeHtml(r.address)}` : ""}${r.phone ? `<br/>${escapeHtml(r.phone)}` : ""}</div>
    <div class="row"><span>Chek: ${escapeHtml(r.receipt_no)}</span><span>${escapeHtml(r.cashier)}</span></div>
    <div class="row"><span>${escapeHtml(r.date)}</span></div>
    <div class="line"></div>
    <table>${rows}</table>
    <div class="line"></div>
    <div class="tot"><span>JAMI</span><span>${fmt(r.total)}</span></div>
    <div class="row"><span>To'lov: ${METHOD[r.method] || r.method}</span></div>
    ${r.method === "cash" && r.given > 0 ? `<div class="row"><span>Berildi</span><span>${fmt(r.given)}</span></div><div class="row"><span>Qaytim</span><span>${fmt(r.change)}</span></div>` : ""}
    ${r.offline ? `<div class="badge">OFLAYN — sinxronlanmoqda</div>` : ""}
    <div class="foot">${escapeHtml(r.footer || "Xaridingiz uchun rahmat!")}<br/>SavdoOS</div>
  </body></html>`;

  const iframe = document.createElement("iframe");
  iframe.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;";
  document.body.appendChild(iframe);
  const doc = iframe.contentWindow?.document;
  if (!doc) return;
  doc.open();
  doc.write(html);
  doc.close();
  iframe.contentWindow?.focus();
  setTimeout(() => {
    iframe.contentWindow?.print();
    setTimeout(() => document.body.removeChild(iframe), 1500);
  }, 300);
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] || c));
}
