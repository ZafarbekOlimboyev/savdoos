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

interface Product {
  id: string; article_code: string; sku: string | null; name: string;
  category_id: string | null; base_buy_price: number; base_sell_price: number;
  stock: number; min_stock: number; unit_code: string | null; expiry_date: string | null;
}
interface Category { id: string; name: string }

const STATUS: Record<StatusKey, { label: string; color: string; soft: string }> = {
  ok: { label: "Yetarli", color: "var(--ok)", soft: "var(--ok-soft)" },
  mid: { label: "O'rtacha", color: "var(--text3)", soft: "var(--surface)" },
  low: { label: "Kam", color: "var(--warn)", soft: "var(--warn-soft)" },
  soon: { label: "Muddati yaqin", color: "var(--warn)", soft: "var(--warn-soft)" },
  expired: { label: "Muddati o'tgan", color: "var(--danger)", soft: "var(--danger-soft)" },
  out: { label: "Tugagan", color: "var(--danger)", soft: "var(--danger-soft)" },
};

const statusOf = (p: Product): StatusKey => statusOfShared(p);
function fmtDate(d: string | null): string {
  if (!d) return "—";
  const dt = new Date(d + "T00:00:00");
  return `${String(dt.getDate()).padStart(2, "0")}.${String(dt.getMonth() + 1).padStart(2, "0")}.${dt.getFullYear()}`;
}

const TABS: { key: string; label: string; match: (s: StatusKey) => boolean; Icon?: any }[] = [
  { key: "all", label: "Barchasi", match: () => true },
  { key: "low", label: "Kam qolgan", match: (s) => s === "low", Icon: Package },
  { key: "soon", label: "Muddati yaqin", match: (s) => s === "soon", Icon: ClockCountdown },
  { key: "expired", label: "Muddati o'tgan", match: (s) => s === "expired", Icon: Prohibit },
  { key: "out", label: "Tugagan", match: (s) => s === "out", Icon: Warning },
];

export function Products() {
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
    const tab = TABS.find((t) => t.key === flt)!;
    return withStatus.filter(({ p, s }) =>
      tab.match(s) &&
      (!qq || p.name.toLowerCase().includes(qq) || p.article_code.includes(qq) || (p.sku || "").includes(qq))
    );
  }, [withStatus, q, flt]);

  const sel = list.find((p) => p.id === selId) || null;

  return (
    <main className="main">
      <header className="topbar">
        <div>
          <div className="h1">Mahsulotlar va ombor</div>
          <div className="sub">Zaxira holati va mahsulotlarni boshqarish</div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn-ghost" style={{ display: "flex", alignItems: "center", gap: 7 }} onClick={() => setImp(true)}>
            <DownloadSimple size={17} />Excel import
          </button>
          <button className="btn btn-primary" style={{ display: "flex", alignItems: "center", gap: 7 }} onClick={() => setAdd(true)}>
            <Plus size={17} weight="bold" />Mahsulot qo'shish
          </button>
        </div>
      </header>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <div className="scroll" style={{ flex: 1, padding: 24 }}>
          {/* Summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16, marginBottom: 18 }}>
            <SummaryCard Icon={Package} color="var(--accent-strong)" soft="var(--accent-soft)" label="Jami mahsulot" value={counts.all} />
            <SummaryCard Icon={Warning} color="var(--warn)" soft="var(--warn-soft)" label="Kam qolgan" value={counts.low} />
            <SummaryCard Icon={ClockCountdown} color="var(--danger)" soft="var(--danger-soft)" label="Muddati yaqin" value={counts.soon} />
          </div>

          {/* Search + selects */}
          <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 240, position: "relative" }}>
              <MagnifyingGlass size={17} color="var(--muted)" style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)" }} />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Mahsulot nomi yoki SKU / artikul bo'yicha qidirish..."
                style={{ width: "100%", height: 48, padding: "0 14px 0 40px", border: "1px solid var(--border-input)", borderRadius: 12, background: "var(--surface)", color: "var(--text)", font: "inherit", fontSize: 14, outline: "none" }} />
            </div>
            <select disabled style={{ height: 48, padding: "0 14px", border: "1px solid var(--border-input)", borderRadius: 12, background: "var(--card)", color: "var(--text3)", font: "inherit", fontSize: 13.5 }}>
              <option>Asosiy ombor</option>
            </select>
          </div>

          {/* Quick tabs */}
          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
            {TABS.map((t) => {
              const on = flt === t.key;
              const n = counts[t.key] ?? 0;
              return (
                <button key={t.key} onClick={() => setFlt(t.key)}
                  style={{ height: 36, padding: "0 13px", borderRadius: 9, cursor: "pointer", font: "inherit", fontSize: 13, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 7, border: `1px solid ${on ? "#6d5dd3" : "var(--border)"}`, background: on ? "#6d5dd3" : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>
                  {t.Icon && <t.Icon size={15} />}{t.label}
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
                  <th style={th}>Mahsulot</th><th style={th}>SKU / Artikul</th><th style={th}>Kategoriya</th>
                  <th style={{ ...th, textAlign: "right" }}>Qoldiq</th><th style={{ ...th, textAlign: "right" }}>Min.</th>
                  <th style={{ ...th, textAlign: "right" }}>Sotuv narxi</th><th style={th}>Muddati</th><th style={th}>Holat</th><th style={{ ...th, width: 44 }}></th>
                </tr></thead>
                <tbody>
                  {rows.map(({ p, s }) => {
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
                        <td style={{ ...td, textAlign: "right", fontWeight: 700, color: s === "out" ? "var(--danger)" : "var(--text)" }} className="tabular">{p.stock} {p.unit_code || ""}</td>
                        <td style={{ ...td, textAlign: "right", color: "var(--muted)" }} className="tabular">{p.min_stock || "—"}</td>
                        <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.base_sell_price)}</td>
                        <td style={{ ...td, color: dl !== null && dl <= 7 ? "var(--danger)" : "var(--text3)" }} className="tabular">{fmtDate(p.expiry_date)}</td>
                        <td style={td}>
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 9, background: st.soft, color: st.color }}>
                            <span style={{ width: 7, height: 7, borderRadius: "50%", background: st.color }} />{st.label}
                          </span>
                        </td>
                        <td style={td}><DotsThreeVertical size={18} color="var(--faint)" /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {rows.length === 0 && <div style={{ padding: 56, textAlign: "center", color: "var(--muted)" }}>Hech narsa topilmadi</div>}
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
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: st.color }} />{st.label}
          </span>
        </div>
        <button onClick={onClose} style={{ width: 32, height: 32, border: "none", background: "var(--surface)", borderRadius: 9, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={16} /></button>
      </div>

      <div style={{ padding: "0 22px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div style={{ background: "var(--surface)", borderRadius: 12, padding: 14 }}>
          <div style={{ fontSize: 11.5, color: "var(--muted)" }}>Ombordagi qoldiq</div>
          <div className="tabular" style={{ fontSize: 20, fontWeight: 800, marginTop: 3, color: status === "out" ? "var(--danger)" : "var(--text)" }}>{product.stock} {product.unit_code || ""}</div>
        </div>
        <div style={{ background: "var(--surface)", borderRadius: 12, padding: 14 }}>
          <div style={{ fontSize: 11.5, color: "var(--muted)" }}>Minimal qoldiq</div>
          <div className="tabular" style={{ fontSize: 20, fontWeight: 800, marginTop: 3 }}>{product.min_stock || "—"}</div>
        </div>
      </div>

      <div style={{ padding: "16px 22px 8px" }}>
        <Row label="Kategoriya" value={catName} />
        <Row label="Bu oy kirim" value={d ? `+${d.month_in}` : "…"} color="var(--ok)" />
        <Row label="Bu oy chiqim" value={d ? `−${d.month_out}` : "…"} color="var(--danger)" />
        <Row label="Sotuv narxi" value={fmt(product.base_sell_price)} />
        <Row label="Xarid narxi" value={fmt(product.base_buy_price)} />
        <Row label="Foyda (dona)" value={d ? fmt(d.profit_unit) : fmt(product.base_sell_price - product.base_buy_price)} color="var(--ok)" />
        <Row label="Yaroqlilik muddati" value={fmtDate(product.expiry_date)} />
      </div>

      <div style={{ padding: "10px 22px 22px", marginTop: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
        <button onClick={onEdit} className="btn btn-ghost" style={{ height: 46, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}><PencilSimple size={17} />Tahrirlash</button>
        <button className="btn btn-primary" style={{ height: 46, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}><ArrowDown size={17} weight="bold" />Kirim qilish</button>
        <button className="btn btn-ghost" style={{ height: 46, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}><ClockClockwise size={17} />Sotuv tarixini ko'rish</button>
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

  const ST: Record<string, [string, string, string]> = { new: ["Yangi", "var(--ok-soft)", "var(--ok)"], existing: ["Mavjud", "var(--border)", "var(--muted)"], error: ["Xato", "var(--danger-soft)", "var(--danger)"] };

  return (
    <Modal onClose={onClose} width={560}>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, fontSize: 12.5, fontWeight: 700 }}>
        <span style={{ color: step >= 1 ? "var(--accent-strong)" : "var(--muted)" }}>1 · Fayl</span>›
        <span style={{ color: step >= 2 ? "var(--accent-strong)" : "var(--muted)" }}>2 · Tekshirish</span>›
        <span style={{ color: step >= 3 ? "var(--accent-strong)" : "var(--muted)" }}>3 · Import</span>
      </div>

      {step === 1 && (
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>Excel / CSV / 1C import</div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 12 }}>Har qator: <b>nom;kategoriya;kelish;sotish;qoldiq;barcode</b> (nuqtali vergul bilan)</div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={SAMPLE} style={{ width: "100%", height: 160, padding: 12, border: "1.5px solid var(--border-input)", borderRadius: 11, fontSize: 13, fontFamily: "monospace", outline: "none", boxSizing: "border-box", resize: "vertical", background: "var(--card)", color: "var(--text)" }} />
          <button onClick={() => setText(SAMPLE)} style={{ marginTop: 8, border: "none", background: "none", color: "var(--accent)", cursor: "pointer", fontWeight: 600, fontSize: 13 }}>Namuna bilan to'ldirish</button>
          {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 8 }}>{err}</div>}
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>Bekor</button>
            <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy || !text.trim()} onClick={goPreview}>{busy ? "..." : "Davom etish"}</button>
          </div>
        </div>
      )}

      {step === 2 && preview && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 16 }}>
            {[["Jami", preview.total, "var(--text3)"], ["Yangi", preview.new, "var(--ok)"], ["Mavjud", preview.existing, "var(--muted)"], ["Xato", preview.error, "var(--danger)"]].map(([l, v, c]) => (
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
            <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => setStep(1)}>Orqaga</button>
            <button className="btn btn-primary" style={{ flex: 2 }} disabled={busy} onClick={commit}>{busy ? "..." : `${preview.new} ta mahsulotni import qilish`}</button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div style={{ textAlign: "center", padding: "10px 0" }}>
          <div style={{ width: 66, height: 66, margin: "0 auto 8px", borderRadius: "50%", background: "var(--ok-soft)", color: "var(--ok)", display: "flex", alignItems: "center", justifyContent: "center" }}><Plus size={32} weight="bold" /></div>
          <div style={{ fontSize: 20, fontWeight: 800, marginTop: 8 }}>Import yakunlandi</div>
          <div style={{ fontSize: 13.5, color: "var(--muted)", marginTop: 6 }}>{imported} ta yangi mahsulot qo'shildi</div>
          <button className="btn btn-primary" style={{ width: "100%", marginTop: 20, height: 48 }} onClick={onDone}>Ro'yxatni ochish</button>
        </div>
      )}
    </Modal>
  );
}

function EditModal({ productId, cats, onClose, onSaved }: { productId: string; cats: Category[]; onClose: () => void; onSaved: () => void }) {
  const detail = useGet<Product & { created_by_name: string; created_at: string }>(`/products/${productId}`);
  const d = detail.data;
  const [name, setName] = useState("");
  const [cat, setCat] = useState("");
  const [buy, setBuy] = useState("");
  const [sell, setSell] = useState("");
  const [min, setMin] = useState("");
  const [expiry, setExpiry] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (d && !loaded) {
    setName(d.name); setCat(d.category_id || ""); setBuy(String(d.base_buy_price));
    setSell(String(d.base_sell_price)); setMin(String(d.min_stock || "")); setExpiry(d.expiry_date || "");
    setLoaded(true);
  }

  async function save() {
    setBusy(true); setErr("");
    try {
      await api(`/products/${productId}`, { method: "PATCH", body: JSON.stringify({ name, category_id: cat, buy_price: +buy || 0, sell_price: +sell || 0, min_qty: +min || 0, expiry_date: expiry || "" }) });
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function del() {
    if (!window.confirm(`"${name}" o'chirilsinmi?`)) return;
    setBusy(true); setErr("");
    try { await api(`/products/${productId}`, { method: "DELETE" }); onSaved(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 4 }}>Mahsulotni tahrirlash</div>
      <div style={{ fontSize: 12.5, color: "var(--muted)" }} className="tabular">{d?.article_code || ""}</div>
      {d && (
        <div style={{ fontSize: 12.5, color: "var(--muted)", margin: "6px 0 16px", padding: "8px 12px", background: "var(--surface)", borderRadius: 9 }}>
          Qo'shgan: <b style={{ color: "var(--text2)" }}>{d.created_by_name}</b>{d.created_at ? ` · ${new Date(d.created_at).toLocaleDateString("ru-RU")}` : ""}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nomi" style={inputStyle} />
        <select value={cat} onChange={(e) => setCat(e.target.value)} style={inputStyle}>
          <option value="">— kategoriya —</option>
          {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <div style={{ display: "flex", gap: 10 }}>
          <input value={buy} onChange={(e) => setBuy(e.target.value.replace(/\D/g, ""))} placeholder="Kelish narxi" style={inputStyle} />
          <input value={sell} onChange={(e) => setSell(e.target.value.replace(/\D/g, ""))} placeholder="Sotish narxi" style={inputStyle} />
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <input value={min} onChange={(e) => setMin(e.target.value.replace(/\D/g, ""))} placeholder="Minimal qoldiq" style={inputStyle} />
          <input type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} style={inputStyle} />
        </div>
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn" style={{ background: "var(--danger-soft)", color: "var(--danger)", padding: "0 16px" }} disabled={busy} onClick={del}>O'chirish</button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-ghost" onClick={onClose}>Bekor</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "..." : "Saqlash"}</button>
      </div>
    </Modal>
  );
}

function AddModal({ cats, onClose, onSaved }: { cats: Category[]; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [cat, setCat] = useState(cats[0]?.id || "");
  const [buy, setBuy] = useState("");
  const [sell, setSell] = useState("");
  const [stock, setStock] = useState("");
  const [min, setMin] = useState("");
  const [expiry, setExpiry] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    if (!name.trim()) return;
    setBusy(true); setErr("");
    try {
      await post("/products/bulk", { items: [{ name, category_id: cat || null, buy_price: +buy || 0, sell_price: +sell || 0, stock: +stock || 0, min_qty: +min || 0, expiry_date: expiry || null }] });
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>Yangi mahsulot</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input placeholder="Nomi" value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} />
        <select value={cat} onChange={(e) => setCat(e.target.value)} style={inputStyle}>
          <option value="">— kategoriya —</option>
          {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <div style={{ display: "flex", gap: 10 }}>
          <input placeholder="Kelish narxi" value={buy} onChange={(e) => setBuy(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
          <input placeholder="Sotish narxi" value={sell} onChange={(e) => setSell(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <input placeholder="Boshlang'ich qoldiq" value={stock} onChange={(e) => setStock(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
          <input placeholder="Minimal qoldiq" value={min} onChange={(e) => setMin(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
        </div>
        <input type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} style={inputStyle} />
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>Bekor</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : "Saqlash"}</button>
      </div>
    </Modal>
  );
}
