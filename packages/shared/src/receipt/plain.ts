// ReceiptDoc → oddiy matn satrlari (golden sinovlar, jurnal, "satr cols dan oshmasin" tekshiruvi).
// Ikki barobar (size 2) satr har belgidan keyin bo'shliq bilan yoziladi — qog'ozdagi kengligi ko'rinsin.
import type { ReceiptDoc } from "./types";
import { center } from "./text";

export function docToText(doc: ReceiptDoc): string[] {
  const cols = doc.cols;
  const out: string[] = [];
  for (const b of doc.blocks) {
    switch (b.t) {
      case "line":
        out.push(b.size === 2 ? Array.from(b.text).join(" ").replace(/ +$/, "") : b.text);
        break;
      case "rule":
        out.push(b.char.repeat(cols));
        break;
      case "feed":
        for (let i = 0; i < b.lines; i++) out.push("");
        break;
      case "logo":
        out.push(center(`[LOGO ${b.width}x${b.height}]`, cols));
        break;
      case "qr":
        out.push(center(`[QR ${b.size}x${b.size}]`, cols));
        break;
      case "barcode":
        out.push(center(`[CODE128 ${b.modules.length}]`, cols));
        break;
      case "cut":
        out.push(center(`[CUT ${b.kind}]`, cols));
        break;
    }
  }
  return out;
}
