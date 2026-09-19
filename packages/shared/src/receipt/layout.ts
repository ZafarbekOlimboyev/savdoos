// ReceiptDTO → ReceiptDoc (bloklar). Sof va deterministik: sana/vaqt, tasodif, lokal API ishlatilmaydi —
// bir xil kirish HAR DOIM bir xil satrlar beradi (golden sinovlar shunga tayanadi).
//
// Qoidalar:
//  - Har matn `cleanText` dan o'tadi (boshqaruv, bidi, zero-width belgilar yo'q).
//  - Hech bir `line` bloki `cols / size` ustundan uzun emas; sig'magan matn o'raladi, kesilmaydi.
//  - Summalar DTO'dan olinadi, qayta hisoblanmaydi (buxgalteriya haqiqati — server). Mos kelmasa
//    faqat ogohlantirish (`totals_mismatch`, `payments_mismatch`) — chek baribir saqlangan qiymatni ko'rsatadi.
//  - Qaysi maydon ko'rinishini `opts.template` hal qiladi (Manager'dagi saqlanmagan qoralama ham jonli
//    ko'rinsin); ma'lumot esa DTO'dan.
import type { Block, PaperWidth, ReceiptDTO, ReceiptDoc, ReceiptTemplate, RenderOptions } from "./types";
import { BUILTIN_TEMPLATE, COLS, DOTS } from "./types";
import { currencyLabel, decAdd, decCmp, decNeg, decSub, fmtMoney, fmtQty, isDecimal } from "./format";
import { labelsFor, methodLabel } from "./labels";
import { center, cleanLine as cleanLineRaw, cleanText as cleanTextRaw, pairLines, strWidth, wrapText } from "./text";
import { base64DecodedLength, isBase64 } from "./b64";
import { BARCODE_QUIET } from "./geometry";

const MAX_LOGO_HEIGHT = 1200;
const QR_MIN = 21;
const QR_MAX = 177;
const QR_MAX_PAYLOAD = 700;
const MAX_BARCODE_MODULES = 2000;
/**
 * Sarlavha/footer: YOZILGAN (o'ralmagan) qatorlar soni va belgi chegarasi — server `_clean_multiline`
 * (settings.py) bilan AYNI qoida. O'ralgan qatorlar sanalmaydi: server qabul qilgan matn har qanday
 * kenglikda to'liq chiqsin (58 mm da 30 dan ortiq o'ralgan qator ham). Eski ma'lumotdagi 2000 ta bo'sh
 * qator esa bittaga yig'iladi — metrlab qog'oz yo'q.
 */
export const MAX_TEMPLATE_LINES = 30;
export const MAX_TEMPLATE_CHARS = 2000;

/** Serverdan to'liq kelmagan (eski versiya) shablonni BUILTIN bilan to'ldiradi. */
export function normalizeTemplate(t: Partial<ReceiptTemplate> | null | undefined): ReceiptTemplate {
  const out: ReceiptTemplate = { ...BUILTIN_TEMPLATE };
  if (!t || typeof t !== "object") return out;
  const src = t as Record<string, unknown>;
  const o = out as unknown as Record<string, unknown>;
  for (const k of Object.keys(BUILTIN_TEMPLATE) as (keyof ReceiptTemplate)[]) {
    const v = src[k];
    if (v === undefined) continue;
    const def = BUILTIN_TEMPLATE[k];
    if (def === null ? v === null || typeof v === "string" : typeof v === typeof def) o[k] = v;
  }
  if (out.width_mm !== 58 && out.width_mm !== 80) out.width_mm = BUILTIN_TEMPLATE.width_mm;
  if (!["none", "receipt_id", "store_url"].includes(out.qr_mode)) out.qr_mode = "none";
  if (out.lang !== null && !["uz", "uzc", "ru", "ky"].includes(out.lang)) out.lang = null;
  if (!Number.isInteger(out.copies) || out.copies < 1 || out.copies > 3) out.copies = BUILTIN_TEMPLATE.copies;
  return out;
}

export function layoutReceipt(dto: ReceiptDTO, opts: RenderOptions): ReceiptDoc {
  const width_mm: PaperWidth = opts.width_mm === 58 ? 58 : 80;
  const cols = COLS[width_mm];
  const half = cols / 2;
  const L = labelsFor(opts.lang);
  const T = normalizeTemplate(opts.template);
  const cur = currencyLabel(opts.lang);
  const blocks: Block[] = [];
  const warnings: string[] = [];
  const warn = (w: string) => {
    if (!warnings.includes(w)) warnings.push(w);
  };
  // Har matn shu ikkisidan o'tadi: ortiqcha birlashuvchi belgi tashlansa (bir asosga > 2) — ogohlantirish.
  const marksDropped = () => warn("marks_dropped");
  const cleanText = (v: unknown) => cleanTextRaw(v, marksDropped);
  const cleanLine = (v: unknown) => cleanLineRaw(v, marksDropped);

  const isReturn = dto.kind === "RETURN";
  const store = dto.store ?? ({} as ReceiptDTO["store"]);
  const actor = dto.actor ?? ({} as ReceiptDTO["actor"]);
  const totals = dto.totals ?? ({} as ReceiptDTO["totals"]);
  const lines = Array.isArray(dto.lines) ? dto.lines : [];
  const payments = Array.isArray(dto.payments) ? dto.payments : [];
  if (dto.schema !== "binos.receipt.v1") warn(`schema:${cleanLine(dto.schema).slice(0, 40)}`);

  // --- summa yordamchilari (yaroqsiz qiymat chekni yiqitmaydi: "?" + ogohlantirish) ---
  const money = (v: unknown, field: string): string => {
    if (isDecimal(v)) return fmtMoney(v, opts.lang);
    warn(`bad_amount:${field}`);
    return "?";
  };
  const pos = (v: unknown): boolean => isDecimal(v) && decCmp(v, "0") > 0;
  const nonZero = (v: unknown): boolean => isDecimal(v) && decCmp(v, "0") !== 0;
  // Qaytarishda pul chiqadi — summalar "-" bilan (ASCII: kod sahifalarida U+2212 yo'q).
  const minus = (s: string) => (s === "0" || s === "?" ? s : "-" + s);
  const signed = (v: string, field: string): string => {
    if (!isDecimal(v)) return money(v, field);
    const c = decCmp(v, "0");
    if (c === 0) return fmtMoney("0");
    return c > 0 ? "+" + fmtMoney(v) : "-" + fmtMoney(decNeg(v));
  };

  // --- blok chiqaruvchilar ---
  const push = (text: string, bold = false, size: 1 | 2 = 1) => {
    const b: Block = { t: "line", text: text.replace(/ +$/, "") };
    if (bold) b.bold = true;
    if (size === 2) b.size = 2;
    blocks.push(b);
  };
  const centered = (raw: unknown, bold = false) => {
    for (const l of wrapText(cleanText(raw), cols)) push(center(l, cols), bold);
  };
  // Shablon matni (sarlavha/footer) — server `_clean_multiline` qoidasi: qator oxiri bo'shliqlari, boshidagi
  // va ketma-ket bo'sh qatorlar olinadi, ko'pi bilan MAX_TEMPLATE_LINES YOZILGAN qator va MAX_TEMPLATE_CHARS
  // belgi; keyin o'raladi va HAMMASI chiqadi. Kesish faqat eski/oflayn (server tozalamagan) ma'lumotda.
  const templateText = (raw: unknown, field: string) => {
    let src: string[] = [];
    for (const l of cleanText(raw).split("\n")) {
      const ln = l.replace(/ +$/, "");
      if (ln === "" && (src.length === 0 || src[src.length - 1] === "")) continue;
      src.push(ln);
    }
    let cut = src.length > MAX_TEMPLATE_LINES;
    src = src.slice(0, MAX_TEMPLATE_LINES);
    while (src.length > 0 && src[src.length - 1] === "") src.pop();
    let text = src.join("\n");
    // Belgi chegarasi server kabi kod nuqtalarida; "…" → "..." (cleanText) server sanog'ini oshirmasin.
    const cps = Array.from(text);
    const limit = MAX_TEMPLATE_CHARS + 2 * (String(raw ?? "").match(/…/g)?.length ?? 0);
    if (cps.length > limit) {
      cut = true;
      text = cps.slice(0, limit).join("").replace(/\s+$/, "");
    }
    if (cut) warn(`${field}_truncated`);
    for (const l of wrapText(text, cols)) push(center(l, cols));
  };
  const leftText = (raw: unknown, indent = 0) => {
    const pad = " ".repeat(indent);
    for (const l of wrapText(cleanText(raw), cols - indent)) push(pad + l);
  };
  const pair = (l: string, r: string, indent = 0, bold = false) => {
    for (const x of pairLines(cleanLine(l), cleanLine(r), cols, indent)) push(x, bold);
  };
  const rule = (char: "-" | "=") => blocks.push({ t: "rule", char });

  // 1) Bannerlar: nusxa / TEST / oflayn (bir nechtasi birga bo'lishi mumkin — masalan oflayn chek nusxasi).
  let banner = false;
  if (opts.copy?.kind === "REPRINT") {
    const no = opts.copy.no;
    const n = typeof no === "number" && Number.isInteger(no) && no > 0 ? ` #${no}` : "";
    centered(`*** ${L.copy}${n} ***`, true);
    banner = true;
  }
  if (dto.test) {
    centered(L.testTitle, true);
    centered(L.testSub);
    banner = true;
  }
  if (dto.provisional) {
    centered(L.offlineTitle, true);
    centered(L.offlineSub);
    banner = true;
  }
  if (banner) blocks.push({ t: "feed", lines: 1 });

  // 2) Logo — faqat shablon ruxsat bersa va yaroqli raster bo'lsa.
  if (T.show_logo && opts.logo) {
    const lg = opts.logo;
    const okDims =
      Number.isInteger(lg.width) && Number.isInteger(lg.height) &&
      lg.width > 0 && lg.width % 8 === 0 && lg.height > 0 && lg.height <= MAX_LOGO_HEIGHT;
    if (!okDims || !isBase64(lg.raster_b64) || base64DecodedLength(lg.raster_b64) !== (lg.width / 8) * lg.height) {
      warn("logo_invalid");
    } else if (lg.width > DOTS[width_mm]) {
      warn("logo_too_wide");
    } else {
      const b: Block = { t: "logo", width: lg.width, height: lg.height, raster_b64: lg.raster_b64 };
      if (typeof lg.png_data_uri === "string") b.png_data_uri = lg.png_data_uri;
      blocks.push(b);
    }
  }

  // 3) Sarlavha (shior), do'kon nomi, filial, manzil, telefon, STIR.
  if (T.header) templateText(T.header, "header");
  const name = cleanLine(T.store_display_name || store.name);
  if (name) {
    if (strWidth(name) <= half) push(center(name, half), true, 2);
    else centered(name, true);
  }
  if (T.show_branch && cleanLine(store.branch_name)) centered(`${L.branch}: ${cleanLine(store.branch_name)}`);
  const address = T.address || store.address;
  if (cleanLine(address)) centered(address);
  const phone = cleanLine(T.phone || store.phone);
  if (phone) centered(phone);
  if (T.show_stir && cleanLine(store.stir)) centered(`${L.stir}: ${cleanLine(store.stir)}`);
  rule("=");

  // 4) Qaytarish sarlavhasi + asl chek havolasi.
  if (isReturn) {
    centered(L.returnTitle, true);
    const o = dto.original;
    if (o && cleanLine(o.number)) {
      // Juftlik: tor qog'ozda sana alohida qatorga o'tadi, lekin sana/vaqt bo'linib ketmaydi.
      pair(`${L.original}: ${cleanLine(o.number)}`, cleanLine(o.issued_at_local));
    }
  }

  // 5) Meta: chek raqami + sana, kassir + kassa, xaridor.
  const docNo = cleanLine(dto.doc?.number);
  pair(`${L.receipt} ${docNo}`.trim(), cleanLine(dto.doc?.issued_at_local));
  const cashier = T.show_cashier && cleanLine(actor.cashier) ? `${L.cashier}: ${cleanLine(actor.cashier)}` : "";
  const till = T.show_till && cleanLine(actor.till_code) ? `${L.till}: ${cleanLine(actor.till_code)}` : "";
  if (cashier && till) pair(cashier, till);
  else if (cashier || till) leftText(cashier || till);
  if (T.show_customer && dto.customer && cleanLine(dto.customer.name)) {
    leftText(`${L.customer}: ${cleanLine(dto.customer.name)}`);
  }
  rule("-");

  // 6) Tovar qatorlari: nom to'liq kenglikda, keyin "  miqdor birlik × narx .. summa".
  lines.forEach((ln, i) => {
    if (cleanLine(ln.name)) leftText(ln.name);
    if (!isDecimal(ln.qty)) warn(`bad_qty:lines[${i}]`);
    const unit = cleanLine(ln.unit);
    const qty = cleanLine(fmtQty(String(ln.qty ?? ""), !!ln.weighted)) + (unit ? " " + unit : "");
    const price = money(ln.unit_price, `lines[${i}].unit_price`);
    const showDisc = T.show_discount && pos(ln.discount);
    // Chegirma alohida qatorda ko'rinsa — yalpi summa (qty×narx), aks holda sof summa: chek qo'shilsin.
    let amount = money(showDisc ? ln.gross : ln.total, `lines[${i}].${showDisc ? "gross" : "total"}`);
    if (isReturn) amount = minus(amount);
    pair(`${qty} × ${price}`, amount, 2);
    if (showDisc) pair(L.lineDiscount, "-" + money(ln.discount, `lines[${i}].discount`), 2);
  });
  rule("-");

  // 7) Jamlar. show_discount faqat QATOR chegirmalarini yashiradi; chek (sarlavha) chegirmasi hech bir
  // qatorga tegishli emas — yashirilsa qatorlar yig'indisi JAMI dan katta chiqardi, shu bois doim ko'rinadi.
  const showLineDisc = T.show_discount && pos(totals.line_discount);
  const showDocDisc = pos(totals.doc_discount);
  const showRounding = nonZero(totals.rounding);
  if (showLineDisc || showDocDisc || showRounding) {
    let sub: unknown = totals.subtotal;
    // Qator chegirmalari yashirilgan bo'lsa qatorlar sof summada — oraliq jami ham sof (ular yig'indisi):
    // "qatorlar = oraliq; oraliq − chek chegirmasi ± yaxlitlash = JAMI".
    if (!T.show_discount && isDecimal(totals.subtotal) && isDecimal(totals.line_discount)) {
      sub = decSub(totals.subtotal, totals.line_discount);
    }
    const s = money(sub, "totals.subtotal");
    pair(L.subtotal, isReturn ? minus(s) : s);
  }
  if (showLineDisc) pair(L.lineDiscount, "-" + money(totals.line_discount, "totals.line_discount"));
  if (showDocDisc) pair(L.discount, "-" + money(totals.doc_discount, "totals.doc_discount"));
  if (showRounding) pair(L.rounding, signed(isReturn ? decNeg(totals.rounding) : totals.rounding, "totals.rounding"));
  const totalLabel = isReturn ? L.returnTotal : L.total;
  const totalText = money(totals.total, "totals.total");
  const totalValue = `${isReturn ? minus(totalText) : totalText} ${cur}`;
  if (strWidth(cleanLine(totalLabel)) + 1 + strWidth(totalValue) <= half) {
    for (const x of pairLines(cleanLine(totalLabel), totalValue, half)) push(x, true, 2);
  } else {
    pair(totalLabel, totalValue, 0, true);
  }

  // Invariantlar (server kafolatlaydi; eski ma'lumot buzilgan bo'lsa — faqat ogohlantirish).
  if ([totals.subtotal, totals.line_discount, totals.doc_discount, totals.rounding, totals.total].every(isDecimal)) {
    const calc = decAdd(decSub(decSub(totals.subtotal, totals.line_discount), totals.doc_discount), totals.rounding);
    if (decCmp(calc, totals.total) !== 0) warn("totals_mismatch");
  }

  // 8) To'lovlar (sotuv) yoki qaytarilgan pul (qaytarish).
  if (!isReturn) {
    if (payments.length > 0 && isDecimal(totals.total) && payments.every((p) => isDecimal(p?.amount))) {
      let sum = "0";
      for (const p of payments) sum = decAdd(sum, p.amount);
      if (decCmp(sum, totals.total) !== 0) warn("payments_mismatch");
    }
    if (payments.length > 0 && (T.show_payment_breakdown || payments.length > 1)) {
      leftText(`${L.paymentTitle}:`);
      payments.forEach((p, i) => {
        pair(methodLabel(L, String(p.method ?? "")), money(p.amount, `payments[${i}].amount`), 2);
        if (p.given !== null && p.given !== undefined) pair(L.given, money(p.given, `payments[${i}].given`), 2);
        if (p.change !== null && p.change !== undefined) pair(L.change, money(p.change, `payments[${i}].change`), 2);
      });
    }
  } else if (dto.refund) {
    pair(`${L.refunded} (${methodLabel(L, String(dto.refund.method ?? ""))})`, money(dto.refund.amount, "refund.amount"));
  }
  rule("-");

  // 9) Footer (bo'sh bo'lsa standart minnatdorchilik — eski chek xulqi bilan bir xil).
  templateText(T.footer || L.footerDefault, "footer");

  // 10) Shtrix-kod (chek uid) va QR — shablon ruxsati + yaroqli ma'lumot.
  const bc = dto.barcode;
  if (T.show_barcode && bc) {
    const payload = cleanLine(bc.payload);
    if (
      payload && strWidth(payload) <= cols && typeof bc.modules === "string" &&
      bc.modules.length <= MAX_BARCODE_MODULES && /^[01]+$/.test(bc.modules)
    ) {
      // Hoshiya bilan 1 nuqtali modulda ham sig'masa — kesilgan shtrix-kod o'qilmaydi: faqat matn.
      if (bc.modules.length + 2 * BARCODE_QUIET <= DOTS[width_mm]) {
        blocks.push({ t: "feed", lines: 1 });
        blocks.push({ t: "barcode", payload, modules: bc.modules });
      } else {
        warn("barcode_too_wide");
      }
      centered(payload); // HRI matni — ikkala renderer'da bir xil, printer HRI o'chiq
    } else {
      warn("barcode_invalid");
    }
  }
  const qr = dto.qr;
  if (T.qr_mode !== "none" && qr && qr.kind === T.qr_mode) {
    const n = qr.size;
    const okMatrix =
      Number.isInteger(n) && n >= QR_MIN && n <= QR_MAX && Array.isArray(qr.matrix) && qr.matrix.length === n &&
      qr.matrix.every((r) => typeof r === "string" && r.length === n && /^[01]+$/.test(r));
    // Payload — QR ichidagi ma'lumot (uid yoki URL); boshqaruv belgisi bo'lishi uchun sabab yo'q.
    const okPayload =
      typeof qr.payload === "string" && qr.payload.length > 0 && qr.payload.length <= QR_MAX_PAYLOAD &&
      !/[\p{Cc}\p{Cf}]/u.test(qr.payload);
    if (okMatrix && okPayload) {
      blocks.push({ t: "feed", lines: 1 });
      blocks.push({ t: "qr", payload: qr.payload, size: n, matrix: qr.matrix.slice() });
    } else {
      warn("qr_invalid");
    }
  }

  // 11) TEST banneri oxirida ham — qog'oz qaysi uchidan qaralsa ham ko'rinsin.
  if (dto.test) centered(L.testTitle, true);

  // 12) Kesish (profilga mosini kodlovchi hal qiladi; qo'shimcha surish ham o'sha yerda).
  if (T.auto_cut) blocks.push({ t: "cut", kind: "partial" });

  return { width_mm, cols, blocks, warnings };
}
