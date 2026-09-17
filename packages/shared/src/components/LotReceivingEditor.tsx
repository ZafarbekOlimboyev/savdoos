// PARTIYALI KIRIM MUHARRIRI (Phase 5C, B2) — kirim qatori uchun partiyalar.
//
// ⚠️  BU YERDA BIZNES QARORI QABUL QILINMAYDI. Muddat o'tganmi, yig'indi
//     to'g'rimi, tannarx qayerdan olinadi — hammasini SERVER hal qiladi va rad
//     etadi. Bu modul faqat operatorga XATONI OLDINDAN aytadi: aks holda u
//     hujjatni to'ldirib, «Saqlash» bosgandan keyingina butun hujjat 400 bilan
//     qaytganini ko'rardi (aralash hujjatda kuzatuvsiz qatorlar bilan birga).
//
// ⚠️  MIQDOR — BUTUN MING ULUSHDA. Float qo'shish (0.1 + 0.2 = 0.30000000000000004)
//     ekranda ham, yig'indi solishtiruvida ham yolg'on farq ko'rsatardi. Shu bois
//     har miqdor BUTUN songa (ming ulush) aylantiriladi va faqat shu yerda
//     qo'shiladi; serverga esa `m / 1000` yuboriladi — JSON'ning eng qisqa
//     yozuvi 3 kasrgacha ANIQ qaytadi.
//
// ⚠️  UCHTADAN ORTIQ KASR — XATO, YAXLITLASH EMAS. Server ham aynan shunday
//     (`lot_receiving.validate_line`): qoldiq va partiya har xil yaxlitlanib
//     jimgina ajralmasin.
import { useEffect, useRef, useState } from "react";
import { Plus, Trash } from "@phosphor-icons/react";
import { get } from "@/lib/api";
import { inputStyle } from "@/components/ui";
import { useT } from "@/lib/i18n";

/** Bitta partiya qoralamasi (matn — operator terganidek). */
export interface LotDraft { key: string; qty: string; expiry: string; batch: string }

/** Bir qatorga ruxsat etilgan partiyalar soni — server ham AYNI chegarani qo'yadi. */
export const MAX_LOTS = 50;

export type IssueKind =
  | "lineQty" | "qty" | "decimals" | "mismatch" | "expiryMissing" | "expiryPast" | "tooMany";

export interface LotIssue { kind: IssueKind; key?: string }

export interface LotLineState {
  lineMilli: number | null;
  sumMilli: number;
  /** `lineMilli - sumMilli` (ming ulush); qator miqdori noto'g'ri bo'lsa `null`. */
  diffMilli: number | null;
  issues: LotIssue[];
  ok: boolean;
  /** Birinchi xato maydon: `{key, field}` — fokus shu yerga qaytariladi. */
  firstBad: { key: string | null; field: "line" | "qty" | "expiry" } | null;
}

export function newLotKey(): string {
  const c: any = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  return "l" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export const emptyLot = (qty = ""): LotDraft => ({ key: newLotKey(), qty, expiry: "", batch: "" });

/** Terilgan matnni tozalaydi: vergul -> nuqta, ortiqcha belgilar tashlanadi. */
export function qtyText(v: string): string {
  const s = String(v).replace(",", ".").replace(/[^\d.]/g, "");
  const i = s.indexOf(".");
  return i === -1 ? s : s.slice(0, i + 1) + s.slice(i + 1).replace(/\./g, "");
}

function norm(raw: string | number | null | undefined): string {
  if (raw === null || raw === undefined) return "";
  let s = String(raw).trim().replace(",", ".");
  if (s.startsWith(".")) s = "0" + s;          // «.5» — operator shunday teradi
  if (s.endsWith(".")) s = s.slice(0, -1);     // «1.» — hali terilmoqda
  return s;
}

/**
 * Miqdorni BUTUN ming ulushga o'giradi (`"1.235"` -> `1235`).
 *
 * `null` qaytadi: bo'sh, son emas, musbat emas, uchtadan ortiq kasr xonasi bor
 * yoki server chegarasidan (1e9) katta.
 */
export function milli(raw: string | number | null | undefined): number | null {
  const s = norm(raw);
  if (!/^\d+(\.\d{1,3})?$/.test(s)) return null;
  const [i, f = ""] = s.split(".");
  const m = Number(i) * 1000 + Number((f + "000").slice(0, 3));
  if (!Number.isFinite(m) || m <= 0 || m > 1e12) return null;
  return m;
}

/** Uchtadan ORTIQ kasr xonasi bormi (xato turini ajratish uchun). */
export function tooManyDecimals(raw: string | number | null | undefined): boolean {
  return /^\d+\.\d{4,}$/.test(norm(raw));
}

/** Ming ulushdan ko'rinadigan matn (`1235` -> `"1.235"`). */
export function fromMilli(m: number): string {
  const s = (Math.abs(m) / 1000).toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  return (m < 0 ? "-" : "") + s;
}

export function hasIssue(st: LotLineState, kind: IssueKind, key?: string): boolean {
  return st.issues.some((i) => i.kind === kind && (key === undefined || i.key === key));
}

/**
 * Qator + partiyalar holati. SERVER QOIDALARINING OYNASI, o'rniga emas.
 *
 * `bizDate` — filial ish kuni (serverdan). Noma'lum bo'lsa muddat O'TGANLIGI
 * TEKSHIRILMAYDI: brauzer sanasi bo'yicha qaror qilish filial vaqt zonasini
 * bilmagani uchun bir kunlik xato berardi va to'g'ri hujjatni bloklardi.
 */
export function lotLineState(
  lineQty: string | number | null | undefined,
  lots: LotDraft[],
  opts: { track_expiry?: boolean } = {},
  bizDate?: string | null,
): LotLineState {
  const issues: LotIssue[] = [];
  const lineMilli = milli(lineQty);
  if (lineMilli === null) issues.push({ kind: "lineQty" });
  if (lots.length > MAX_LOTS) issues.push({ kind: "tooMany" });

  let sum = 0;
  let bad = false;
  for (const l of lots) {
    const m = milli(l.qty);
    if (m === null) {
      bad = true;
      issues.push({ kind: tooManyDecimals(l.qty) ? "decimals" : "qty", key: l.key });
    } else {
      sum += m;
    }
    if (opts.track_expiry) {
      if (!l.expiry) issues.push({ kind: "expiryMissing", key: l.key });
      else if (bizDate && l.expiry < bizDate) issues.push({ kind: "expiryPast", key: l.key });
    }
  }
  if (!lots.length) { bad = true; issues.push({ kind: "qty" }); }
  // Yig'indi farqi FAQAT hamma miqdor to'g'ri bo'lsa ma'noli — aks holda
  // operator bir vaqtda ikkita («miqdor xato» + «yig'indi mos emas») xato
  // ko'rib, qaysi birini tuzatishni bilmasdi.
  const diff = lineMilli === null || bad ? null : lineMilli - sum;
  if (diff !== null && diff !== 0) issues.push({ kind: "mismatch" });

  const first = issues[0];
  const firstBad = !first ? null
    : first.kind === "lineQty" ? { key: null, field: "line" as const }
      : first.kind === "expiryMissing" || first.kind === "expiryPast"
        ? { key: first.key ?? null, field: "expiry" as const }
        : { key: first.key ?? null, field: "qty" as const };
  return { lineMilli, sumMilli: sum, diffMilli: diff, issues, ok: issues.length === 0, firstBad };
}

/**
 * Server so'raydigan `lots` massivi.
 *
 * ⚠️  `unit_cost` YUBORILMAYDI. Shartnoma uni qabul qiladi, lekin partiya narxi
 *     hujjat qatori narxidan ajralsa, COGS va yetkazib beruvchi qarzi bir-biriga
 *     zid bo'lardi. Partiya narxi — HAR DOIM qator narxi (`create_lots`).
 * ⚠️  `expiry_date` FAQAT muddat kuzatiladigan mahsulotda: FIFO mahsulotda sana
 *     yuborilsa server 400 beradi (va bu to'g'ri — sana FEFO'ni jimgina yoqardi).
 */
export function lotsPayload(lots: LotDraft[], trackExpiry: boolean) {
  return lots.map((l) => {
    const out: { qty: number; batch_number?: string; expiry_date?: string } = {
      qty: (milli(l.qty) ?? 0) / 1000,
    };
    const b = (l.batch || "").trim();
    if (b) out.batch_number = b;
    if (trackExpiry && l.expiry) out.expiry_date = l.expiry;
    return out;
  });
}

// ── FILIAL ISH KUNI ──────────────────────────────────────────────────────────
// ⚠️  BIR SO'ROV, BIR MARTA. Ish kuni FILIAL xossasi — har qator uchun so'rash
//     bir xil javobni qayta-qayta tortardi. Ruxsat yo'q bo'lsa (`ombor.view`
//     kirim xodimida bo'lmasligi mumkin) — JIMGINA maslahatsiz ishlaymiz:
//     server baribir yakuniy hakam.
let _biz: { at: number; date: string | null } | null = null;
const BIZ_TTL = 5 * 60_000;

export function invalidateBusinessDate() { _biz = null; }

export function useBusinessDate(probeProductId: string | null | undefined): string | null {
  const [date, setDate] = useState<string | null>(_biz ? _biz.date : null);
  useEffect(() => {
    let alive = true;
    if (!probeProductId) return;
    if (_biz && Date.now() - _biz.at < BIZ_TTL) { setDate(_biz.date); return; }
    get<{ business_date?: string }>(`/lots/products/${probeProductId}`)
      .then((d) => {
        _biz = { at: Date.now(), date: d?.business_date || null };
        if (alive) setDate(_biz.date);
      })
      .catch(() => {
        _biz = { at: Date.now(), date: null };     // ruxsat yo'q / xato -> maslahatsiz
        if (alive) setDate(null);
      });
    return () => { alive = false; };
  }, [probeProductId]);
  return date;
}

// ── MUHARRIR ─────────────────────────────────────────────────────────────────

export interface EditorProduct {
  id?: string | null; name: string; unit_code?: string | null; track_expiry?: boolean;
}

/**
 * Qator ostidagi partiya muharriri.
 *
 * ⚠️  ENTER HUJJATNI YUBORMAYDI. Kirim formasi bitta tugma bilan saqlanadi;
 *     partiya maydonida Enter bosilsa hujjat yarim to'ldirilgan holda ketardi.
 *     Enter — KEYINGI maydon.
 */
export function LotReceivingEditor({
  product, lineQty, lots, onChange, bizDate, testid = "lots", idPrefix = "lot",
}: {
  product: EditorProduct;
  lineQty: string;
  lots: LotDraft[];
  onChange: (lots: LotDraft[]) => void;
  bizDate?: string | null;
  testid?: string;
  idPrefix?: string;
}) {
  const t = useT();
  const box = useRef<HTMLDivElement | null>(null);
  const trackExpiry = !!product.track_expiry;
  const st = lotLineState(lineQty, lots, { track_expiry: trackExpiry }, bizDate);
  const unit = product.unit_code || "";

  const set = (key: string, patch: Partial<LotDraft>) =>
    onChange(lots.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const add = () => { if (lots.length < MAX_LOTS) onChange([...lots, emptyLot()]); };
  const remove = (key: string) => onChange(lots.filter((l) => l.key !== key));
  /** Qolgan miqdorni OXIRGI partiyaga yozadi (taxmin emas — operator bosadi). */
  const fill = () => {
    const d = st.diffMilli;
    if (!d || !lots.length) return;
    const last = lots[lots.length - 1];
    const cur = milli(last.qty) ?? 0;
    const next = cur + d;
    if (next <= 0) return;
    set(last.key, { qty: fromMilli(next) });
  };

  function onKey(e: React.KeyboardEvent) {
    if (e.key !== "Enter") return;
    e.preventDefault();                       // hujjat YUBORILMAYDI
    const el = box.current;
    if (!el) return;
    const f = Array.from(el.querySelectorAll<HTMLInputElement>("input"));
    const i = f.indexOf(document.activeElement as HTMLInputElement);
    if (i >= 0 && f[i + 1]) f[i + 1].focus();
  }

  const label: React.CSSProperties = { fontSize: 11.5, color: "var(--muted)", display: "block", marginBottom: 4 };
  const cell: React.CSSProperties = { ...inputStyle, height: 40, fontSize: 13 };

  return (
    <div ref={box} className="lot-screen" data-testid={testid} onKeyDown={onKey}
         style={{ border: "1px dashed var(--accent-border)", borderRadius: 12, padding: 12,
                  background: "var(--surface)", minWidth: 0 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 12.5 }}>{t("recv.lotsTitle")}</strong>
        <span role="status" aria-live="polite" data-testid={testid + "-sum"}
              style={{ fontSize: 12.5, color: st.ok ? "var(--muted)" : "var(--warn)" }}>
          {t("recv.lotSum", { s: fromMilli(st.sumMilli), q: st.lineMilli === null ? "—" : fromMilli(st.lineMilli), u: unit })}
          {st.diffMilli !== null && st.diffMilli > 0 && " · " + t("recv.lotRemaining", { n: fromMilli(st.diffMilli) })}
          {st.diffMilli !== null && st.diffMilli < 0 && " · " + t("recv.lotExcess", { n: fromMilli(-st.diffMilli) })}
        </span>
      </div>

      {lots.map((l, idx) => (
        <div key={l.key} data-testid={testid + "-row"}
             style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginTop: 10 }}>
          <label style={{ flex: "1 1 110px", minWidth: 0 }}>
            <span style={label}>{t("lot.qty")}{unit ? ` (${unit})` : ""}</span>
            <input value={l.qty} inputMode="decimal" data-testid={testid + "-qty-" + idx}
                   id={`${idPrefix}-qty-${l.key}`} aria-label={`${t("lot.qty")} ${idx + 1}`}
                   onChange={(e) => set(l.key, { qty: qtyText(e.target.value) })}
                   style={{ ...cell, borderColor: hasIssue(st, "qty", l.key) || hasIssue(st, "decimals", l.key) ? "var(--danger)" : undefined }} />
          </label>
          {trackExpiry ? (
            <label style={{ flex: "1 1 140px", minWidth: 0 }}>
              <span style={label}>{t("lot.expiry")} *</span>
              <input type="date" value={l.expiry} min={bizDate || undefined}
                     data-testid={testid + "-expiry-" + idx} id={`${idPrefix}-expiry-${l.key}`}
                     onChange={(e) => set(l.key, { expiry: e.target.value })}
                     style={{ ...cell, borderColor: hasIssue(st, "expiryMissing", l.key) || hasIssue(st, "expiryPast", l.key) ? "var(--danger)" : undefined }} />
            </label>
          ) : null}
          <label style={{ flex: "1 1 130px", minWidth: 0 }}>
            <span style={label}>{t("lot.batchNo")}</span>
            <input value={l.batch} maxLength={64} data-testid={testid + "-batch-" + idx}
                   onChange={(e) => set(l.key, { batch: e.target.value })} style={cell} />
          </label>
          <button type="button" className="btn btn-ghost" data-testid={testid + "-remove-" + idx}
                  aria-label={t("recv.lotRemove", { n: idx + 1 })} disabled={lots.length <= 1}
                  onClick={() => remove(l.key)}
                  style={{ height: 40, color: "var(--danger)", opacity: lots.length <= 1 ? 0.4 : 1 }}>
            <Trash size={15} aria-hidden />
          </button>
        </div>
      ))}

      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        <button type="button" className="btn btn-ghost" data-testid={testid + "-add"}
                onClick={add} disabled={lots.length >= MAX_LOTS}
                style={{ height: 38, display: "flex", alignItems: "center", gap: 6 }}>
          <Plus size={14} aria-hidden />{t("recv.addLot")}
        </button>
        {st.diffMilli !== null && st.diffMilli > 0 && (
          <button type="button" className="btn btn-ghost" data-testid={testid + "-fill"} onClick={fill}
                  style={{ height: 38 }}>{t("recv.fillRemaining")}</button>
        )}
      </div>

      {!trackExpiry && (
        <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}>{t("lot.expiryNotTracked")}</div>
      )}
      {trackExpiry && bizDate && (
        <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}
             data-testid={testid + "-bizdate"}>{t("recv.lotExpiryHint", { d: bizDate })}</div>
      )}
      {hasIssue(st, "decimals") && (
        <div role="alert" style={{ fontSize: 12, color: "var(--danger)", marginTop: 8 }}>{t("recv.lotDecimals")}</div>
      )}
      {trackExpiry && hasIssue(st, "expiryMissing") && (
        <div role="alert" style={{ fontSize: 12, color: "var(--warn)", marginTop: 8 }}>{t("lot.newLotExpiryRequired")}</div>
      )}
      {hasIssue(st, "expiryPast") && bizDate && (
        <div role="alert" style={{ fontSize: 12, color: "var(--danger)", marginTop: 8 }}>{t("recv.lotExpiryPast", { d: bizDate })}</div>
      )}
      {hasIssue(st, "tooMany") && (
        <div role="alert" style={{ fontSize: 12, color: "var(--danger)", marginTop: 8 }}>{t("recv.lotTooMany", { n: MAX_LOTS })}</div>
      )}
    </div>
  );
}

/**
 * BIRINCHI xato uchun operator tilidagi matn.
 *
 * ⚠️  BITTA XATO — BITTA XABAR. Hammasini birdan ko'rsatish («miqdor xato» +
 *     «yig'indi mos emas» + «muddat yo'q») operatorni qaysi biridan boshlashini
 *     bilmay qoldirardi; fokus ham aynan shu maydonga qaytariladi.
 */
export function lotIssueText(
  t: (k: string, v?: Record<string, string | number>) => string,
  st: LotLineState,
  bizDate?: string | null,
): string {
  const k = st.issues[0]?.kind;
  if (k === "lineQty") return t("recv.needQty");
  if (k === "decimals") return t("recv.lotDecimals");
  if (k === "expiryMissing") return t("lot.newLotExpiryRequired");
  if (k === "expiryPast") return t("recv.lotExpiryPast", { d: bizDate || "" });
  if (k === "mismatch") return t("recv.lotMismatch");
  if (k === "tooMany") return t("recv.lotTooMany", { n: MAX_LOTS });
  return t("recv.lotQtyInvalid");
}

/** Tasdiqlangan qatorda ko'rinadigan bir qatorli xulosa. */
export function lotSummary(lots: LotDraft[]): string {
  const q = lots.map((l) => l.qty || "0").join(" + ");
  const d = lots.map((l) => l.expiry).filter(Boolean);
  return d.length ? `${q} · ${d.join(", ")}` : q;
}
