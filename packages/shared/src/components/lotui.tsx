import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowClockwise, CheckCircle, Question, Warning, WarningCircle } from "@phosphor-icons/react";
import { get } from "@/lib/api";
import { inputStyle } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { lotAvailability, type Bucket, type CostBasis, type LotAvailability } from "@/lib/lots";

/** Qidiruvni KECHIKTIRISH — har harfda server so'roviga chiqmaslik uchun. */
export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/**
 * Yuklanish / xato / bo'sh holat — HAR ekranda bir xil.
 *
 * ⚠️  XATO JIM QOLMAYDI va boshi berk ko'cha bo'lmaydi: matn bilan birga
 *     «Qayta urinish» tugmasi beriladi. Operator ekranni yopib-ochishi shart emas.
 */
export function State({ loading, err, empty, emptyText, onRetry, children }: {
  loading?: boolean; err?: string; empty?: boolean; emptyText?: string;
  onRetry?: () => void; children?: ReactNode;
}) {
  const t = useT();
  if (err) {
    return (
      <div role="alert" data-testid="state-error" style={box}>
        <WarningCircle size={30} color="var(--danger)" aria-hidden />
        <div style={{ marginTop: 8, color: "var(--danger)", maxWidth: 520 }}>{err}</div>
        {onRetry && (
          <button className="btn btn-ghost" onClick={onRetry} data-testid="state-retry"
                  style={{ marginTop: 14, display: "inline-flex", alignItems: "center", gap: 7 }}>
            <ArrowClockwise size={16} aria-hidden />{t("lot.retry")}
          </button>
        )}
      </div>
    );
  }
  if (loading) {
    return (
      <div role="status" aria-live="polite" data-testid="state-loading" style={box}>
        <ArrowClockwise size={26} className="spin" color="var(--muted)" aria-hidden />
        <div style={{ marginTop: 8 }}>{t("lot.loading")}</div>
      </div>
    );
  }
  if (empty) {
    return (
      <div role="status" data-testid="state-empty" style={box}>
        <CheckCircle size={30} color="var(--faint)" aria-hidden />
        <div style={{ marginTop: 8 }}>{emptyText || t("lot.empty")}</div>
      </div>
    );
  }
  return <>{children}</>;
}

const box: React.CSSProperties = { padding: 44, textAlign: "center", color: "var(--muted)", fontSize: 13.5 };

// ── Tannarx sifati ───────────────────────────────────────────────────────────
// ⚠️  RANG YETARLI EMAS. Rang ko'rmaydigan operator uchun har nishonda MATN bor;
//     tushuntirish `title` (va `aria-label`) da — «taxminiy» so'zi nimani
//     anglatishini foyda hisobotidan qidirib yurmasin.
const COST: Record<CostBasis, { key: string; bg: string; fg: string }> = {
  known: { key: "exact", bg: "var(--ok-soft)", fg: "var(--ok)" },
  estimated: { key: "approx", bg: "var(--warn-soft)", fg: "var(--warn)" },
  unknown: { key: "unknown", bg: "var(--danger-soft)", fg: "var(--danger)" },
};

export function CostBadge({ basis, mixed }: { basis?: CostBasis; mixed?: boolean }) {
  const t = useT();
  const c = mixed || !basis ? { key: "mixed", bg: "var(--info-soft)", fg: "var(--info)" } : COST[basis];
  const label = t("lot.cost." + c.key);
  const hint = t("lot.costHint." + c.key);
  return (
    <span data-testid={"cost-" + (mixed ? "mixed" : basis)} title={hint} aria-label={`${label}: ${hint}`}
          style={{ fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 7, background: c.bg, color: c.fg, whiteSpace: "nowrap" }}>
      {label}
    </span>
  );
}

// ── Muddat guruhi ────────────────────────────────────────────────────────────
const BUCKET: Record<Bucket, { bg: string; fg: string }> = {
  expired: { bg: "var(--danger-soft)", fg: "var(--danger)" },
  expires_today: { bg: "var(--warn-soft)", fg: "var(--warn)" },
  within_7_days: { bg: "var(--warn-soft)", fg: "var(--warn)" },
  within_30_days: { bg: "var(--info-soft)", fg: "var(--info)" },
  later: { bg: "var(--ok-soft)", fg: "var(--ok)" },
  no_expiry: { bg: "var(--surface)", fg: "var(--muted)" },
};

export function ExpiryBadge({ bucket, daysLeft }: { bucket: Bucket; daysLeft?: number | null }) {
  const t = useT();
  const c = BUCKET[bucket] || BUCKET.no_expiry;
  const txt = bucket === "expired" && daysLeft != null
    ? t("lot.bucket.expiredDays", { n: Math.abs(daysLeft) })
    : t("lot.bucket." + bucket);
  return (
    <span data-testid={"bucket-" + bucket}
          style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11.5, fontWeight: 700, padding: "3px 9px", borderRadius: 7, background: c.bg, color: c.fg, whiteSpace: "nowrap" }}>
      {(bucket === "expired" || bucket === "expires_today") && <Warning size={12} weight="fill" aria-hidden />}
      {txt}
    </span>
  );
}

// ── Sahifalash ───────────────────────────────────────────────────────────────
export function Pager({ total, limit, offset, onOffset }: {
  total: number; limit: number; offset: number; onOffset: (n: number) => void;
}) {
  const t = useT();
  const prevRef = useRef<HTMLButtonElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  if (total <= limit) return null;
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav aria-label={t("lot.pages")} data-testid="pager"
         style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 12, padding: "12px 16px", flexWrap: "wrap" }}>
      <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("lot.range", { from, to, total })}</span>
      {/* ⚠️  FOKUS YO'QOLMASIN. Oxirgi sahifaga o'tganda bosilgan tugma O'CHADI va
          fokus <body> ga tushardi — keyingi Tab sahifani boshidan boshlardi.
          Shu bois bosilgandan keyin fokus QO'SHNI tugmaga beriladi. */}
      <button ref={prevRef} className="btn btn-ghost" data-testid="page-prev" disabled={offset <= 0}
              onClick={() => { onOffset(Math.max(0, offset - limit)); if (offset - limit <= 0) nextRef.current?.focus(); }}
              style={{ opacity: offset <= 0 ? 0.45 : 1 }}>{t("lot.prev")}</button>
      <button ref={nextRef} className="btn btn-ghost" data-testid="page-next" disabled={to >= total}
              onClick={() => { onOffset(offset + limit); if (offset + 2 * limit >= total) prevRef.current?.focus(); }}
              style={{ opacity: to >= total ? 0.45 : 1 }}>{t("lot.next")}</button>
    </nav>
  );
}

// ── Segment (tab/filtr) ──────────────────────────────────────────────────────
// Klaviatura: tugmalar TAB bilan kezib chiqiladi, `aria-pressed` holatni aytadi.
export function Segmented({ value, options, onChange, testid, label }: {
  value: string; options: [string, string][]; onChange: (v: string) => void;
  testid?: string; label?: string;
}) {
  return (
    <div role="group" aria-label={label} data-testid={testid}
         style={{ display: "inline-flex", gap: 2, padding: 3, borderRadius: 12, border: "1px solid var(--border)", background: "var(--card)", flexWrap: "wrap" }}>
      {options.map(([k, label]) => {
        const on = value === k;
        return (
          <button key={k} onClick={() => onChange(k)} aria-pressed={on} data-testid={(testid || "seg") + "-" + k}
                  style={{ height: 34, padding: "0 14px", borderRadius: 9, cursor: "pointer", font: "inherit", fontSize: 13,
                           // ⚠️  TANLOV RANG BILAN EMAS. Rang ko'rmaydigan operator uchun
                           //     tanlangan segment QALIN matn va ostki chiziq bilan ham
                           //     ajraladi (aria-pressed — ekran o'quvchi uchun).
                           fontWeight: on ? 800 : 600,
                           border: "none", borderBottom: on ? "2px solid var(--accent)" : "2px solid transparent",
                           background: on ? "var(--surface)" : "transparent",
                           color: on ? "var(--accent-strong)" : "var(--text3)" }}>
            {label}
          </button>
        );
      })}
    </div>
  );
}


/**
 * Modal/drawer uchun FOKUS boshqaruvi.
 *
 * ⚠️  FOKUS OYNA ICHIDA QOLADI. `aria-modal` ekran o'quvchiga «orqadagi sahifa
 *     yo'q» deydi, brauzer esa Tab'ni orqaga o'tkazaverardi — operator
 *     ko'rmayotgan jadval qatorlarini kezib yurardi.
 * ⚠️  YOPILGACH FOKUS QAYERDAN KELGAN BO'LSA O'SHA YERGA qaytadi; aks holda u
 *     <body> ga tushib, keyingi Tab sahifani BOSHIDAN boshlardi.
 */
export function useModalFocus(ref: React.RefObject<HTMLElement | null>, onClose: () => void, active = true) {
  useEffect(() => {
    if (!active) return;
    const prev = document.activeElement as HTMLElement | null;
    const focusables = () => Array.from(ref.current?.querySelectorAll<HTMLElement>(
      'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),'
      + 'textarea:not([disabled]),[tabindex]:not([tabindex="-1"])') || []);
    const t = setTimeout(() => { (focusables()[0] || ref.current)?.focus(); }, 0);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
      if (e.key !== "Tab") return;
      const f = focusables();
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      clearTimeout(t);
      document.removeEventListener("keydown", onKey, true);
      if (prev && document.body.contains(prev)) prev.focus();
    };
  }, [ref, onClose, active]);
}

// ── Xavfli amal tasdig'i ─────────────────────────────────────────────────────
/**
 * ⚠️  MATN O'ZGARMAYDI: «qoldiqni kamaytiradi» va «qaytarib bo'lmaydigan audit
 *     yozuvi» — operator nimani tasdiqlayotganini AYNAN bilishi shart.
 *     Tasdiqlash tugmasi fokusni O'ZIGA olmaydi (tasodifiy Enter bosilmasin).
 */
export function Confirm({ title, lines, confirmLabel, busy, onCancel, onConfirm }: {
  title: string; lines: ReactNode[]; confirmLabel: string; busy?: boolean;
  onCancel: () => void; onConfirm: () => void;
}) {
  const t = useT();
  const boxRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  // ⚠️  Ish ketayotganda (busy) Escape ham, backdrop ham YOPMAYDI: yarim
  //     yuborilgan amalni operator tasodifan «bekor qildim» deb o'ylamasin.
  useModalFocus(boxRef, () => { if (!busy) onCancel(); }, true);
  return (
    // ⚠️  BOSISH ORQADAGI OYNAGA O'TMAYDI. Tasdiq oynasi drawer ICHIDA chizilsa,
    //     uning fonini bosish drawer'ning o'z «tashqariga bosildi» ishlovchisiga
    //     ham yetib borardi va operator yozgan miqdorlar bilan birga butun
    //     oyna yopilib ketardi.
    <div onClick={(e) => { e.stopPropagation(); if (!busy) onCancel(); }}
         style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.55)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 40, padding: 16 }}>
      <div role="alertdialog" aria-modal="true" aria-label={title} data-testid="confirm"
           ref={boxRef}
           onClick={(e) => e.stopPropagation()}
           style={{ width: 460, maxWidth: "100%", background: "var(--card)", borderRadius: 18, padding: 24 }}>
        <div style={{ display: "flex", gap: 11, alignItems: "flex-start" }}>
          <Warning size={22} color="var(--danger)" weight="fill" aria-hidden />
          <div style={{ fontSize: 17, fontWeight: 800 }}>{title}</div>
        </div>
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8, fontSize: 13.5, color: "var(--text3)" }}>
          {lines.map((l, i) => <div key={i}>{l}</div>)}
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
          <button ref={cancelRef} className="btn btn-ghost" onClick={onCancel} disabled={busy}
                  data-testid="confirm-cancel" style={{ flex: 1, height: 46 }}>{t("common.cancel")}</button>
          <button className="btn" onClick={onConfirm} disabled={busy} data-testid="confirm-ok"
                  style={{ flex: 1, height: 46, background: "var(--danger)", color: "#fff", opacity: busy ? 0.6 : 1 }}>
            {busy ? t("lot.saving") : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Funksiya darvozasi ───────────────────────────────────────────────────────
// ⚠️  DARVOZANI SERVER OCHADI. Frontend «bu do'konda partiya bor» deb o'zi qaror
//     qilsa, kuzatuv yoqilmagan jonli do'konda operator yarim ishlaydigan
//     ekranlarni ko'rardi va «nega bo'sh?» degan savol bilan qolardi.
//     Ruxsat tekshiruvi ham shu yerda EMAS — server baribir tekshiradi; bu
//     faqat tugmani ko'rsatmaslik uchun (403 o'rniga tushunarli holat).
let _cache: { at: number; data: LotAvailability } | null = null;
let _inflight: Promise<LotAvailability> | null = null;
const TTL = 60_000;
// ⚠️  BITTA JAVOB — HAMMA NUSXAGA. Yon panel bir marta ulanadi va boshqa hech
//     qachon so'ramaydi; obuna bo'lmasa, birinchi mahsulotga kuzatuv yoqilganda
//     menyu ilova QAYTA ISHGA TUSHMAGUNCHA paydo bo'lmasdi.
const _subs = new Set<(d: LotAvailability) => void>();

export function invalidateAvailability() { _cache = null; }

export function useAvailability(): {
  data: LotAvailability | null; err: string; loading: boolean;
  reload: () => void; revalidate: () => void;
} {
  const [data, setData] = useState<LotAvailability | null>(_cache ? _cache.data : null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(!_cache);
  const alive = useRef(true);
  function run(force: boolean) {
    if (!force && _cache && Date.now() - _cache.at < TTL) { setData(_cache.data); setLoading(false); return; }
    if (force) _cache = null;
    setLoading(true);
    _inflight = _inflight || lotAvailability().then((d) => {
      _cache = { at: Date.now(), data: d };
      _subs.forEach((fn) => fn(d));      // boshqa ekranlar ham darhol biladi
      return d;
    }).finally(() => { _inflight = null; });
    _inflight.then((d) => { if (alive.current) { setData(d); setErr(""); } })
      .catch((e) => { if (alive.current) setErr(e.message); })
      .finally(() => { if (alive.current) setLoading(false); });
  }
  useEffect(() => {
    alive.current = true;
    _subs.add(setData);
    run(false);
    return () => { alive.current = false; _subs.delete(setData); };
    /* eslint-disable-next-line */
  }, []);
  // `reload` — TTL ni MENSIMAYDI (foydalanuvchi «qayta urinish» bosdi).
  // `revalidate` — TTL ni HURMAT qiladi (navigatsiyada arzon tekshiruv).
  return { data, err, loading, reload: () => run(true), revalidate: () => run(false) };
}

/** Kuzatuv umuman yoqilmagan do'konda ekran «ishlayotgandek» ko'rinmasin. */
export function DormantNotice({ av }: { av: LotAvailability }) {
  const t = useT();
  return (
    <div className="card" data-testid="lot-dormant" style={{ margin: 24, display: "flex", gap: 13, alignItems: "flex-start" }}>
      <Question size={22} color="var(--muted)" aria-hidden />
      <div>
        <div style={{ fontWeight: 700, marginBottom: 6 }}>{t("lot.dormantTitle")}</div>
        <div style={{ fontSize: 13.5, color: "var(--text3)", maxWidth: 620, lineHeight: 1.55 }}>{t("lot.dormantBody")}</div>
        {!av.can_enable && (
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 8 }}>{t("lot.dormantClosed")}</div>
        )}
      </div>
    </div>
  );
}

/** Yozuv tugmalari yopiq bo'lsa — SABABINI aytadi (jim o'chirilgan tugma emas). */
export function WriteClosed({ av }: { av: LotAvailability }) {
  const t = useT();
  // `can_write` faqat RUXSATNI aks ettiradi (server shuni tekshiradi) — sabab ham shu.
  const why = !av.permissions.edit ? t("lot.writeClosedPerm") : t("lot.writeClosedGeneric");
  return (
    <div data-testid="write-closed" role="note"
         style={{ display: "flex", gap: 9, alignItems: "flex-start", padding: "11px 14px", borderRadius: 11, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 12.5, fontWeight: 600 }}>
      <Warning size={16} weight="fill" aria-hidden />{why}
    </div>
  );
}

/**
 * Tor ekran (telefon) — JADVAL o'rniga KARTA.
 *
 * ⚠️  Gorizontal scroll'li jadval telefonda ishlamaydi: operator javon oldida
 *     turib ustunlarni surib yurmaydi. Shu bois 760px dan tor ekranda har qator
 *     kartaga aylanadi.
 */
export function useNarrow(max = 760): boolean {
  const [narrow, setNarrow] = useState(() => {
    try { return window.matchMedia(`(max-width: ${max}px)`).matches; } catch { return false; }
  });
  useEffect(() => {
    let mq: MediaQueryList;
    try { mq = window.matchMedia(`(max-width: ${max}px)`); } catch { return; }
    const on = () => setNarrow(mq.matches);
    on();
    mq.addEventListener ? mq.addEventListener("change", on) : mq.addListener(on);
    return () => { mq.removeEventListener ? mq.removeEventListener("change", on) : mq.removeListener(on); };
  }, [max]);
  return narrow;
}

/** Kichik «yorliq: qiymat» juftligi (karta ko'rinishida ishlatiladi). */
export function KV({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13 }}>
      <span style={{ color: "var(--muted)" }}>{k}</span>
      <span style={{ fontWeight: 600, textAlign: "right", minWidth: 0 }}>{v}</span>
    </div>
  );
}

// ── Mahsulot tanlagich ───────────────────────────────────────────────────────
export interface PickedProduct {
  id: string; name: string; unit_code: string | null; stock: number;
  // Muddat MAJBURIYLIGI shu bayroqdan bilinadi — partiyalar ro'yxatidan TAXMIN
  // qilinsa, partiyasi tugagan tovarda maydon "ixtiyoriy" bo'lib ko'rinardi.
  track_expiry?: boolean;
}

/**
 * Kuzatuvli mahsulotni QIDIRIB tanlash.
 *
 * ⚠️  RO'YXAT OLDINDAN YUKLANMAYDI. Katalogda 7000+ tovar bor; hammasini
 *     yuklab `<select>` ga solish ekranni ham, serverni ham cho'ktiradi.
 *     Qidiruv kamida 2 harfdan boshlanadi va SERVER `tracked=true` bilan
 *     faqat kuzatuvli tovarni qaytaradi.
 */
export function ProductPicker({ value, onPick, testid = "product-picker" }: {
  value: PickedProduct | null; onPick: (p: PickedProduct | null) => void; testid?: string;
}) {
  const t = useT();
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<PickedProduct[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const dq = useDebounced(q);
  const seq = useRef(0);

  useEffect(() => {
    if (value) return;
    const term = dq.trim();
    if (term.length < 2) { setRows([]); setErr(""); return; }
    const my = ++seq.current;
    setBusy(true);
    get<PickedProduct[]>(`/products?tracked=true&q=${encodeURIComponent(term)}`)
      .then((d) => { if (my === seq.current) { setRows(d.slice(0, 25)); setErr(""); } })
      .catch((e) => { if (my === seq.current) setErr(e.message); })
      .finally(() => { if (my === seq.current) setBusy(false); });
  }, [dq, value]);

  if (value) {
    return (
      <div data-testid={testid + "-picked"} style={{ display: "flex", alignItems: "center", gap: 10, justifyContent: "space-between", padding: "11px 14px", borderRadius: 11, background: "var(--surface)" }}>
        <span style={{ fontWeight: 700 }}>{value.name}</span>
        <button className="btn btn-ghost" data-testid={testid + "-clear"} onClick={() => { onPick(null); setQ(""); }}>
          {t("lot.change")}
        </button>
      </div>
    );
  }
  return (
    <div data-testid={testid}>
      <label>
        <span className="sr-only">{t("lot.pickProduct")}</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} data-testid={testid + "-input"}
               placeholder={t("lot.pickProduct")} style={{ ...inputStyle, height: 44 }} />
      </label>
      {err && <div role="alert" style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 8 }}>{err}</div>}
      {busy && <div role="status" style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 8 }}>{t("lot.loading")}</div>}
      {!busy && dq.trim().length >= 2 && rows.length === 0 && !err && (
        <div style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 8 }}>{t("lot.noTrackedFound")}</div>
      )}
      {rows.length > 0 && (
        <ul style={{ listStyle: "none", margin: "8px 0 0", padding: 0, maxHeight: 240, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 11 }} className="no-sb">
          {rows.map((p) => (
            <li key={p.id}>
              <button onClick={() => onPick(p)} data-testid={testid + "-opt-" + p.id}
                      style={{ width: "100%", textAlign: "left", font: "inherit", border: "none", background: "transparent", padding: "11px 14px", cursor: "pointer", display: "flex", justifyContent: "space-between", gap: 10 }}>
                <span>{p.name}</span>
                <span style={{ color: "var(--muted)" }} className="tabular">{p.stock} {p.unit_code || ""}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Dashboard kartalari — «bugun nimaga qarash kerak».
 *
 * ⚠️  ARZON SO'ROV. Faqat `/lots/alerts` chaqiriladi: u SANOQLARNI SQL da
 *     hisoblaydi, qatorlarni tortmaydi. Dashboard'ga partiya ro'yxatini
 *     yuklash 7000+ tovarli katalogda bosh sahifani sekinlashtirardi.
 *
 * ⚠️  KUZATUV YO'Q BO'LSA — UMUMAN KO'RINMAYDI (bo'sh «0» kartalari emas).
 */
export function LotAlertCards() {
  const t = useT();
  const av = useAvailability();
  // ⚠️  Kuzatuv o'chirilgan, lekin ochiq qarz qolgan do'konda ham kartalar
  //     ko'rinadi — aks holda yopilmagan pul dashboarddan yo'qolardi.
  const on = !!av.data && av.data.permissions.view
    && (av.data.tracked_products > 0 || av.data.has_lot_data);
  const [a, setA] = useState<LotAlertsShape | null>(null);
  useEffect(() => {
    if (!on) return;
    let alive = true;
    get<LotAlertsShape>("/lots/alerts")
      .then((d) => { if (alive) setA(d); })
      .catch(() => { /* dashboard xatosi butun sahifani buzmasin */ });
    return () => { alive = false; };
  }, [on]);
  if (!on || !a) return null;

  // ⚠️  BIRLIK ATAYLAB BOSHQA-BOSHQA. Muddat kartalari PARTIYA sanaydi, qarz
  //     kartasi esa HOLAT (bitta sotuvdagi aniqlanmagan qoldiq) — ikkisini bir
  //     xil "partiya" deb atash raqamlarni yolg'on qilardi.
  const items: { key: string; href: string; n: number; unit: string; sub: string; danger: boolean }[] = [
    { key: "alertExpired", href: "#/muddat", n: a.expiry.expired.lots, danger: true, unit: "lot.alertLots",
      sub: t("lot.alertPieces", { n: a.expiry.expired.qty }) },
    { key: "alertSoon", href: "#/muddat", n: a.expiry.expires_today.lots + a.expiry.within_7_days.lots, danger: false, unit: "lot.alertLots",
      sub: t("lot.alertPieces", { n: a.expiry.expires_today.qty + a.expiry.within_7_days.qty }) },
    { key: "alertShortfall", href: "#/aniqlanmagan-qoldiq", n: a.shortfalls.open_count, danger: false, unit: "lot.alertCases",
      sub: t("lot.alertPieces", { n: a.shortfalls.open_qty }) },
  ];
  if (items.every((i) => i.n === 0)) return null;

  return (
    <div data-testid="lot-alert-cards" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 18, marginBottom: 18 }}>
      {items.filter((i) => i.n > 0).map((i) => (
        <a key={i.key} href={i.href} data-testid={"lot-alert-" + i.key} className="card click-card"
           style={{ textDecoration: "none", padding: 22, display: "block" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--muted)", fontWeight: 500 }}>
            <Warning size={15} weight="fill" color={i.danger ? "var(--danger)" : "var(--warn)"} aria-hidden />
            {t("lot." + i.key)}
          </div>
          <div className="tabular" style={{ fontSize: 26, fontWeight: 800, marginTop: 8, color: i.danger ? "var(--danger)" : "var(--text)" }}>
            {t(i.unit, { n: i.n })}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{i.sub}</div>
        </a>
      ))}
    </div>
  );
}

interface LotAlertsShape {
  expiry: Record<"expired" | "expires_today" | "within_7_days" | "within_30_days", { lots: number; qty: number; value_at_risk: number }>;
  shortfalls: { open_count: number; open_qty: number; provisional_exposure_max: number };
}
