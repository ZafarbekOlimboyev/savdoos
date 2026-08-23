import { useMemo, useState } from "react";
import {
  ArrowDown,
  ClockClockwise,
  ClockCountdown,
  DotsThreeVertical,
  DownloadSimple,
  MagnifyingGlass,
  Package,
  PencilSimple,
  Plus,
  Prohibit,
  Warning,
  X,
} from "@phosphor-icons/react";
import { api, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Modal, inputStyle, td, th, useGet } from "@/components/ui";
import { daysLeft, statusOf as statusOfShared, type StatusKey } from "@/lib/status";
import { useT } from "@/lib/i18n";

// Birlik kodini (dona/kg/litr/upak) joriy tilga o'giradi; noma'lum kod bo'lsa o'zini qaytaradi.
function unitL(t: (k: string) => string, u?: string | null): string {
  if (!u) return "";
  const v = t("unit." + u);
  return v.startsWith("unit.") ? u : v;
}

interface Product {
  id: string; article_code: string; sku: string | null; name: string;
  category_id: string | null; base_buy_price: number; base_sell_price: number;
  stock: number; min_stock: number; unit_code: string | null; expiry_date: string | null;
  is_weighted?: boolean; plu_code?: string | null; scale_sync?: boolean;
}
interface Category { id: string; name: string }

const STATUS: Record<StatusKey, { labelKey: string; color: string; soft: string }> = {
  ok: { labelKey: "prod.st_ok", color: "var(--ok)", soft: "var(--ok-soft)" },
  mid: { labelKey: "prod.st_mid", color: "var(--text3)", soft: "var(--surface)" },
  low: { labelKey: "prod.st_low", color: "var(--warn)", soft: "var(--warn-soft)" },
  soon: { labelKey: "prod.st_soon", color: "var(--warn)", soft: "var(--warn-soft)" },
  expired: { labelKey: "prod.st_expired", color: "var(--danger)", soft: "var(--danger-soft)" },
  out: { labelKey: "prod.st_out", color: "var(--danger)", soft: "var(--danger-soft)" },
};

const statusOf = (p: Product): StatusKey => statusOfShared(p);
function fmtDate(d: string | null): string {
  if (!d) return "—";
  const dt = new Date(d + "T00:00:00");
  return `${String(dt.getDate()).padStart(2, "0")}.${String(dt.getMonth() + 1).padStart(2, "0")}.${dt.getFullYear()}`;
}

const TABS: { key: string; labelKey: string; match: (s: StatusKey) => boolean; Icon?: any }[] = [
  { key: "all", labelKey: "pos.all", match: () => true },
  { key: "low", labelKey: "prod.lowRunning", match: (s) => s === "low", Icon: Package },
  { key: "soon", labelKey: "prod.st_soon", match: (s) => s === "soon", Icon: ClockCountdown },
  { key: "expired", labelKey: "prod.st_expired", match: (s) => s === "expired", Icon: Prohibit },
  { key: "out", labelKey: "prod.st_out", match: (s) => s === "out", Icon: Warning },
];

export function Products() {
  const t = useT();
  const products = useGet<Product[]>("/products");
  const cats = useGet<Category[]>("/categories");
  const [q, setQ] = useState("");
  const [flt, setFlt] = useState("all");
  const [selId, setSelId] = useState<string | null>(null);
  const [add, setAdd] = useState(false);
  const [imp, setImp] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);

  const list = products.data || [];
  const catName = (id: string | null) => (cats.data || []).find((c) => c.id === id)?.name || "—";

  // Har mahsulotga holat + jonli sanagichlar (butun katalog bo'yicha)
  const withStatus = useMemo(() => list.map((p) => ({ p, s: statusOf(p) })), [list]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: list.length, low: 0, soon: 0, expired: 0, out: 0 };
    withStatus.forEach(({ s }) => { if (c[s] !== undefined) c[s]++; });
    return c;
  }, [withStatus, list.length]);

  const rows = useMemo(() => {
    const qq = q.trim().toLowerCase();
    const tab = TABS.find((tb) => tb.key === flt)!;
    return withStatus.filter(({ p, s }) =>
      tab.match(s) &&
      (!qq || p.name.toLowerCase().includes(qq) || p.article_code.includes(qq) || (p.sku || "").includes(qq))
    );
  }, [withStatus, q, flt]);

  // Katta katalogda (masalan 8000 mahsulot) hammasini birdan render qilsak — UI qotadi.
  // Shuning uchun faqat birinchi LIMIT tasini ko'rsatamiz; qolganini qidiruv bilan topiladi.
  const LIMIT = 200;
  const shown = useMemo(() => rows.slice(0, LIMIT), [rows]);

  const sel = list.find((p) => p.id === selId) || null;

  return (
    <main className="main">
      <header className="topbar">
        <div>
          <div className="h1">{t("prod.title")}</div>
          <div className="sub">{t("prod.sub")}</div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn-ghost" style={{ display: "flex", alignItems: "center", gap: 7 }} onClick={() => setImp(true)}>
            <DownloadSimple size={17} />{t("prod.excelImport")}
          </button>
          <button className="btn btn-primary" style={{ display: "flex", alignItems: "center", gap: 7 }} onClick={() => setAdd(true)}>
            <Plus size={17} weight="bold" />{t("prod.addProduct")}
          </button>
        </div>
      </header>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <div className="scroll" style={{ flex: 1, padding: 24 }}>
          {/* Summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16, marginBottom: 18 }}>
            <SummaryCard Icon={Package} color="var(--accent-strong)" soft="var(--accent-soft)" label={t("prod.totalProducts")} value={counts.all} />
            <SummaryCard Icon={Warning} color="var(--warn)" soft="var(--warn-soft)" label={t("prod.lowRunning")} value={counts.low} />
            <SummaryCard Icon={ClockCountdown} color="var(--danger)" soft="var(--danger-soft)" label={t("prod.st_soon")} value={counts.soon} />
          </div>

          {/* Search + selects */}
          <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 240, position: "relative" }}>
              <MagnifyingGlass size={17} color="var(--muted)" style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)" }} />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("prod.searchPlaceholder")}
                style={{ width: "100%", height: 48, padding: "0 14px 0 40px", border: "1px solid var(--border-input)", borderRadius: 12, background: "var(--surface)", color: "var(--text)", font: "inherit", fontSize: 14, outline: "none" }} />
            </div>
            <select disabled style={{ height: 48, padding: "0 14px", border: "1px solid var(--border-input)", borderRadius: 12, background: "var(--card)", color: "var(--text3)", font: "inherit", fontSize: 13.5 }}>
              <option>{t("prod.mainWarehouse")}</option>
            </select>
          </div>

          {/* Quick tabs */}
          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
            {TABS.map((tb) => {
              const on = flt === tb.key;
              const n = counts[tb.key] ?? 0;
              return (
                <button key={tb.key} onClick={() => setFlt(tb.key)}
                  style={{ height: 36, padding: "0 13px", borderRadius: 9, cursor: "pointer", font: "inherit", fontSize: 13, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 7, border: `1px solid ${on ? "#6d5dd3" : "var(--border)"}`, background: on ? "#6d5dd3" : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>
                  {tb.Icon && <tb.Icon size={15} />}{t(tb.labelKey)}
                  <span className="tabular" style={{ fontSize: 11.5, fontWeight: 700, padding: "1px 6px", borderRadius: 7, background: on ? "rgba(255,255,255,0.22)" : "var(--surface)", color: on ? "#fff" : "var(--muted)" }}>{n}</span>
                </button>
              );
            })}
          </div>

          {/* Table */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead><tr style={{ background: "var(--card-alt)" }}>
                  <th style={th}>{t("sales.thProduct")}</th><th style={th}>{t("prod.thSku")}</th><th style={th}>{t("audit.f_category")}</th>
                  <th style={{ ...th, textAlign: "right" }}>{t("prod.thStock")}</th><th style={{ ...th, textAlign: "right" }}>{t("prod.thMin")}</th>
                  <th style={{ ...th, textAlign: "right" }}>{t("prod.sellPrice")}</th><th style={th}>{t("prod.thExpiry")}</th><th style={th}>{t("prod.thStatus")}</th><th style={{ ...th, width: 44 }}></th>
                </tr></thead>
                <tbody>
                  {shown.map(({ p, s }) => {
                    const st = STATUS[s];
                    const dl = daysLeft(p.expiry_date);
                    return (
                      <tr key={p.id} onClick={() => setSelId(p.id)} style={{ cursor: "pointer", background: selId === p.id ? "var(--surface)" : undefined }}>
                        <td style={td}>
                          <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                            <div style={{ width: 34, height: 34, flex: "none", borderRadius: 9, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 700 }}>{p.name.charAt(0).toUpperCase()}</div>
                            <span style={{ fontWeight: 600 }}>{p.name}</span>
                          </div>
                        </td>
                        <td style={{ ...td, color: "var(--text3)" }} className="tabular">{p.sku || "—"}<div style={{ fontSize: 10.5, color: "var(--faint)" }}>{p.article_code}</div></td>
                        <td style={{ ...td, color: "var(--text3)" }}>{catName(p.category_id)}</td>
                        <td style={{ ...td, textAlign: "right", fontWeight: 700, color: s === "out" ? "var(--danger)" : "var(--text)" }} className="tabular">{p.stock} {unitL(t, p.unit_code)}</td>
                        <td style={{ ...td, textAlign: "right", color: "var(--muted)" }} className="tabular">{p.min_stock || "—"}</td>
                        <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.base_sell_price)}</td>
                        <td style={{ ...td, color: dl !== null && dl <= 7 ? "var(--danger)" : "var(--text3)" }} className="tabular">{fmtDate(p.expiry_date)}</td>
                        <td style={td}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 9, background: st.soft, color: st.color }}>
                            <span style={{ width: 7, height: 7, borderRadius: "50%", background: st.color }} />{t(st.labelKey)}
                          </span>
                        </td>
                        <td style={td}><DotsThreeVertical size={18} color="var(--faint)" /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {rows.length === 0 && <div style={{ padding: 56, textAlign: "center", color: "var(--muted)" }}>{t("prod.nothingFound")}</div>}
            {rows.length > LIMIT && <div style={{ padding: "14px 20px", textAlign: "center", color: "var(--muted)", fontSize: 13, borderTop: "1px solid var(--border)" }}>{t("prod.capped", { shown: LIMIT, total: rows.length })}</div>}
          </div>
        </div>

        {/* Detail panel (440px) */}
        {sel && (
          <DetailPanel product={sel} catName={catName(sel.category_id)} status={statusOf(sel)}
            onClose={() => setSelId(null)} onEdit={() => setEditId(sel.id)} />
        )}
      </div>

      {add && <AddModal cats={cats.data || []} onClose={() => setAdd(false)} onSaved={() => { setAdd(false); products.reload(); }} />}
      {editId && <EditModal productId={editId} cats={cats.data || []} onClose={() => setEditId(null)} onSaved={() => { setEditId(null); setSelId(null); products.reload(); }} />}
      {imp && <ImportWizard onClose={() => setImp(false)} onDone={() => { setImp(false); products.reload(); }} />}
    </main>
  );
}

function SummaryCard({ Icon, color, soft, label, value }: { Icon: any; color: string; soft: string; label: string; value: number }) {
  return (
    <div className="card" style={{ padding: "15px 18px", display: "flex", alignItems: "center", gap: 14 }}>
      <div style={{ width: 42, height: 42, flex: "none", borderRadius: 11, background: soft, color, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Icon size={22} weight="fill" />
      </div>
      <div>
        <div className="tabular" style={{ fontSize: 24, fontWeight: 800, lineHeight: 1 }}>{value}</div>
        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 3 }}>{label}</div>
      </div>
    </div>
  );
}

function DetailPanel({ product, catName, status, onClose, onEdit }: { product: Product; catName: string; status: StatusKey; onClose: () => void; onEdit: () => void }) {
  const t = useT();
  const detail = useGet<{ month_in: number; month_out: number; profit_unit: number; created_by_name: string }>(`/products/${product.id}`);
  const st = STATUS[status];
  const d = detail.data;
  const Row = ({ label, value, color }: { label: string; value: string; color?: string }) => (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderTop: "1px solid var(--border-soft)", fontSize: 13.5 }}>
      <span style={{ color: "var(--text3)" }}>{label}</span>
      <span className="tabular" style={{ fontWeight: 600, color: color || "var(--text)" }}>{value}</span>
    </div>
  );
  return (
    <aside style={{ width: 440, flex: "none", borderLeft: "1px solid var(--border)", background: "var(--card)", display: "flex", flexDirection: "column", overflowY: "auto" }}>
      <div style={{ padding: "20px 22px", display: "flex", alignItems: "flex-start", gap: 14 }}>
        <div style={{ width: 52, height: 52, flex: "none", borderRadius: 13, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, fontWeight: 800 }}>{product.name.charAt(0).toUpperCase()}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-0.02em" }}>{product.name}</div>
          <div className="tabular" style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>SKU {product.sku || "—"} · {product.article_code}</div>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, marginTop: 8, fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 9, background: st.soft, color: st.color }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: st.color }} />{t(st.labelKey)}
          </span>
        </div>
        <button onClick={onClose} style={{ width: 32, height: 32, border: "none", background: "var(--surface)", borderRadius: 9, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={16} /></button>
      </div>

      <div style={{ padding: "0 22px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div style={{ background: "var(--surface)", borderRadius: 12, padding: 14 }}>
          <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{t("prod.stockInWarehouse")}</div>
          <div className="tabular" style={{ fontSize: 20, fontWeight: 800, marginTop: 3, color: status === "out" ? "var(--danger)" : "var(--text)" }}>{product.stock} {unitL(t, product.unit_code)}</div>
        </div>
        <div style={{ background: "var(--surface)", borderRadius: 12, padding: 14 }}>
          <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{t("prod.minStock")}</div>
          <div className="tabular" style={{ fontSize: 20, fontWeight: 800, marginTop: 3 }}>{product.min_stock || "—"}</div>
        </div>
      </div>

      <div style={{ padding: "16px 22px 8px" }}>
        <Row label={t("audit.f_category")} value={catName} />
        <Row label={t("prod.monthIn")} value={d ? `+${d.month_in}` : "…"} color="var(--ok)" />
        <Row label={t("prod.monthOut")} value={d ? `−${d.month_out}` : "…"} color="var(--danger)" />
        <Row label={t("prod.sellPrice")} value={fmt(product.base_sell_price)} />
        <Row label={t("prod.buyPrice")} value={fmt(product.base_buy_price)} />
        <Row label={t("prod.profitUnit")} value={d ? fmt(d.profit_unit) : fmt(product.base_sell_price - product.base_buy_price)} color="var(--ok)" />
        <Row label={t("prod.expiryDate")} value={fmtDate(product.expiry_date)} />
      </div>

      <div style={{ padding: "10px 22px 22px", marginTop: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
        <button onClick={onEdit} className="btn btn-ghost" style={{ height: 46, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}><PencilSimple size={17} />{t("cust.edit")}</button>
        <button className="btn btn-primary" style={{ height: 46, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}><ArrowDown size={17} weight="bold" />{t("prod.stockIn")}</button>
        <button className="btn btn-ghost" style={{ height: 46, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}><ClockClockwise size={17} />{t("prod.saleHistory")}</button>
      </div>
    </aside>
  );
}

interface ImportRow { name: string; category?: string; buy: number; sell: number; stock: number; barcode?: string }

function ImportWizard({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [step, setStep] = useState(1);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<{ total: number; new: number; existing: number; error: number; sample: { name: string; article: string; category: string; status: string }[]; rows: ImportRow[] } | null>(null);
  const [imported, setImported] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const t = useT();

  const SAMPLE = "Coca-Cola 2L;Ichimliklar;90;130;60\nLipton 0.5L;Ichimliklar;50;75;40\nSnickers;Shirinliklar;60;90;100";

  function parseRows(): ImportRow[] {
    return text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l) => {
      const [name, category, buy, sell, stock, barcode] = l.split(/[;\t]/).map((s) => (s || "").trim());
      return { name: name || "", category: category || undefined, buy: +buy || 0, sell: +sell || 0, stock: +stock || 0, barcode: barcode || undefined };
    });
  }
  async function goPreview() {
    setBusy(true); setErr("");
    try { const rows = parseRows(); const pv = await post<any>("/products/import/preview", { rows }); setPreview({ ...pv, rows }); setStep(2); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function commit() {
    if (!preview) return;
    setBusy(true); setErr("");
    try { const r = await post<{ imported: number }>("/products/import/commit", { rows: preview.rows }); setImported(r.imported); setStep(3); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  const ST: Record<string, [string, string, string]> = { new: [t("prod.new"), "var(--ok-soft)", "var(--ok)"], existing: [t("prod.existing"), "var(--border)", "var(--muted)"], error: [t("common.error"), "var(--danger-soft)", "var(--danger)"] };

  return (
    <Modal onClose={onClose} width={560}>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, fontSize: 12.5, fontWeight: 700 }}>
        <span style={{ color: step >= 1 ? "var(--accent-strong)" : "var(--muted)" }}>1 · {t("prod.file")}</span>›
        <span style={{ color: step >= 2 ? "var(--accent-strong)" : "var(--muted)" }}>2 · {t("prod.check")}</span>›
        <span style={{ color: step >= 3 ? "var(--accent-strong)" : "var(--muted)" }}>3 · {t("prod.import")}</span>
      </div>

      {step === 1 && (
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>{t("prod.importTitle")}</div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 12 }}>{t("prod.eachRow")} <b>{t("prod.importFormat")}</b> {t("prod.semicolonSep")}</div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={SAMPLE} style={{ width: "100%", height: 160, padding: 12, border: "1.5px solid var(--border-input)", borderRadius: 11, fontSize: 13, fontFamily: "monospace", outline: "none", boxSizing: "border-box", resize: "vertical", background: "var(--card)", color: "var(--text)" }} />
          <button onClick={() => setText(SAMPLE)} style={{ marginTop: 8, border: "none", background: "none", color: "var(--accent)", cursor: "pointer", fontWeight: 600, fontSize: 13 }}>{t("prod.fillSample")}</button>
          {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
            <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy || !text.trim()} onClick={goPreview}>{busy ? "..." : t("prod.continue")}</button>
          </div>
        </div>
      )}

      {step === 2 && preview && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 16 }}>
            {[[t("prod.total"), preview.total, "var(--text3)"], [t("prod.new"), preview.new, "var(--ok)"], [t("prod.existing"), preview.existing, "var(--muted)"], [t("common.error"), preview.error, "var(--danger)"]].map(([l, v, c]) => (
              <div key={l as string} style={{ background: "var(--surface)", borderRadius: 12, padding: 12, textAlign: "center" }}>
                <div className="tabular" style={{ fontSize: 20, fontWeight: 800, color: c as string }}>{v as number}</div>
                <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{l as string}</div>
              </div>
            ))}
          </div>
          <div style={{ maxHeight: 220, overflowY: "auto", border: "1px solid var(--border)", borderRadius: 12 }}>
            {preview.sample.map((r, i) => {
              const s = ST[r.status] || ["?", "var(--surface)", "var(--muted)"];
              return (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", borderTop: i ? "1px solid var(--border-soft)" : "none", fontSize: 13 }}>
                  <span style={{ fontWeight: 600 }}>{r.name}</span>
                  <span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 8, background: s[1], color: s[2] }}>{s[0]}</span>
                </div>
              );
            })}
          </div>
          {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => setStep(1)}>{t("prod.back")}</button>
            <button className="btn btn-primary" style={{ flex: 2 }} disabled={busy} onClick={commit}>{busy ? "..." : t("prod.importN", { n: preview.new })}</button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div style={{ textAlign: "center", padding: "10px 0" }}>
          <div style={{ width: 66, height: 66, margin: "0 auto 8px", borderRadius: "50%", background: "var(--ok-soft)", color: "var(--ok)", display: "flex", alignItems: "center", justifyContent: "center" }}><Plus size={32} weight="bold" /></div>
          <div style={{ fontSize: 20, fontWeight: 800, marginTop: 8 }}>{t("prod.importDone")}</div>
          <div style={{ fontSize: 13.5, color: "var(--muted)", marginTop: 6 }}>{t("prod.importedN", { n: imported })}</div>
          <button className="btn btn-primary" style={{ width: "100%", marginTop: 20, height: 48 }} onClick={onDone}>{t("prod.openList")}</button>
        </div>
      )}
    </Modal>
  );
}

function EditModal({ productId, cats, onClose, onSaved }: { productId: string; cats: Category[]; onClose: () => void; onSaved: () => void }) {
  const t = useT();
  const detail = useGet<Product & { created_by_name: string; created_at: string }>(`/products/${productId}`);
  const d = detail.data;
  const [name, setName] = useState("");
  const [cat, setCat] = useState("");
  const [buy, setBuy] = useState("");
  const [sell, setSell] = useState("");
  const [min, setMin] = useState("");
  const [expiry, setExpiry] = useState("");
  const [weighed, setWeighed] = useState(false);
  const [plu, setPlu] = useState("");
  const [sync, setSync] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (d && !loaded) {
    setName(d.name); setCat(d.category_id || ""); setBuy(String(d.base_buy_price));
    setSell(String(d.base_sell_price)); setMin(String(d.min_stock || "")); setExpiry(d.expiry_date || "");
    setWeighed(!!d.is_weighted); setPlu(d.plu_code || ""); setSync(d.scale_sync !== false);
    setLoaded(true);
  }

  async function save() {
    if (weighed && !plu.trim()) { setErr(t("prod2.pluUnique")); return; }
    setBusy(true); setErr("");
    try {
      await api(`/products/${productId}`, { method: "PATCH", body: JSON.stringify({ name, category_id: cat, buy_price: +buy || 0, sell_price: +sell || 0, min_qty: +min || 0, expiry_date: expiry || "", is_weighted: weighed, plu_code: weighed ? plu : "", scale_sync: weighed ? sync : false, ...(weighed ? { unit_code: "kg" } : {}) }) });
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function del() {
    if (!window.confirm(t("cust.deleteConfirm", { name }))) return;
    setBusy(true); setErr("");
    try { await api(`/products/${productId}`, { method: "DELETE" }); onSaved(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 4 }}>{t("prod.editProduct")}</div>
      <div style={{ fontSize: 12.5, color: "var(--muted)" }} className="tabular">{d?.article_code || ""}</div>
      {d && (
        <div style={{ fontSize: 12.5, color: "var(--muted)", margin: "6px 0 16px", padding: "8px 12px", background: "var(--surface)", borderRadius: 9 }}>
          {t("prod.addedBy")} <b style={{ color: "var(--text2)" }}>{d.created_by_name}</b>{d.created_at ? ` · ${new Date(d.created_at).toLocaleDateString("ru-RU")}` : ""}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("prod.namePlaceholder")} style={inputStyle} />
        <select value={cat} onChange={(e) => setCat(e.target.value)} style={inputStyle}>
          <option value="">{t("prod.pickCategory")}</option>
          {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <div style={{ display: "flex", gap: 10 }}>
          <input value={buy} onChange={(e) => setBuy(e.target.value.replace(/\D/g, ""))} placeholder={t("prod.arrivalPrice")} style={inputStyle} />
          <input value={sell} onChange={(e) => setSell(e.target.value.replace(/\D/g, ""))} placeholder={t("prod.salePricePh")} style={inputStyle} />
        </div>
        <SaleTypeSection t={t} weighed={weighed} setWeighed={setWeighed} plu={plu} setPlu={setPlu} sync={sync} setSync={setSync} />
        <div style={{ display: "flex", gap: 10 }}>
          <input value={min} onChange={(e) => setMin(e.target.value.replace(/\D/g, ""))} placeholder={t("prod.minStock")} style={inputStyle} />
          <input type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} style={inputStyle} />
        </div>
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn" style={{ background: "var(--danger-soft)", color: "var(--danger)", padding: "0 16px" }} disabled={busy} onClick={del}>{t("prod.delete")}</button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-ghost" onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "..." : t("common.save")}</button>
      </div>
    </Modal>
  );
}

function SaleTypeSection({ t, weighed, setWeighed, plu, setPlu, sync, setSync }: { t: (k: string, v?: any) => string; weighed: boolean; setWeighed: (v: boolean) => void; plu: string; setPlu: (v: string) => void; sync: boolean; setSync: (v: boolean) => void }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 12, padding: 14, background: "var(--surface)" }}>
      <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text3)", marginBottom: 10 }}>{t("prod2.saleType")}</div>
      <div style={{ display: "flex", gap: 8 }}>
        {([["unit", t("prod2.byUnit")], ["weight", t("prod2.byWeight")]] as const).map(([k, l]) => {
          const on = (k === "weight") === weighed;
          return <button key={k} type="button" onClick={() => setWeighed(k === "weight")} style={{ flex: 1, height: 42, borderRadius: 10, cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600, border: `1.5px solid ${on ? "#6d5dd3" : "var(--border)"}`, background: on ? "var(--accent-soft)" : "var(--card)", color: on ? "var(--accent-strong)" : "var(--muted)" }}>{l}</button>;
        })}
      </div>
      {weighed && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
          <div>
            <label style={{ fontSize: 12, color: "var(--text3)", fontWeight: 600 }}>{t("prod2.plu")}</label>
            <input value={plu} onChange={(e) => setPlu(e.target.value.replace(/\D/g, ""))} placeholder="123" style={{ ...inputStyle, marginTop: 5 }} />
          </div>
          <div style={{ fontSize: 11.5, color: "var(--muted)", lineHeight: 1.4 }}>{t("prod2.priceIsPerKg")}</div>
          <label style={{ display: "flex", alignItems: "center", gap: 9, cursor: "pointer" }}>
            <input type="checkbox" checked={sync} onChange={(e) => setSync(e.target.checked)} style={{ width: 16, height: 16, accentColor: "#6d5dd3" }} />
            <span style={{ fontSize: 13, color: "var(--text2)", fontWeight: 500 }}>{t("prod2.syncToScaleHint")}</span>
          </label>
        </div>
      )}
    </div>
  );
}

function AddModal({ cats, onClose, onSaved }: { cats: Category[]; onClose: () => void; onSaved: () => void }) {
  const t = useT();
  const [name, setName] = useState("");
  const [cat, setCat] = useState(cats[0]?.id || "");
  const [buy, setBuy] = useState("");
  const [sell, setSell] = useState("");
  const [stock, setStock] = useState("");
  const [min, setMin] = useState("");
  const [expiry, setExpiry] = useState("");
  const [weighed, setWeighed] = useState(false);
  const [plu, setPlu] = useState("");
  const [sync, setSync] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    if (!name.trim()) return;
    if (weighed && !plu.trim()) { setErr(t("prod2.pluUnique")); return; }
    setBusy(true); setErr("");
    try {
      await post("/products/bulk", { items: [{ name, category_id: cat || null, buy_price: +buy || 0, sell_price: +sell || 0, stock: +stock || 0, min_qty: +min || 0, expiry_date: expiry || null, unit_code: weighed ? "kg" : "dona", is_weighted: weighed, plu_code: weighed ? (plu || null) : null, scale_sync: weighed ? sync : false }] });
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>{t("prod.newProduct")}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input placeholder={t("prod.namePlaceholder")} value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} />
        <select value={cat} onChange={(e) => setCat(e.target.value)} style={inputStyle}>
          <option value="">{t("prod.pickCategory")}</option>
          {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <div style={{ display: "flex", gap: 10 }}>
          <input placeholder={t("prod.arrivalPrice")} value={buy} onChange={(e) => setBuy(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
          <input placeholder={t("prod.salePricePh")} value={sell} onChange={(e) => setSell(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <input placeholder={t("prod.initialStock")} value={stock} onChange={(e) => setStock(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
          <input placeholder={t("prod.minStock")} value={min} onChange={(e) => setMin(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
        </div>
        <input type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} style={inputStyle} />
        <SaleTypeSection t={t} weighed={weighed} setWeighed={setWeighed} plu={plu} setPlu={setPlu} sync={sync} setSync={setSync} />
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : t("common.save")}</button>
      </div>
    </Modal>
  );
}
