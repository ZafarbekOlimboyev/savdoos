// Manager «Chek» sozlamalari (Phase 5F) — Sozlamalar → «Chek va printer» bo'limi tanasi.
//
// ⚠️  SHABLON SERVERDA (`/receipt/settings`), PRINTER QURILMADA (`<PrinterSetup/>`). Eski
//     `receipt.printer` kompaniya sozlamasi bu ekranda YO'Q: bitta kompyuter tanlagan printer
//     nomi hamma filial va kassaga tarqalardi.
// ⚠️  MEROS: filial → kompaniya → standart. Filial doirasida qatorda YO'Q maydon kompaniyadan
//     olinadi; «Standartga qaytarish» maydonga `null` yuboradi (qatordan o'chiradi). Bo'sh matn ham
//     `null` — ya'ni meros (server bir qatorli maydonlarda shunday qiladi, izchil bo'lsin).
// ⚠️  AVTO-SAQLASH boshqa Sozlamalar bo'limlari kabi: matn — maydondan chiqqanda, tugma/tanlov —
//     darhol. So'rovlar KETMA-KET (navbat): tez bosilgan ikki almashtirgich javobi teskari tartibda
//     kelib, yangi qiymatni eski bilan bosib ketmasin. Xatoda optimistik qiymat bekor qilinib,
//     server holati qayta o'qiladi (SB-020 naqshi).
// ⚠️  OLDINDAN KO'RISH — sof kutubxona (`@/receipt`) bilan, saqlanmagan qoralama qo'llangan holda;
//     iframe `sandbox=""` (skript ham, tashqi so'rov ham yo'q) — HTML'ning o'zida ham CSP bor.
// ⚠️  SINOV CHOP ETISH hech narsa yozmaydi (`printTestReceipt` — faqat GET, jurnalsiz).
import { useEffect, useId, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { get, post, put } from "@/lib/api";
import { inputStyle } from "@/components/ui";
import { Segmented } from "@/components/lotui";
import { PrinterSetup } from "@/components/PrinterSetup";
import { useT } from "@/lib/i18n";
import { printTestReceipt, type PrintResult } from "@/lib/printing";
import { hasElectronPrint, readPrinterConfig } from "@/lib/printerConfig";
import { useLang, LANGS } from "@/store/lang";
import { useAuth } from "@/store/auth";
import {
  BUILTIN_TEMPLATE, code128Modules, docHeightMm, labelsFor, layoutReceipt, normalizeTemplate, renderHtml,
  sampleReceipt, type LogoVariant, type PaperWidth, type ReceiptDTO, type ReceiptTemplate, type SampleKind,
} from "@/receipt";

export type SaveState = "saving" | "saved" | "failed";
/**
 * `printTestReceipt` ning 2-argumenti: doira (kompaniya/filial) + `dto` — ko'rinishdagi AYNAN o'sha namuna
 * (qog'oz = ko'rinish; printing.ts uni o'zgartirmasdan chop etadi).
 */
type TestPrintOpts = NonNullable<Parameters<typeof printTestReceipt>[1]> & { scope?: "company"; dto?: ReceiptDTO };

type Row = Record<string, unknown>;
type TextField = "header" | "footer" | "store_display_name" | "address" | "phone" | "qr_url";
type BoolField =
  | "show_logo" | "show_branch" | "show_stir" | "show_cashier" | "show_till" | "show_payment_breakdown"
  | "show_discount" | "show_customer" | "show_barcode" | "auto_cut" | "auto_print";

interface BranchRef { id: string; name: string }
interface LogoOut { id: string; sha256: string; branch_id: string | null; variants: Partial<Record<"58" | "80", LogoVariant>> }
interface View {
  scope: { branch_id: string | null; company_editable: boolean; branch_editable: boolean };
  branches: BranchRef[];
  company: Row;
  branch: Row | null;
  effective: Row;
  store: ReceiptDTO["store"];
  logo: LogoOut | null;
}

// Server `BUILTIN` (§1) — shablon maydonlari + DTO'ga kirmaydiganlari.
const BUILTIN_ALL: Row = { ...BUILTIN_TEMPLATE, printer: null, logo_id: null, qr_url: null };
const TEXT_MAX: Record<TextField, number> = {
  header: 2000, footer: 2000, store_display_name: 120, address: 300, phone: 40, qr_url: 300,
};
const MULTILINE = new Set<TextField>(["header", "footer"]);
// `ega`/`administrator` — server `require()` ularni ruxsat ro'yxatisiz o'tkazadi; UI ham shunday
// hisoblasin (aks holda override bilan ruxsati olingan admin tahrirlay olsa-da, UI yopib qo'yardi).
const FULL_ACCESS_ROLES = ["ega", "administrator"];

const LOGO_MAX_BYTES = 2 * 1024 * 1024;
const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp"];
const PNG_URI_RE = /^data:image\/png;base64,[A-Za-z0-9+/=]+$/;
// Server bilan AYNI qoida (settings.py `_URL_RE`): sxema http(s), bo'shliq/qo'shtirnoq/burchak yo'q.
const URL_RE = /^https?:\/\/[^\s<>"']+$/;
// Boshqaruv (Cc) VA format (Cf: ZWSP, soft hyphen, bidi...) belgilari: layout bunday QR payload'ini rad
// etadi (`qr_invalid`) — havola saqlanib, QR esa jimgina chiqmay qolmasin: maydonning o'zida xato.
const CONTROL_RE = /[\p{Cc}\p{Cf}]/u;
const MM_PX = 96 / 25.4;
const SAMPLE_KINDS: SampleKind[] = ["sale", "mixed", "return", "long"];
const TOGGLES_FIELDS: BoolField[] = [
  "show_branch", "show_stir", "show_cashier", "show_till", "show_payment_breakdown", "show_discount",
  "show_customer", "show_barcode",
];

const labelStyle: CSSProperties = { fontSize: 12.5, color: "var(--text3)", fontWeight: 600 };
const noteStyle: CSSProperties = { fontSize: 12, color: "var(--muted)", marginTop: 6, lineHeight: 1.45 };
const errStyle: CSSProperties = { fontSize: 12, color: "var(--red)", marginTop: 6 };

// ── yordamchilar ────────────────────────────────────────────────────────────
const present = (row: Row | null | undefined, f: string) => !!row && row[f] !== null && row[f] !== undefined;

/** Qatlamlash: `null`/`undefined` — meros (yuqori qatlam qoladi). */
function layer(base: Row, row: Row | null | undefined): Row {
  const out = { ...base };
  if (row) for (const [k, v] of Object.entries(row)) if (v !== null && v !== undefined && k in BUILTIN_ALL) out[k] = v;
  return out;
}

const asRow = (v: unknown): Row => (v && typeof v === "object" && !Array.isArray(v) ? (v as Row) : {});
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);

/** Server javobi ISHONCHSIZ: shakli buzuq bo'lsa null (ekran «yuklanmadi» deydi, yiqilmaydi). */
function asView(v: unknown): View | null {
  const o = asRow(v);
  const sc = asRow(o.scope);
  if (!o.effective || typeof o.effective !== "object" || !o.scope) return null;
  const st = asRow(o.store);
  const lg = asRow(o.logo);
  return {
    scope: {
      branch_id: str(sc.branch_id),
      company_editable: sc.company_editable === true,
      branch_editable: sc.branch_editable === true,
    },
    branches: Array.isArray(o.branches)
      ? (o.branches as unknown[]).map(asRow).filter((b) => typeof b.id === "string")
        .map((b) => ({ id: b.id as string, name: str(b.name) ?? "" }))
      : [],
    company: asRow(o.company),
    branch: o.branch && typeof o.branch === "object" ? asRow(o.branch) : null,
    effective: asRow(o.effective),
    store: {
      name: str(st.name) ?? "", branch_name: str(st.branch_name), address: str(st.address),
      phone: str(st.phone), stir: str(st.stir),
    },
    logo: typeof lg.id === "string"
      ? { id: lg.id, sha256: str(lg.sha256) ?? "", branch_id: str(lg.branch_id), variants: asRow(lg.variants) as LogoOut["variants"] }
      : null,
  };
}

function isDto(v: unknown): v is ReceiptDTO {
  const d = v as ReceiptDTO;
  return !!d && typeof d === "object" && d.schema === "binos.receipt.v1" && Array.isArray(d.lines) &&
    !!d.doc && !!d.store && !!d.totals;
}

/** Saqlanadigan qiymat: bo'sh matn — `null` (meros). */
function toSaved(f: TextField, raw: string): string | null {
  if (MULTILINE.has(f)) {
    const v = raw.replace(/\r\n?/g, "\n");
    return v.trim() === "" ? null : v;
  }
  return raw.trim() || null;
}

function validUrl(v: unknown): v is string {
  return typeof v === "string" && v.length <= TEXT_MAX.qr_url && !CONTROL_RE.test(v) && URL_RE.test(v);
}

function errMsg(e: unknown): string {
  const m = (e as Error)?.message;
  return typeof m === "string" && m ? m : String(e ?? "");
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onerror = () => reject(r.error ?? new Error("read"));
    r.onload = () => {
      const s = typeof r.result === "string" ? r.result : "";
      const i = s.indexOf(",");
      if (i < 0) reject(new Error("read"));
      else resolve(s.slice(i + 1));
    };
    r.readAsDataURL(file);
  });
}

/**
 * Sehrli baytlar — server bilan AYNI tekshiruv (fayl nomi/MIME e'tiborsiz). Serverda baribir
 * qayta tekshiriladi; bu yerda — 2 MB ni behuda yuklamaslik va aniq xabar uchun.
 */
function sniffImage(b64: string): boolean {
  let head = "";
  try { head = atob(b64.slice(0, 16)); } catch { return false; }
  const b = (i: number) => head.charCodeAt(i);
  const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a].every((x, i) => b(i) === x);
  const jpeg = b(0) === 0xff && b(1) === 0xd8 && b(2) === 0xff;
  const webp = head.slice(0, 4) === "RIFF" && head.slice(8, 12) === "WEBP";
  return png || jpeg || webp;
}

/** Element kengligi (px) — ResizeObserver bo'lmasa oyna o'lchami o'zgarganda. */
function useWidth(el: HTMLElement | null): number {
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!el) return;
    const measure = () => setW(el.clientWidth);
    measure();
    if (typeof ResizeObserver === "function") {
      const ro = new ResizeObserver(measure);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [el]);
  return w;
}

// ── kichik UI bloklari (Sozlamalar sahifasining ko'rinishi bilan bir xil) ──────
function Section({ id, title, desc, children, testid }: {
  id: string; title: string; desc?: string; children: ReactNode; testid?: string;
}) {
  return (
    <section className="card" aria-labelledby={id} data-testid={testid} style={{ marginBottom: 18, maxWidth: 620, minWidth: 0 }}>
      <h2 id={id} style={{ fontSize: 17, fontWeight: 700, margin: 0 }}>{title}</h2>
      {desc ? <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 3, marginBottom: 14 }}>{desc}</div>
        : <div style={{ height: 14 }} />}
      {children}
    </section>
  );
}

function SwitchRow({ id, label, note, on, disabled, onChange, tag }: {
  id: string; label: string; note?: string; on: boolean; disabled: boolean; onChange: (v: boolean) => void; tag?: ReactNode;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "12px 0", borderTop: "1px solid var(--border-soft)" }}>
      <div style={{ minWidth: 0 }}>
        <label id={`${id}-label`} htmlFor={id} style={{ fontSize: 14, fontWeight: 500, color: disabled ? "var(--muted)" : "var(--text)", cursor: disabled ? "default" : "pointer" }}>
          {label}
        </label>
        {note ? <div id={`${id}-note`} style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{note}</div> : null}
        {tag ? <div style={{ marginTop: 4 }}>{tag}</div> : null}
      </div>
      <button type="button" id={id} role="switch" aria-checked={on} aria-labelledby={`${id}-label`}
        aria-describedby={note ? `${id}-note` : undefined} disabled={disabled} onClick={() => onChange(!on)}
        style={{ width: 46, height: 26, flex: "none", borderRadius: 13, border: "none", padding: 0, background: on ? "var(--accent)" : "var(--border-input)", position: "relative", cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.6 : 1 }}>
        <span aria-hidden="true" style={{ position: "absolute", top: 3, left: on ? 23 : 3, width: 20, height: 20, borderRadius: "50%", background: "#fff", transition: "left .15s", boxShadow: "0 1px 3px rgba(0,0,0,0.25)" }} />
      </button>
    </div>
  );
}

function LabelRow({ htmlFor, label, tag }: { htmlFor: string; label: string; tag?: ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap", minHeight: 20 }}>
      <label htmlFor={htmlFor} style={labelStyle}>{label}</label>
      {tag}
    </div>
  );
}

// ── ekran ───────────────────────────────────────────────────────────────────
export function ReceiptSettings({ onSaveState }: { onSaveState?: (s: SaveState) => void }): JSX.Element {
  const t = useT();
  const uiLang = useLang((s) => s.lang);
  const employee = useAuth((s) => s.employee);
  const permEdit = !!employee && (
    (employee.permissions ?? []).includes("sozlamalar.edit") || FULL_ACCESS_ROLES.includes(employee.role_code));

  const uid = useId().replace(/:/g, "");
  const id = (k: string) => `rs-${uid}-${k}`;

  const [bid, setBid] = useState<string | null>(null);
  const bidRef = useRef<string | null>(null);
  const [branches, setBranches] = useState<BranchRef[]>([]);
  const [view, setView] = useState<View | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [local, setLocal] = useState<Row>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [qrErr, setQrErr] = useState<"required" | "invalid" | null>(null);
  const [logoMsg, setLogoMsg] = useState<{ ok: boolean | null; text: string } | null>(null);
  const [logoBusy, setLogoBusy] = useState(false);
  const [kind, setKind] = useState<SampleKind>("sale");
  const [previewW, setPreviewW] = useState<PaperWidth | null>(null); // null — shablon kengligi
  // `silent` — server namunasi ATAYIN so'ralmagan (kompaniya doirasini o'zgartira olmaydigan xodim): izoh yo'q.
  const [sample, setSample] = useState<{ key: string; dto: ReceiptDTO; local: boolean; silent?: boolean } | null>(null);
  const [tp, setTp] = useState<{ busy: boolean; ok?: boolean; text?: string; detail?: string }>({ busy: false });
  const [rootEl, setRootEl] = useState<HTMLElement | null>(null);
  const [frameBoxEl, setFrameBoxEl] = useState<HTMLElement | null>(null);
  const rootW = useWidth(rootEl);
  const frameBoxW = useWidth(frameBoxEl);
  const fileRef = useRef<HTMLInputElement>(null);
  const qrUrlRef = useRef<HTMLInputElement>(null);

  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const onSaveRef = useRef(onSaveState);
  onSaveRef.current = onSaveState;

  // ── yuklash ──────────────────────────────────────────────────────────────
  const loadSeq = useRef(0);
  async function load(scope: string | null, first = false) {
    const my = ++loadSeq.current;
    setLoadErr(null);
    try {
      const q = scope ? `?branch_id=${encodeURIComponent(scope)}` : "";
      const v = asView(await get<unknown>(`/receipt/settings${q}`));
      if (!alive.current || my !== loadSeq.current) return;
      if (!v) throw new Error(t("common.error"));
      setBranches(v.branches);
      // Filialga biriktirilgan admin kompaniya shablonini o'zgartira olmaydi — darhol O'Z filialini
      // ochamiz (aks holda birinchi ko'rgani hamma maydoni yopiq sahifa bo'lardi).
      if (first && scope === null && permEdit && !v.scope.company_editable && v.branches.length > 0) {
        switchScope(v.branches[0].id);
        return;
      }
      setView(v);
      setLocal({});
    } catch (e) {
      if (alive.current && my === loadSeq.current) setLoadErr(errMsg(e));
    }
  }

  /** Xatodan keyin: server holatini qayta o'qish — qoralamaning BOSHQA maydonlariga tegmaydi. */
  async function refresh(scope: string | null) {
    try {
      const q = scope ? `?branch_id=${encodeURIComponent(scope)}` : "";
      const v = asView(await get<unknown>(`/receipt/settings${q}`));
      if (v && alive.current && scope === bidRef.current) { setView(v); setBranches(v.branches); }
    } catch { /* keyingi harakatda yana urinib ko'riladi */ }
  }

  useEffect(() => { load(null, true); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function switchScope(next: string | null) {
    if (next === bidRef.current && view) return;
    bidRef.current = next;
    setBid(next);
    setView(null);
    setLocal({});
    setMsg(null);
    setQrErr(null);
    setLogoMsg(null);
    setPreviewW(null);
    load(next);
  }

  // ── doira va qoralama ───────────────────────────────────────────────────
  const isBranch = !!view && view.scope.branch_id !== null;
  const editable = !!view && permEdit && (isBranch ? view.scope.branch_editable : view.scope.company_editable);
  const ro = !editable;
  const scopeRow: Row = (view ? (isBranch ? view.branch : view.company) : null) ?? {};
  const base: Row = view && isBranch ? layer(BUILTIN_ALL, view.company) : { ...BUILTIN_ALL };
  // Matn maydonidagi bo'sh qiymat — meros (saqlanganda ham shunday bo'ladi).
  const localRow: Row = {};
  for (const [k, v] of Object.entries(local)) {
    localRow[k] = typeof v === "string" && k in TEXT_MAX ? toSaved(k as TextField, v) : v;
  }
  const draftRow: Row = { ...scopeRow, ...localRow };
  const draft = layer(base, draftRow);
  const T: ReceiptTemplate = normalizeTemplate(draft as Partial<ReceiptTemplate>);

  // ── saqlash navbati ─────────────────────────────────────────────────────
  const chain = useRef<Promise<void>>(Promise.resolve());
  const inflight = useRef(0);
  const batchFailed = useRef(false);

  function enqueue(work: () => Promise<boolean>): Promise<void> {
    if (inflight.current === 0) batchFailed.current = false;
    inflight.current += 1;
    onSaveRef.current?.("saving");
    const run = chain.current.then(work).catch(() => false).then((ok) => {
      if (!ok) batchFailed.current = true;
      inflight.current -= 1;
      // `alive` tekshirilMAYDI: matn maydonidan boshqa bo'limga o'tilganda (blur → saqlash → bu ekran
      // yopiladi) Sozlamalar Topbar'i «saqlanmoqda» holatida qotib qolmasin — natija baribir aytiladi.
      if (inflight.current === 0) onSaveRef.current?.(batchFailed.current ? "failed" : "saved");
    });
    chain.current = run;
    return run;
  }

  /** Mahalliy (optimistik) qiymatni tozalash — faqat u hali AYNAN yuborilgan qiymat bo'lsa. */
  function settle(snap: Row) {
    setLocal((prev) => {
      let changed = false;
      const n = { ...prev };
      for (const [k, v] of Object.entries(snap)) {
        if (k in n && Object.is(n[k], v)) { delete n[k]; changed = true; }
      }
      return changed ? n : prev;
    });
  }

  function save(patch: Row, snap: Row = patch): Promise<void> {
    if (ro) return Promise.resolve();
    const scope = bidRef.current;
    return enqueue(async () => {
      try {
        const v = asView(await put<unknown>("/receipt/settings", { branch_id: scope, value: patch }));
        if (!alive.current || scope !== bidRef.current) return true;
        if (v) { setView(v); setBranches(v.branches); }
        settle(snap);
        setMsg(null);
        return true;
      } catch (e) {
        if (!alive.current || scope !== bidRef.current) return false;
        setMsg(t("rs.saveFailed", { reason: errMsg(e) }));
        settle(snap);
        void refresh(scope);
        return false;
      }
    });
  }

  // ── maydon amallari ─────────────────────────────────────────────────────
  function setField(f: string, v: unknown) {
    setLocal((l) => ({ ...l, [f]: v }));
  }

  function setBool(f: BoolField, v: boolean) {
    setField(f, v);
    void save({ [f]: v });
  }

  function reset(f: string) {
    setField(f, null);
    if (f === "qr_mode" || f === "qr_url") setQrErr(null);
    void save({ [f]: null });
  }

  const textOf = (f: TextField): string => {
    if (f in local) return typeof local[f] === "string" ? (local[f] as string) : "";
    return typeof scopeRow[f] === "string" ? (scopeRow[f] as string) : "";
  };

  function commitText(f: TextField) {
    if (!(f in local) || ro) return;
    const raw = local[f];
    const next = typeof raw === "string" ? toSaved(f, raw) : null;
    const saved = typeof scopeRow[f] === "string" ? scopeRow[f] : null;
    if (f === "qr_url") {
      // Bo'sh — meros: filialda kompaniya havolasi bo'lsa `null` saqlanadi (o'shani oladi); havola hech
      // qaysi qatlamda qolmasagina «kiriting». `draft` null'ni o'tkazib yuboradi — draft.qr_url = meros qiymat.
      if (next === null && T.qr_mode === "store_url" && !validUrl(draft.qr_url)) { setQrErr("required"); return; }
      if (next !== null && !validUrl(next)) { setQrErr("invalid"); return; }
      setQrErr(null);
      const patch: Row = { qr_url: next };
      const snap: Row = { qr_url: raw };
      // Rejim havolani kutib turgan bo'lsa — birga saqlanadi (server havolasiz store_url'ni rad etadi).
      if (next !== null && T.qr_mode === "store_url" && view?.effective.qr_mode !== "store_url") {
        patch.qr_mode = "store_url";
        snap.qr_mode = local.qr_mode;
      }
      if (next === saved && !("qr_mode" in patch)) { settle(snap); return; }
      void save(patch, snap);
      return;
    }
    if (next === saved) { settle({ [f]: raw }); return; }
    void save({ [f]: next }, { [f]: raw });
  }

  function setQrMode(mode: string) {
    setField("qr_mode", mode);
    if (mode !== "store_url") {
      setQrErr(null);
      void save({ qr_mode: mode });
      return;
    }
    // Havola hali yozilayotgan bo'lsa — o'sha; aks holda saqlangan samarali havola.
    const pending = typeof local.qr_url === "string" ? toSaved("qr_url", local.qr_url as string) : undefined;
    // Tozalangan havola (null) — meros: filialda kompaniya havolasi amal qiladi.
    const url = pending !== undefined ? (pending ?? base.qr_url) : view?.effective.qr_url;
    if (!validUrl(url)) {
      setQrErr(pending ? "invalid" : "required");
      setTimeout(() => qrUrlRef.current?.focus(), 0);
      return;
    }
    setQrErr(null);
    const patch: Row = { qr_mode: mode };
    const snap: Row = { qr_mode: mode };
    if (pending !== undefined) { patch.qr_url = pending; snap.qr_url = local.qr_url; }
    void save(patch, snap);
  }

  function setWidth(w: PaperWidth) {
    setField("width_mm", w);
    setPreviewW(null); // oldindan ko'rish yangi shablon kengligiga ergashadi
    void save({ width_mm: w });
  }

  // ── logo ────────────────────────────────────────────────────────────────
  async function onLogoFile(e: React.ChangeEvent<HTMLInputElement>) {
    const input = e.currentTarget;
    const file = input.files && input.files[0];
    input.value = ""; // o'sha faylni qayta tanlash ham `change` bersin
    if (!file || ro) return;
    // Mijoz tekshiruvi — server baribir qayta tekshiradi (sehrli baytlar, o'lcham, Pillow).
    if (file.type && !LOGO_TYPES.includes(file.type)) { setLogoMsg({ ok: false, text: t("rs.logoErrType") }); return; }
    if (file.size > LOGO_MAX_BYTES) { setLogoMsg({ ok: false, text: t("rs.logoErrSize") }); return; }
    let b64: string;
    try { b64 = await readBase64(file); } catch { setLogoMsg({ ok: false, text: t("rs.logoErrRead") }); return; }
    if (!sniffImage(b64)) { setLogoMsg({ ok: false, text: t("rs.logoErrType") }); return; }
    const scope = bidRef.current;
    setLogoBusy(true);
    setLogoMsg({ ok: null, text: t("rs.logoUploading") });
    await enqueue(async () => {
      try {
        const out = await post<{ id?: unknown }>("/receipt/logos", { branch_id: scope, data_b64: b64 });
        if (!out || typeof out.id !== "string") throw new Error(t("common.error"));
        const v = asView(await put<unknown>("/receipt/settings", { branch_id: scope, value: { logo_id: out.id } }));
        if (alive.current && scope === bidRef.current) {
          if (v) { setView(v); setBranches(v.branches); }
          setLogoMsg({ ok: true, text: t("rs.logoDone") });
        }
        return true;
      } catch (err) {
        if (alive.current && scope === bidRef.current) setLogoMsg({ ok: false, text: t("rs.logoFail", { reason: errMsg(err) }) });
        return false;
      } finally {
        if (alive.current) setLogoBusy(false);
      }
    });
  }

  function removeLogo() {
    setLogoMsg(null);
    void save({ logo_id: null }, {});
  }

  // ── oldindan ko'rish: namuna DTO (filial × tur × saqlangan QR — bir marta) ──
  const savedQr = view ? `${String(view.effective.qr_mode ?? "")}|${String(view.effective.qr_url ?? "")}` : "";
  const sampleKey = view ? `${view.scope.branch_id ?? ""}|${kind}|${savedQr}` : "";
  const samples = useRef(new Map<string, { dto: ReceiptDTO; local: boolean }>());
  const viewRef = useRef(view);
  viewRef.current = view;
  useEffect(() => {
    const v = viewRef.current;
    if (!sampleKey || !v) return;
    const hit = samples.current.get(sampleKey);
    if (hit) { setSample({ key: sampleKey, ...hit }); return; }
    let live = true;
    const q = new URLSearchParams({ kind });
    // Kompaniya doirasi — kompaniya standartining o'zi (xodim filiali ustamasi, QR havolasi, logosi EMAS).
    if (v.scope.branch_id) q.set("branch_id", v.scope.branch_id);
    else q.set("scope", "company");
    // Server yo'q/ruxsat yo'q — mahalliy namuna (qoralama baribir ustiga qo'llanadi).
    const fallback = () => ({ dto: sampleReceipt(kind, v.store, normalizeTemplate(v.effective as Partial<ReceiptTemplate>)), local: true });
    // Kompaniya standartini o'zgartira olmaydigan xodim (filialga cheklangan yoki faqat ko'rish): server
    // scope=company'ni unga 403 bilan rad etadi — so'ramaymiz, mahalliy namuna JIMGINA (bu nosozlik emas).
    if (!v.scope.branch_id && !v.scope.company_editable) {
      setSample({ key: sampleKey, ...fallback(), silent: true });
      return;
    }
    get<unknown>(`/receipt/sample?${q.toString()}`)
      .then((r) => {
        if (!live) return;
        const entry = isDto(r) ? { dto: r, local: false } : fallback();
        if (!entry.local) samples.current.set(sampleKey, entry);
        setSample({ key: sampleKey, ...entry });
      })
      .catch(() => { if (live) setSample({ key: sampleKey, ...fallback() }); });
    return () => { live = false; };
  }, [sampleKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const width: PaperWidth = previewW ?? T.width_mm;
  const preview = useMemo(() => {
    if (!sample || !view) return null;
    const b = sample.dto;
    const docUid = b.doc?.uid ?? null;
    // Shtrix-kod qoralamada yoqilgan, server namunasi esa saqlangan (o'chiq) holatdan — mahalliy CODE128.
    const modules = T.show_barcode && docUid ? (b.barcode?.modules ?? code128Modules(docUid)) : null;
    const dto: ReceiptDTO = {
      ...b,
      test: true,
      store: { ...b.store, ...view.store, branch_name: view.store.branch_name ?? b.store?.branch_name ?? null },
      customer: T.show_customer ? (b.customer ?? { name: "TEST" }) : null,
      barcode: modules && docUid ? { format: "CODE128", payload: b.barcode?.payload ?? docUid, modules } : null,
      template: T,
    };
    const logo = T.show_logo && view.logo ? view.logo.variants[String(width) as "58" | "80"] ?? null : null;
    try {
      const doc = layoutReceipt(dto, { width_mm: width, lang: T.lang ?? uiLang, template: T, logo, copy: null });
      return {
        html: renderHtml(doc, { title: t("rs.previewFrame", { w: width }) }),
        heightMm: docHeightMm(doc),
        // Sinov chop etish AYNAN shu DTO'ni oladi (qog'oz = ko'rinish): ko'rinishdagi logo havolasi va
        // ko'rinish kengligi bilan (printing.ts kenglikni shablondan oladi).
        printDto: {
          ...dto,
          logo: T.show_logo && view.logo ? { id: view.logo.id, sha256: view.logo.sha256 } : null,
          template: { ...T, width_mm: width },
        } as ReceiptDTO,
        // Jim mahalliy namunada QR matritsasi yo'q — "saqlangandan keyin ko'rinadi" deyish noto'g'ri bo'lardi.
        qrMissing: !sample.silent && T.qr_mode !== "none" && (!b.qr || b.qr.kind !== T.qr_mode) &&
          (T.qr_mode === "store_url" || !!docUid),
        // Layout QR'ni rad etgan (`qr_invalid`: masalan havolada ko'rinmas belgi) — alohida izoh: saqlash
        // ham yordam bermaydi, jimgina QR'siz chek bo'lmasin.
        qrInvalid: doc.warnings.includes("qr_invalid"),
      };
    } catch {
      return null;
    }
    // `t` har renderda yangi funksiya — bog'liqlik emas (til `uiLang` orqali kiradi); 120 qatorli
    // namuna har bosishda qayta chizilmasin.
  }, [sample, view, JSON.stringify(T), width, uiLang]); // eslint-disable-line react-hooks/exhaustive-deps

  async function testPrint() {
    setTp({ busy: true });
    let r: PrintResult;
    // Kompaniya doirasida namuna kompaniya standartidan (`scope: "company"` — ko'rinish bilan bir xil),
    // xodim filiali ustamasidan emas; filial doirasida — o'sha filial. Ko'rinish tayyor bo'lsa — AYNAN
    // o'sha DTO (server namunasi yoki mahalliy, qoralama shabloni qo'llangan): qog'oz = ko'rinish.
    const opts: TestPrintOpts = bidRef.current ? { branch_id: bidRef.current } : { scope: "company" };
    if (preview?.printDto) opts.dto = preview.printDto;
    try {
      r = await printTestReceipt(kind, opts);
    } catch (e) {
      r = { ok: false, code: "FAILED", error: errMsg(e) };
    }
    if (!alive.current) return;
    if (r.ok) {
      // Brauzer oynasi natijani aytmaydi — «yuborildi» (PrinterSetup bilan bir xil qoida).
      const unconfirmed = !window.__BINOS_VIRTUAL_PRINTER__ && (!hasElectronPrint() || readPrinterConfig().transport === "browser");
      setTp({ busy: false, ok: true, text: t(unconfirmed ? "rs.testSent" : "rs.testOk") });
    } else {
      setTp({ busy: false, ok: false, text: t("rs.testFail", { reason: t(`ps.err.${r.code ?? "FAILED"}`) }), detail: r.error });
    }
  }

  // ── chizish ─────────────────────────────────────────────────────────────
  const twoCol = rootW >= 900; // keng ekranda ko'rinish o'ngda yopishqoq (tahrir paytida doim ko'rinsin)

  const tagFor = (f: string, fieldLabel: string): ReactNode => {
    if (!isBranch) return null;
    if (present(draftRow, f)) {
      return (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--accent-strong)" }}>{t("rs.overridden")}</span>
          {!ro && (
            <button type="button" onClick={() => reset(f)} aria-label={t("rs.resetAria", { field: fieldLabel })}
              data-testid={`rs-reset-${f}`}
              style={{ border: "none", background: "none", padding: 0, font: "inherit", fontSize: 12, fontWeight: 600, color: "var(--accent)", cursor: "pointer", textDecoration: "underline" }}>
              {t("rs.reset")}
            </button>
          )}
        </span>
      );
    }
    return (
      <span data-testid={`rs-inherited-${f}`} style={{ fontSize: 11.5, fontWeight: 600, color: "var(--muted)", background: "var(--surface)", padding: "2px 8px", borderRadius: 7 }}>
        {t("rs.inherited")}
      </span>
    );
  };

  /** Meros qiymat (placeholder): SAQLANGAN qatorda maydon yo'q bo'lsa `store` aynan shuni ko'rsatadi. */
  function inherited(f: TextField): string {
    if (!view) return "";
    if (isBranch && present(view.company, f)) return String(view.company[f]);
    const rowHas = present(scopeRow, f);
    switch (f) {
      case "store_display_name": return rowHas ? "" : view.store.name;
      case "address": return rowHas ? "" : view.store.address ?? "";
      case "phone": return rowHas ? "" : view.store.phone ?? "";
      case "footer": return labelsFor(T.lang ?? uiLang).footerDefault;
      case "header": return t("rs.headerExample");
      case "qr_url": return "https://";
    }
  }

  const textField = (f: TextField, label: string, opts: { hint?: string; error?: string | null; inputRef?: React.Ref<HTMLInputElement> } = {}) => {
    const fid = id(f);
    const describedBy = [opts.error ? `${fid}-err` : "", opts.hint ? `${fid}-hint` : ""].filter(Boolean).join(" ") || undefined;
    const common = {
      id: fid,
      value: textOf(f),
      placeholder: inherited(f),
      disabled: ro,
      maxLength: TEXT_MAX[f],
      "aria-invalid": opts.error ? true : undefined,
      "aria-describedby": describedBy,
      "data-testid": `rs-${f}`,
      onBlur: () => commitText(f),
    };
    return (
      <div style={{ flex: "1 1 220px", minWidth: 0, marginBottom: 12 }}>
        <LabelRow htmlFor={fid} label={label} tag={tagFor(f, label)} />
        {MULTILINE.has(f) ? (
          <textarea {...common} rows={3} onChange={(e) => setField(f, e.target.value)}
            style={{ ...inputStyle, height: "auto", minHeight: 76, padding: "10px 14px", marginTop: 6, resize: "vertical", lineHeight: 1.45 }} />
        ) : (
          <input {...common} ref={opts.inputRef} type={f === "qr_url" ? "url" : "text"} autoComplete="off"
            spellCheck={f === "qr_url" ? false : undefined}
            onChange={(e) => { setField(f, e.target.value); if (f === "qr_url") setQrErr(null); }}
            style={{ ...inputStyle, marginTop: 6 }} />
        )}
        {opts.error ? <div id={`${fid}-err`} role="alert" style={errStyle}>{opts.error}</div> : null}
        {opts.hint ? <div id={`${fid}-hint`} style={noteStyle}>{opts.hint}</div> : null}
      </div>
    );
  };

  const toggle = (f: BoolField, label: string, note?: string) => (
    <SwitchRow key={f} id={id(f)} label={label} note={note} on={T[f] === true} disabled={ro}
      onChange={(v) => setBool(f, v)} tag={tagFor(f, label)} />
  );

  const selectField = (f: "copies" | "lang" | "qr_mode", label: string, value: string, options: [string, string][], onChange: (v: string) => void) => (
    <div style={{ flex: "1 1 220px", minWidth: 0, marginBottom: 12 }}>
      <LabelRow htmlFor={id(f)} label={label} tag={tagFor(f, label)} />
      <select id={id(f)} value={value} disabled={ro} data-testid={`rs-${f}`} onChange={(e) => onChange(e.target.value)}
        style={{ ...inputStyle, marginTop: 6 }}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );

  const scopeCard = (
    <section className="card" data-testid="rs-scope-card" style={{ marginBottom: 18, maxWidth: 620, minWidth: 0 }}>
      <label htmlFor={id("scope")} style={labelStyle}>{t("rs.scope")}</label>
      <select id={id("scope")} data-testid="rs-scope" value={bid ?? ""} onChange={(e) => switchScope(e.target.value || null)}
        style={{ ...inputStyle, marginTop: 6 }}>
        <option value="">{t("rs.scopeCompany")}</option>
        {branches.map((b) => <option key={b.id} value={b.id}>{t("rs.scopeBranch", { name: b.name })}</option>)}
      </select>
      <div style={noteStyle}>{bid ? t("rs.scopeBranchHint") : t("rs.scopeCompanyHint")}</div>
      {view && ro && (
        <div role="note" data-testid="rs-readonly"
          style={{ marginTop: 12, padding: "10px 13px", borderRadius: 11, fontSize: 12.5, lineHeight: 1.5, background: "var(--surface)", color: "var(--text2)" }}>
          {permEdit ? t("rs.readOnlyCompany") : t("rs.readOnly")}
        </div>
      )}
      <div role="status" aria-live="polite" data-testid="rs-status"
        style={{ fontSize: 12.5, color: "var(--red)", marginTop: msg ? 10 : 0, overflowWrap: "anywhere" }}>
        {msg ?? ""}
      </div>
    </section>
  );

  if (loadErr && !view) {
    return (
      <div ref={setRootEl} className="lot-screen" data-testid="receipt-settings">
        {scopeCard}
        <div className="card" role="alert" style={{ maxWidth: 460 }}>
          <div style={{ color: "var(--danger)", fontWeight: 600, marginBottom: 10 }}>{t("rs.loadErr")}</div>
          <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14, overflowWrap: "anywhere" }}>{loadErr}</div>
          <button type="button" className="btn btn-primary" onClick={() => load(bidRef.current)}>{t("common.retry")}</button>
        </div>
      </div>
    );
  }
  if (!view) {
    return (
      <div ref={setRootEl} className="lot-screen" data-testid="receipt-settings">
        {scopeCard}
        <div role="status" style={{ color: "var(--muted)" }}>{t("common.loading")}</div>
      </div>
    );
  }

  const logoVariants = view.logo?.variants ?? {};
  const logoOwnRow = present(scopeRow, "logo_id");
  const logoInherited = isBranch && !!view.logo && !present(view.branch, "logo_id");
  const stirMissing = !view.store.stir;

  const logoSection = (
    <Section id={id("h-logo")} title={t("rs.logoTitle")} desc={t("rs.logoDesc")} testid="rs-section-logo">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end" }} data-testid="rs-logo-previews">
        {view.logo ? (["58", "80"] as const).map((w) => {
          const v = logoVariants[w];
          if (!v || !PNG_URI_RE.test(v.png_data_uri) || !(v.width > 0) || !(v.height > 0)) return null;
          return (
            <figure key={w} style={{ margin: 0, minWidth: 0, maxWidth: "100%" }}>
              <div style={{ background: "#fff", border: "1px solid var(--border)", borderRadius: 10, padding: 8, maxWidth: "100%", overflow: "hidden" }}>
                <img src={v.png_data_uri} alt={t("rs.logoPreviewAlt", { w })} data-testid={`rs-logo-${w}`}
                  style={{ display: "block", width: `${v.width / 8}mm`, maxWidth: "100%", height: "auto", imageRendering: "pixelated" }} />
              </div>
              <figcaption style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 4 }}>{w} mm</figcaption>
            </figure>
          );
        }) : <div style={{ fontSize: 13, color: "var(--muted)" }}>{t("rs.logoNone")}</div>}
      </div>
      {logoInherited && <div style={noteStyle}>{t("rs.logoInheritedNote")}</div>}
      <label htmlFor={id("logo-file")} className="sr-only">{t("rs.logoFile")}</label>
      <input ref={fileRef} id={id("logo-file")} type="file" accept={LOGO_TYPES.join(",")} hidden disabled={ro || logoBusy}
        data-testid="rs-logo-file" onChange={onLogoFile} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 12, marginBottom: 6 }}>
        <button type="button" className="btn btn-ghost" disabled={ro || logoBusy} aria-busy={logoBusy || undefined}
          onClick={() => fileRef.current?.click()} style={{ fontSize: 13, padding: "8px 14px", opacity: ro ? 0.6 : 1 }}>
          {logoBusy ? t("rs.logoUploading") : view.logo ? t("rs.logoReplace") : t("rs.logoUpload")}
        </button>
        {logoOwnRow && !ro && (
          <button type="button" className="btn btn-ghost" disabled={logoBusy} onClick={removeLogo}
            aria-label={isBranch ? t("rs.resetAria", { field: t("rs.logoTitle") }) : undefined}
            style={{ fontSize: 13, padding: "8px 14px" }}>
            {isBranch ? t("rs.reset") : t("rs.logoRemove")}
          </button>
        )}
      </div>
      <div role="status" aria-live="polite" data-testid="rs-logo-status"
        style={{ fontSize: 12.5, minHeight: 4, overflowWrap: "anywhere", color: logoMsg?.ok === false ? "var(--red)" : logoMsg?.ok ? "var(--green)" : "var(--muted)" }}>
        {logoMsg?.text ?? ""}
      </div>
      {toggle("show_logo", t("rs.show_logo"))}
    </Section>
  );

  const storeSection = (
    <Section id={id("h-store")} title={t("rs.storeTitle")} desc={t("rs.storeDesc")} testid="rs-section-store">
      <div style={{ display: "flex", flexWrap: "wrap", columnGap: 12 }}>
        {textField("store_display_name", t("rs.store_display_name"))}
        {textField("phone", t("rs.phone"))}
      </div>
      {textField("address", t("rs.address"))}
      {textField("header", t("rs.header"))}
    </Section>
  );

  const fieldsSection = (
    <Section id={id("h-fields")} title={t("rs.fieldsTitle")} desc={t("rs.fieldsDesc")} testid="rs-section-fields">
      {TOGGLES_FIELDS.map((f) => toggle(f, t(`rs.${f}`),
        f === "show_customer" ? t("rs.show_customerNote")
          : f === "show_discount" ? t("rs.show_discountNote") // chek (umumiy) chegirmasi doim chiqadi
            : f === "show_stir" && stirMissing ? t("rs.show_stirNote") : undefined))}
    </Section>
  );

  const widthSection = (
    <Section id={id("h-width")} title={t("rs.widthTitle")} desc={t("rs.widthDesc")} testid="rs-section-width">
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <fieldset disabled={ro} style={{ border: 0, padding: 0, margin: 0, minWidth: 0, opacity: ro ? 0.6 : 1 }}>
          <Segmented value={String(T.width_mm)} testid="rs-width" label={t("rs.widthTitle")}
            options={[["58", "58 mm"], ["80", "80 mm"]]} onChange={(v) => setWidth(v === "58" ? 58 : 80)} />
        </fieldset>
        {tagFor("width_mm", t("rs.widthTitle"))}
      </div>
    </Section>
  );

  const qrOpts: [string, string][] = [
    ["none", t("rs.qr.none")], ["receipt_id", t("rs.qr.receipt_id")], ["store_url", t("rs.qr.store_url")],
  ];
  // Filialda kompaniya tili aniq bo'lsa «kassa tili» ('' → null) tanlab bo'lmaydi: null filialda MEROS
  // (kompaniya tili) degani — variant bosilsa ham kompaniya tiliga qaytib qolardi. Meros — «Standartga qaytarish».
  const deviceLangOpt = !(isBranch && base.lang != null);
  const langOpts: [string, string][] = [
    ...(deviceLangOpt ? [["", t("rs.langDevice")] as [string, string]] : []),
    ...LANGS.map((l) => [l.code, l.native] as [string, string]),
  ];
  const footerSection = (
    <Section id={id("h-footer")} title={t("rs.footerTitle")} testid="rs-section-footer">
      {textField("footer", t("rs.footer"))}
      <div style={{ display: "flex", flexWrap: "wrap", columnGap: 12 }}>
        {selectField("qr_mode", t("rs.qrMode"), T.qr_mode, qrOpts, setQrMode)}
      </div>
      {T.qr_mode === "store_url" && textField("qr_url", t("rs.qrUrl"), {
        inputRef: qrUrlRef,
        error: qrErr === "invalid" ? t("rs.qrUrlInvalid") : qrErr === "required" ? t("rs.qrUrlRequired") : null,
      })}
      <div style={{ display: "flex", flexWrap: "wrap", columnGap: 12 }}>
        {selectField("copies", t("rs.copies"), String(T.copies), [["1", "1"], ["2", "2"], ["3", "3"]],
          (v) => { const n = Number(v); setField("copies", n); void save({ copies: n }); })}
        {selectField("lang", t("rs.lang"), T.lang ?? "", langOpts,
          (v) => { const l = v || null; setField("lang", l); void save({ lang: l }); })}
      </div>
      {toggle("auto_cut", t("rs.auto_cut"), t("rs.auto_cutNote"))}
      {toggle("auto_print", t("rs.auto_print"), t("rs.auto_printNote"))}
    </Section>
  );

  const printerSection = (
    <Section id={id("h-printer")} title={t("rs.printerTitle")} desc={t("rs.printerDesc")} testid="rs-section-printer">
      <PrinterSetup compact templateWidth={T.width_mm} />
    </Section>
  );

  const pxW = Math.ceil(width * MM_PX) + 2;
  const pxH = Math.ceil(((preview?.heightMm ?? 60) + 4) * MM_PX);
  const avail = frameBoxW > 0 ? frameBoxW - 24 : 0;
  const scale = avail > 0 ? Math.min(1, avail / pxW) : 1;
  const previewSection = (
    <Section id={id("h-preview")} title={t("rs.previewTitle")} desc={t("rs.previewDesc")} testid="rs-section-preview">
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 12 }}>
        <Segmented value={kind} testid="rs-sample" label={t("rs.sampleKind")}
          options={SAMPLE_KINDS.map((k) => [k, t(`rs.sample.${k}`)] as [string, string])}
          onChange={(v) => setKind(v as SampleKind)} />
        <Segmented value={String(width)} testid="rs-preview-width" label={t("rs.previewWidth")}
          options={[["58", "58 mm"], ["80", "80 mm"]]} onChange={(v) => setPreviewW(v === "58" ? 58 : 80)} />
      </div>
      {/* Uzun chek (120 qator) sahifani cho'zib yubormasin — ko'rinish o'z qutisida aylanadi. */}
      <div ref={setFrameBoxEl} data-testid="rs-preview-box"
        style={{ background: "var(--surface)", borderRadius: 12, padding: 12, overflowX: "hidden", overflowY: "auto", maxWidth: "100%",
          maxHeight: twoCol ? "calc(100vh - 300px)" : "70vh", minHeight: 120 }}>
        {preview ? (
          <div style={{ width: pxW * scale, height: pxH * scale, margin: "0 auto", overflow: "hidden" }}>
            <iframe title={t("rs.previewFrame", { w: width })} sandbox="" srcDoc={preview.html}
              data-testid="rs-preview-frame" data-width-mm={width}
              style={{ display: "block", width: pxW, height: pxH, border: 0, background: "#fff", borderRadius: 4,
                transform: scale < 1 ? `scale(${scale})` : undefined, transformOrigin: "top left" }} />
          </div>
        ) : (
          <div role="status" style={{ fontSize: 13, color: "var(--muted)" }}>{t("common.loading")}</div>
        )}
      </div>
      {preview?.qrInvalid ? (
        <div style={{ ...noteStyle, color: "var(--red)" }} data-testid="rs-preview-qr-note">{t("rs.previewQrInvalid")}</div>
      ) : preview?.qrMissing && <div style={noteStyle} data-testid="rs-preview-qr-note">{t("rs.previewQrNote")}</div>}
      {sample?.local && !sample.silent && <div style={noteStyle} data-testid="rs-preview-local">{t("rs.previewLocal")}</div>}
      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 12, marginTop: 14 }}>
        <button type="button" className="btn btn-ghost" onClick={testPrint} disabled={tp.busy} aria-busy={tp.busy || undefined}
          data-testid="rs-test-print" style={{ fontSize: 13, padding: "8px 14px" }}>
          {tp.busy ? t("rs.testPrinting") : t("rs.testPrint")}
        </button>
        <div role="status" aria-live="polite" data-testid="rs-test-result" title={tp.detail || undefined}
          style={{ fontSize: 13, minWidth: 0, overflowWrap: "anywhere", color: tp.ok === undefined ? "var(--muted)" : tp.ok ? "var(--green)" : "var(--red)" }}>
          {tp.text ?? ""}
        </div>
      </div>
      <div style={noteStyle}>{t("rs.testNote")}</div>
    </Section>
  );

  const form = (
    <>
      {logoSection}
      {storeSection}
      {fieldsSection}
      {widthSection}
      {footerSection}
    </>
  );

  return (
    <div ref={setRootEl} className="lot-screen" data-testid="receipt-settings" style={{ minWidth: 0 }}>
      {twoCol ? (
        // O'ng ustun 80 mm chekni 1:1 sig'diradi (302px + quti 24 + karta 40); forma qolganini oladi.
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 620px) minmax(368px, 1fr)", gap: 20, alignItems: "start" }}>
          <div style={{ minWidth: 0 }}>
            {scopeCard}
            {form}
            {printerSection}
          </div>
          <div style={{ position: "sticky", top: 0, minWidth: 0 }}>{previewSection}</div>
        </div>
      ) : (
        <>
          {scopeCard}
          {form}
          {printerSection}
          {previewSection}
        </>
      )}
    </div>
  );
}
