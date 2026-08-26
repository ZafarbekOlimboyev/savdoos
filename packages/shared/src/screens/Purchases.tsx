import { useRef, useState } from "react";
import { api, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Modal, Topbar, inputStyle, td, th, useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { FullReceiving, type Product as CatalogProduct } from "./Products";

interface Purchase { id: string; doc_no: string; supplier: string; date: string; total: number; status: string; }
interface Supplier { id: string; name: string; phone: string | null; balance: number; }
interface Product { id: string; name: string; base_buy_price: number; base_sell_price: number; stock: number; }
interface Category { id: string; name: string }

// Kirim qatori: mavjud mahsulot (pid) YOKI yangi nom. Mavjudni tanlasa narxlar bazadan
// avto-to'ladi; foydalanuvchi o'zgartirsa — commit'da mahsulot kartochkasi ham yangilanadi.
interface KRow { pid: string; name: string; qty: string; cost: string; sell: string; catId: string; open: boolean; aiName?: string; unit?: string }

const emptyRow = (): KRow => ({ pid: "", name: "", qty: "", cost: "", sell: "", catId: "", open: false });

export function Purchases() {
  const purchases = useGet<Purchase[]>("/purchases");
  const suppliers = useGet<Supplier[]>("/suppliers");
  const catalog = useGet<CatalogProduct[]>("/products");
  const cats = useGet<Category[]>("/categories");
  const [add, setAdd] = useState(false);
  const [photo, setPhoto] = useState(false);
  const [editSup, setEditSup] = useState<Supplier | null>(null);
  const [selSup, setSelSup] = useState<string | null>(null); // yetkazib beruvchi batafsil
  const [supPage, setSupPage] = useState(false);   // yetkazib beruvchilar to'liq sahifasi
  const [newSup, setNewSup] = useState(false);
  const t = useT();

  const list = purchases.data || [];
  const sup = suppliers.data || [];
  const debt = sup.reduce((t, s) => t + s.balance, 0);
  const reload = () => { purchases.reload(); suppliers.reload(); catalog.reload(); };

  // "Yangi kirim" endi Ombordagi bilan bir xil oqim (FullReceiving) — takror bo'lmasin.
  if (add) {
    return <FullReceiving cats={cats.data || []} products={catalog.data || []} suppliers={sup}
      onBack={() => setAdd(false)}
      onSaved={() => { setAdd(false); reload(); }} />;
  }
  if (selSup) {
    return <SupplierDetail id={selSup} onBack={() => { setSelSup(null); suppliers.reload(); }}
      onEdit={() => { const s = sup.find((x) => x.id === selSup); if (s) setEditSup(s); }}
      editModal={editSup ? <SupplierEdit s={editSup} onClose={() => setEditSup(null)} onDone={() => { setEditSup(null); suppliers.reload(); }} /> : null} />;
  }
  if (supPage) {
    return <SuppliersPage suppliers={sup} onBack={() => { setSupPage(false); suppliers.reload(); }}
      onOpen={(id) => setSelSup(id)} onAdd={() => setNewSup(true)}
      newSupModal={newSup ? <SupplierNew onClose={() => setNewSup(false)} onDone={() => { setNewSup(false); suppliers.reload(); }} /> : null} />;
  }

  return (
    <main className="main">
      <Topbar title={t("nav.xaridlar")} sub={t("purch.sub")}
        right={<div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn-ghost" onClick={() => setPhoto(true)}>📷 {t("purch.photoKirim")}</button>
          <button className="btn btn-primary" onClick={() => setAdd(true)}>＋ {t("purch.newKirim")}</button>
        </div>} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18, marginBottom: 20 }}>
          <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("purch.docs")}</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8 }}>{list.length}</div></div>
          {/* Yetkazib beruvchilar CARD — bosilsa to'liq sahifa ochiladi */}
          <div className="card" onClick={() => setSupPage(true)} title={t("purch.openSuppliers")}
            style={{ cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--accent-border)")}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--border)")}>
            <div>
              <div style={{ fontSize: 13, color: "var(--muted)" }}>{t("purch.suppliers")}</div>
              <div style={{ fontSize: 26, fontWeight: 800, marginTop: 8 }}>{sup.length}</div>
            </div>
            <span style={{ color: "var(--accent-strong)", fontSize: 22 }}>›</span>
          </div>
          <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("purch.supplierDebt")}</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8, color: "var(--red)" }} className="tabular">{fmt(debt)}</div></div>
        </div>

        {/* Xarid hujjatlari — to'liq enlik */}
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ padding: "18px 20px 12px", fontSize: 16, fontWeight: 700 }}>{t("purch.docs")}</div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "var(--card-alt)" }}><th style={th}>{t("purch.thDoc")}</th><th style={th}>{t("purch.thSupplier")}</th><th style={th}>{t("purch.thDate")}</th><th style={{ ...th, textAlign: "right" }}>{t("sales.thSum")}</th><th style={th}>{t("purch.thStatus")}</th></tr></thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.id}>
                  <td style={{ ...td, fontWeight: 700 }}>{p.doc_no}</td>
                  <td style={{ ...td, color: "var(--text2)" }}>{p.supplier}</td>
                  <td style={{ ...td, color: "var(--muted)" }}>{p.date}</td>
                  <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.total)}</td>
                  <td style={td}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: p.status === "debt" ? "var(--warn-soft)" : "var(--ok-soft)", color: p.status === "debt" ? "var(--warn)" : "var(--ok)" }}>{p.status === "debt" ? t("pay.credit") : t("purch.paid")}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.length === 0 && <div style={{ padding: 30, textAlign: "center", color: "var(--muted)" }}>{t("purch.noKirim")}</div>}
        </div>
      </div>

      {photo && <PhotoKirim suppliers={sup} onClose={() => setPhoto(false)} onSaved={() => { setPhoto(false); reload(); }} />}
      {editSup && <SupplierEdit s={editSup} onClose={() => setEditSup(null)} onDone={() => { setEditSup(null); suppliers.reload(); }} />}
    </main>
  );
}

function SupplierEdit({ s, onClose, onDone }: { s: Supplier; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(s.name);
  const [phone, setPhone] = useState(s.phone || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const t = useT();
  async function save() { setBusy(true); setErr(""); try { await api(`/suppliers/${s.id}`, { method: "PATCH", body: JSON.stringify({ name, phone }) }); onDone(); } catch (e: any) { setErr(e?.message || t("common.error")); } finally { setBusy(false); } }
  async function del() { if (!window.confirm(t("cust.deleteConfirm", { name: `"${s.name}"` }))) return; setBusy(true); setErr(""); try { await api(`/suppliers/${s.id}`, { method: "DELETE" }); onDone(); } catch (e: any) { setErr(e?.message || t("common.error")); } finally { setBusy(false); } }
  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>{t("purch.supplier")}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("purch.name")} style={inputStyle} />
        <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder={t("cust.thPhone")} style={inputStyle} />
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        {err && <div style={{ color: "var(--danger)", fontSize: 12.5, alignSelf: "center" }}>{err}</div>}
        <button className="btn" style={{ background: "var(--danger-soft)", color: "var(--danger)", padding: "0 16px" }} disabled={busy} onClick={del}>🗑</button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-ghost" onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "..." : t("common.save")}</button>
      </div>
    </Modal>
  );
}

function SupplierNew({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const t = useT();
  async function save() { if (!name.trim()) return; setBusy(true); setErr(""); try { await post("/suppliers", { name, phone }); onDone(); } catch (e: any) { setErr(e?.message || t("common.error")); } finally { setBusy(false); } }
  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>{t("purch.newSupplier")}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("purch.name")} style={inputStyle} />
        <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder={t("cust.thPhone")} style={inputStyle} />
      </div>
      {err && <div style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : t("common.add")}</button>
      </div>
    </Modal>
  );
}

// ── Kirim qatorlari muharriri (qo'lda + rasm oqimlari uchun umumiy) ──────────
function RowsEditor({ rows, setRows, products, cats, t }: {
  rows: KRow[]; setRows: (f: (r: KRow[]) => KRow[]) => void;
  products: Product[]; cats: Category[]; t: (k: string, v?: Record<string, string | number>) => string;
}) {
  const setRow = (i: number, patch: Partial<KRow>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const pick = (i: number, p: Product) => setRow(i, { pid: p.id, name: p.name, cost: String(p.base_buy_price || ""), sell: String(p.base_sell_price || ""), open: false });
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {rows.map((r, i) => {
        const q = r.name.trim().toLowerCase();
        const sugg = r.open && q.length >= 2 && !r.pid
          ? products.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 8)
          : [];
        const prod = products.find((p) => p.id === r.pid);
        const isNew = !r.pid && r.name.trim().length > 0;
        return (
          <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 12, padding: "10px 12px", background: "var(--surface)" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
                <input value={r.name} placeholder={t("purch.searchProduct")}
                  onChange={(e) => setRow(i, { name: e.target.value, pid: "", open: true })}
                  onFocus={() => setRow(i, { open: true })}
                  style={{ ...inputStyle, height: 42, width: "100%" }} />
                {sugg.length > 0 && (
                  <div style={{ position: "absolute", left: 0, right: 0, top: 46, zIndex: 40, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, boxShadow: "0 12px 30px rgba(0,0,0,0.18)", overflow: "hidden" }}>
                    {sugg.map((p) => (
                      <div key={p.id} onClick={() => pick(i, p)} style={{ padding: "9px 12px", cursor: "pointer", fontSize: 13, display: "flex", justifyContent: "space-between", gap: 10, borderTop: "1px solid var(--border-soft)" }}>
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</span>
                        <span className="tabular" style={{ color: "var(--muted)", flex: "none" }}>{fmt(p.base_sell_price)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <input placeholder={t("purch.qty")} value={r.qty} onChange={(e) => setRow(i, { qty: e.target.value.replace(/[^\d.]/g, "") })} inputMode="decimal" style={{ ...inputStyle, height: 42, width: 76, textAlign: "right" }} />
              <button onClick={() => setRows((rr) => rr.filter((_, j) => j !== i))} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--faint)", fontSize: 15 }}>✕</button>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 110 }}>
                <div style={{ fontSize: 10.5, color: "var(--muted)", marginBottom: 3 }}>{t("prod.buyPrice")}</div>
                <input value={r.cost} onChange={(e) => setRow(i, { cost: e.target.value.replace(/\D/g, "") })} inputMode="numeric" placeholder="0" style={{ ...inputStyle, height: 38, width: "100%", textAlign: "right" }} />
              </div>
              <div style={{ flex: 1, minWidth: 110 }}>
                <div style={{ fontSize: 10.5, color: "var(--muted)", marginBottom: 3 }}>{t("prod.sellPrice")}</div>
                <input value={r.sell} onChange={(e) => setRow(i, { sell: e.target.value.replace(/\D/g, "") })} inputMode="numeric" placeholder="0" style={{ ...inputStyle, height: 38, width: "100%", textAlign: "right" }} />
              </div>
              {isNew && (
                <div style={{ flex: 1.2, minWidth: 140 }}>
                  <div style={{ fontSize: 10.5, color: "var(--accent-ink)", marginBottom: 3 }}>{t("purch.newProd")}</div>
                  <select value={r.catId} onChange={(e) => setRow(i, { catId: e.target.value })} style={{ ...inputStyle, height: 38, width: "100%" }}>
                    <option value="">{t("prod.pickCategory")}</option>
                    {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </div>
              )}
              {prod && (
                <div className="tabular" style={{ fontSize: 12, fontWeight: 600, color: "var(--ok)", whiteSpace: "nowrap" }}>
                  {prod.stock} → {prod.stock + (+r.qty || 0)}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function buildItems(rows: KRow[]) {
  return rows
    .filter((r) => (r.pid || r.name.trim()) && +r.qty > 0)
    .map((r) => ({
      product_id: r.pid || null,
      new_name: r.pid ? null : r.name.trim(),
      new_sell_price: r.sell !== "" ? +r.sell : null,
      new_category_id: !r.pid && r.catId ? r.catId : null,
      qty: +r.qty,
      unit_cost: +r.cost || 0,
      ai_name: r.aiName || null,
      unit: r.unit || null,
    }));
}

// ── Qo'lda kirim: mavjudni tanla (narxlar avto) yoki yangi nom + kategoriya + narxlar ──
function PhotoKirim({ suppliers, onClose, onSaved }: { suppliers: Supplier[]; onClose: () => void; onSaved: () => void }) {
  const { data: products } = useGet<Product[]>("/products?include_archived=1");
  const { data: cats } = useGet<Category[]>("/categories");
  const [stage, setStage] = useState<"pick" | "scanning" | "review">("pick");
  const [rows, setRows] = useState<KRow[]>([]);
  const [supplier, setSupplier] = useState("");
  const [payment, setPayment] = useState<"cash" | "credit">("cash");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const imgRef = useRef<{ b64: string; media: string; source: string; aiRaw: unknown[] }>({ b64: "", media: "", source: "ai", aiRaw: [] });
  const fileRef = useRef<HTMLInputElement>(null);
  const t = useT();

  async function onFile(f: File | null) {
    if (!f) return;
    setErr("");
    const b64 = await new Promise<string>((res, rej) => {
      const rd = new FileReader();
      rd.onload = () => res(String(rd.result).split(",")[1] || "");
      rd.onerror = () => rej(new Error("read"));
      rd.readAsDataURL(f);
    });
    imgRef.current.b64 = b64;
    imgRef.current.media = f.type || "image/jpeg";
    setStage("scanning");
    try {
      const r = await post<{ source: string; items: { ai_name: string; qty: number; unit: string; product_id: string | null; matched_name: string | null; unit_cost: number }[]; ai_raw: unknown[] }>(
        "/receiving/scan", { image_b64: b64, media_type: imgRef.current.media });
      imgRef.current.source = r.source;
      imgRef.current.aiRaw = r.ai_raw || [];
      const prods = products || [];
      setRows((r.items || []).map((it) => {
        const p = it.product_id ? prods.find((x) => x.id === it.product_id) : undefined;
        return {
          pid: it.product_id || "", name: it.matched_name || it.ai_name,
          qty: String(it.qty || 1), cost: String(Math.round(it.unit_cost || 0) || ""),
          sell: p ? String(p.base_sell_price || "") : "", catId: "", open: false,
          aiName: it.ai_name, unit: it.unit,
        };
      }));
      setStage("review");
    } catch (e: any) { setErr(e.message); setStage("pick"); }
  }

  async function save() {
    const items = buildItems(rows);
    if (!items.length) { setErr(t("purch.errNeedItems")); return; }
    setBusy(true); setErr("");
    try {
      await post("/receiving/commit", {
        items, supplier_id: supplier || null, payment, source: imgRef.current.source,
        image_b64: imgRef.current.b64, ai_raw: imgRef.current.aiRaw,
        client_uuid: crypto.randomUUID(),
      });
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose} width={680}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 14 }}>📷 {t("purch.photoKirim")}</div>

      {stage === "pick" && (
        <div>
          <div onClick={() => fileRef.current?.click()}
            style={{ border: "2px dashed var(--accent-border)", borderRadius: 14, padding: "44px 20px", textAlign: "center", cursor: "pointer", background: "var(--surface)" }}>
            <div style={{ fontSize: 34, marginBottom: 8 }}>📸</div>
            <div style={{ fontWeight: 700, fontSize: 14.5 }}>{t("purch.pickPhoto")}</div>
            <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 5 }}>{t("purch.photoHint")}</div>
          </div>
          <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }}
            onChange={(e) => onFile(e.target.files?.[0] || null)} />
          {err && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 10 }}>{err}</div>}
        </div>
      )}

      {stage === "scanning" && (
        <div style={{ padding: "50px 0", textAlign: "center", color: "var(--muted)", fontSize: 14, fontWeight: 600 }}>{t("purch.scanning")}</div>
      )}

      {stage === "review" && (
        <div>
          <div style={{ display: "flex", gap: 12, marginBottom: 14 }}>
            <select value={supplier} onChange={(e) => setSupplier(e.target.value)} style={inputStyle}>
              <option value="">{t("purch.supplier")} —</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <select value={payment} onChange={(e) => setPayment(e.target.value as "cash" | "credit")} style={{ ...inputStyle, width: 160 }}>
              <option value="cash">{t("purch.paid")}</option>
              <option value="credit">{t("purch.statusDebt")}</option>
            </select>
          </div>
          <RowsEditor rows={rows} setRows={setRows} products={products || []} cats={cats || []} t={t} />
          <button onClick={() => setRows((r) => [...r, emptyRow()])} style={{ border: "1.5px dashed var(--accent-border)", background: "var(--surface)", borderRadius: 11, padding: "10px 16px", cursor: "pointer", fontWeight: 600, color: "var(--accent-ink)", marginTop: 10 }}>＋ {t("purch.addRow")}</button>
          {err && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 10 }}>{err}</div>}
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
            <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : t("purch.saveKirim")}</button>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ═══ YETKAZIB BERUVCHI BATAFSIL: qarz, yetkazgan mahsulotlar, xaridlar tarixi ═══
interface SupDetail {
  id: string; name: string; phone: string | null; balance: number;
  purchase_count: number; total_purchased: number; product_types: number;
  products: { name: string; qty: number; cost: number }[];
  recent_purchases: { id: string; doc_no: string; date: string; total: number; status: string }[];
}

function SupplierDetail({ id, onBack, onEdit, editModal }: { id: string; onBack: () => void; onEdit: () => void; editModal?: React.ReactNode }) {
  const t = useT();
  const detail = useGet<SupDetail>(`/suppliers/${id}`);
  const [payOpen, setPayOpen] = useState(false);
  const d = detail.data;

  return (
    <main className="main">
      <Topbar title={d ? d.name : "…"} sub={d?.phone || t("purch.supplier")}
        right={<div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn-ghost" onClick={onBack}>← {t("prod.back")}</button>
          <button className="btn btn-ghost" onClick={onEdit}>{t("cust.edit")}</button>
          {d && d.balance > 0 && <button className="btn btn-primary" onClick={() => setPayOpen(true)}>{t("purch.payDebt")}</button>}
        </div>} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {!d ? <div style={{ color: "var(--muted)" }}>{t("common.loading")}</div> : (
          <div style={{ maxWidth: 1000, display: "flex", flexDirection: "column", gap: 18 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.debt")}</div>
                <div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 6, color: d.balance > 0 ? "var(--danger)" : "var(--ok)" }}>{d.balance > 0 ? fmt(d.balance) : t("purch.clean")}</div></div>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.totalPurchased")}</div>
                <div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }}>{fmt(d.total_purchased)}</div></div>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.docs")}</div>
                <div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }}>{d.purchase_count}</div></div>
              <div className="card"><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("purch.productTypes")}</div>
                <div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }}>{d.product_types}</div></div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{ padding: "16px 20px 10px", fontSize: 15, fontWeight: 700 }}>{t("purch.deliveredProducts")}</div>
                <div style={{ maxHeight: 420, overflowY: "auto" }} className="no-sb">
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead><tr style={{ background: "var(--card-alt)" }}>
                      <th style={th}>{t("sales.thProduct")}</th><th style={{ ...th, textAlign: "right" }}>{t("recv.qty")}</th><th style={{ ...th, textAlign: "right" }}>{t("sales.thSum")}</th>
                    </tr></thead>
                    <tbody>
                      {d.products.map((p, i) => (
                        <tr key={i}>
                          <td style={{ ...td, fontWeight: 600 }}>{p.name}</td>
                          <td style={{ ...td, textAlign: "right" }} className="tabular">{p.qty}</td>
                          <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.cost)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {d.products.length === 0 && <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>{t("purch.noDeliveries")}</div>}
                </div>
              </div>

              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{ padding: "16px 20px 10px", fontSize: 15, fontWeight: 700 }}>{t("purch.purchaseHistory")}</div>
                <div style={{ maxHeight: 420, overflowY: "auto" }} className="no-sb">
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead><tr style={{ background: "var(--card-alt)" }}>
                      <th style={th}>{t("purch.thDoc")}</th><th style={th}>{t("purch.thDate")}</th><th style={{ ...th, textAlign: "right" }}>{t("sales.thSum")}</th><th style={th}></th>
                    </tr></thead>
                    <tbody>
                      {d.recent_purchases.map((p) => (
                        <tr key={p.id}>
                          <td style={{ ...td, fontWeight: 700 }}>{p.doc_no}</td>
                          <td style={{ ...td, color: "var(--muted)" }}>{p.date}</td>
                          <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.total)}</td>
                          <td style={td}><span style={{ fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 8, background: p.status === "debt" ? "var(--warn-soft)" : "var(--ok-soft)", color: p.status === "debt" ? "var(--warn)" : "var(--ok)" }}>{p.status === "debt" ? t("pay.credit") : t("purch.paid")}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {d.recent_purchases.length === 0 && <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>{t("purch.noKirim")}</div>}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
      {payOpen && d && <PayDebt supplierId={id} balance={d.balance} onClose={() => setPayOpen(false)} onDone={() => { setPayOpen(false); detail.reload(); }} />}
      {editModal}
    </main>
  );
}

function PayDebt({ supplierId, balance, onClose, onDone }: { supplierId: string; balance: number; onClose: () => void; onDone: () => void }) {
  const t = useT();
  const [amount, setAmount] = useState(String(Math.round(balance)));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  async function pay() {
    const a = +amount;
    if (!(a > 0)) { setErr(t("purch.enterAmount")); return; }
    setBusy(true); setErr("");
    try { await post(`/suppliers/${supplierId}/payments`, { amount: a, method: "cash", client_uuid: crypto.randomUUID() }); onDone(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <Modal onClose={onClose} width={380}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 4 }}>{t("purch.payDebt")}</div>
      <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 14 }}>{t("purch.debt")}: <b style={{ color: "var(--danger)" }}>{fmt(balance)}</b></div>
      <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} placeholder="0" style={{ ...inputStyle, textAlign: "right", fontSize: 18 }} />
      {err && <div style={{ color: "var(--danger)", fontSize: 13, marginTop: 8 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={pay}>{busy ? "..." : t("purch.pay")}</button>
      </div>
    </Modal>
  );
}

// ═══ YETKAZIB BERUVCHILAR — TO'LIQ SAHIFA (ro'yxat + qo'shish, bosilsa batafsil) ═══
function SuppliersPage({ suppliers, onBack, onOpen, onAdd, newSupModal }: {
  suppliers: Supplier[]; onBack: () => void; onOpen: (id: string) => void; onAdd: () => void; newSupModal: React.ReactNode;
}) {
  const t = useT();
  const [q, setQ] = useState("");
  const qq = q.trim().toLowerCase();
  const rows = suppliers.filter((s) => !qq || s.name.toLowerCase().includes(qq) || (s.phone || "").includes(qq));
  const totalDebt = suppliers.reduce((a, s) => a + (s.balance > 0 ? s.balance : 0), 0);

  return (
    <main className="main">
      <Topbar title={t("purch.suppliers")} sub={t("purch.suppliersSub")}
        right={<div style={{ display: "flex", gap: 10 }}>
          <button className="btn btn-ghost" onClick={onBack}>← {t("prod.back")}</button>
          <button className="btn btn-primary" onClick={onAdd}>＋ {t("purch.newSupplier")}</button>
        </div>} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ maxWidth: 1000 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 18, marginBottom: 18 }}>
            <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("purch.suppliers")}</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8 }}>{suppliers.length}</div></div>
            <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("purch.supplierDebt")}</div><div className="tabular" style={{ fontSize: 26, fontWeight: 800, marginTop: 8, color: totalDebt > 0 ? "var(--danger)" : "var(--ok)" }}>{fmt(totalDebt)}</div></div>
          </div>

          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("purch.searchSupplier")}
            style={{ ...inputStyle, marginBottom: 14, height: 46 }} />

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ background: "var(--card-alt)" }}>
                <th style={th}>{t("purch.name")}</th><th style={th}>{t("cust.thPhone")}</th><th style={{ ...th, textAlign: "right" }}>{t("purch.debt")}</th><th style={{ ...th, width: 40 }}></th>
              </tr></thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} onClick={() => onOpen(s.id)} style={{ cursor: "pointer" }}>
                    <td style={{ ...td, fontWeight: 600 }}>{s.name}</td>
                    <td style={{ ...td, color: "var(--text3)" }}>{s.phone || "—"}</td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 700, color: s.balance > 0 ? "var(--danger)" : "var(--ok)" }} className="tabular">{s.balance > 0 ? fmt(s.balance) : t("purch.clean")}</td>
                    <td style={{ ...td, textAlign: "center", color: "var(--faint)" }}>›</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>{t("purch.noSuppliers")}</div>}
          </div>
        </div>
      </div>
      {newSupModal}
    </main>
  );
}
