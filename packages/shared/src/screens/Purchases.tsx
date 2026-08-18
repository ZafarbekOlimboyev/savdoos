import { useState } from "react";
import { api, get, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Modal, Topbar, inputStyle, td, th, useGet } from "@/components/ui";

interface Purchase { id: string; doc_no: string; supplier: string; date: string; total: number; status: string; }
interface Supplier { id: string; name: string; phone: string | null; balance: number; }
interface Product { id: string; name: string; base_buy_price: number; stock: number; }

export function Purchases() {
  const purchases = useGet<Purchase[]>("/purchases");
  const suppliers = useGet<Supplier[]>("/suppliers");
  const [add, setAdd] = useState(false);
  const [editSup, setEditSup] = useState<Supplier | null>(null);
  const [newSup, setNewSup] = useState(false);

  const list = purchases.data || [];
  const sup = suppliers.data || [];
  const debt = sup.reduce((t, s) => t + s.balance, 0);

  return (
    <main className="main">
      <Topbar title="Xaridlar" sub="Yetkazib beruvchilar va kirim hujjatlari"
        right={<button className="btn btn-primary" onClick={() => setAdd(true)}>＋ Yangi kirim</button>} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18, marginBottom: 20 }}>
          <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>Kirim hujjatlari</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8 }}>{list.length}</div></div>
          <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>Yetkazib beruvchilar</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8 }}>{sup.length}</div></div>
          <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>Beruvchiga qarz</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8, color: "var(--red)" }} className="tabular">{fmt(debt)}</div></div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 18 }}>
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "18px 20px 12px", fontSize: 16, fontWeight: 700 }}>Kirim hujjatlari</div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ background: "var(--card-alt)" }}><th style={th}>Hujjat</th><th style={th}>Beruvchi</th><th style={th}>Sana</th><th style={{ ...th, textAlign: "right" }}>Summa</th><th style={th}>Holat</th></tr></thead>
              <tbody>
                {list.map((p) => (
                  <tr key={p.id}>
                    <td style={{ ...td, fontWeight: 700 }}>{p.doc_no}</td>
                    <td style={{ ...td, color: "var(--text2)" }}>{p.supplier}</td>
                    <td style={{ ...td, color: "var(--muted)" }}>{p.date}</td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.total)}</td>
                    <td style={td}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: p.status === "debt" ? "var(--warn-soft)" : "var(--ok-soft)", color: p.status === "debt" ? "var(--warn)" : "var(--ok)" }}>{p.status === "debt" ? "Qarz" : "To'langan"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.length === 0 && <div style={{ padding: 30, textAlign: "center", color: "var(--muted)" }}>Hozircha kirim yo'q</div>}
          </div>

          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <div style={{ fontSize: 16, fontWeight: 700 }}>Yetkazib beruvchilar</div>
              <button onClick={() => setNewSup(true)} style={{ border: "none", background: "none", color: "var(--accent)", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>＋ Qo'shish</button>
            </div>
            {sup.map((s) => (
              <div key={s.id} onClick={() => setEditSup(s)} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderTop: "1px solid var(--surface)", cursor: "pointer" }}>
                <div><div style={{ fontSize: 13.5, fontWeight: 600 }}>{s.name}</div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{s.phone}</div></div>
                <div style={{ fontSize: 13, fontWeight: 700, color: s.balance > 0 ? "var(--danger)" : "var(--ok)" }} className="tabular">{s.balance > 0 ? fmt(s.balance) : "Toza"}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {add && <AddKirim suppliers={sup} onClose={() => setAdd(false)} onSaved={() => { setAdd(false); purchases.reload(); suppliers.reload(); }} />}
      {editSup && <SupplierEdit s={editSup} onClose={() => setEditSup(null)} onDone={() => { setEditSup(null); suppliers.reload(); }} />}
      {newSup && <SupplierNew onClose={() => setNewSup(false)} onDone={() => { setNewSup(false); suppliers.reload(); }} />}
    </main>
  );
}

function SupplierEdit({ s, onClose, onDone }: { s: Supplier; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(s.name);
  const [phone, setPhone] = useState(s.phone || "");
  const [busy, setBusy] = useState(false);
  async function save() { setBusy(true); try { await api(`/suppliers/${s.id}`, { method: "PATCH", body: JSON.stringify({ name, phone }) }); onDone(); } finally { setBusy(false); } }
  async function del() { if (!window.confirm(`"${s.name}" o'chirilsinmi?`)) return; setBusy(true); try { await api(`/suppliers/${s.id}`, { method: "DELETE" }); onDone(); } finally { setBusy(false); } }
  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>Yetkazib beruvchi</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nomi" style={inputStyle} />
        <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Telefon" style={inputStyle} />
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn" style={{ background: "var(--danger-soft)", color: "var(--danger)", padding: "0 16px" }} disabled={busy} onClick={del}>🗑</button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-ghost" onClick={onClose}>Bekor</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "..." : "Saqlash"}</button>
      </div>
    </Modal>
  );
}

function SupplierNew({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  async function save() { if (!name.trim()) return; setBusy(true); try { await post("/suppliers", { name, phone }); onDone(); } finally { setBusy(false); } }
  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>Yangi yetkazib beruvchi</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nomi" style={inputStyle} />
        <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Telefon" style={inputStyle} />
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>Bekor</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : "Qo'shish"}</button>
      </div>
    </Modal>
  );
}

function AddKirim({ suppliers, onClose, onSaved }: { suppliers: Supplier[]; onClose: () => void; onSaved: () => void }) {
  const { data: products } = useGet<Product[]>("/products");
  const [supplier, setSupplier] = useState(suppliers[0]?.id || "");
  const [status, setStatus] = useState("received");
  const [rows, setRows] = useState<{ product_id: string; qty: string; cost: string }[]>([{ product_id: "", qty: "", cost: "" }]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const setRow = (i: number, k: string, v: string) => setRows((r) => r.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  const total = rows.reduce((t, r) => t + (+r.qty || 0) * (+r.cost || 0), 0);

  async function save() {
    const items = rows.filter((r) => r.product_id && +r.qty > 0).map((r) => ({ product_id: r.product_id, qty: +r.qty, unit_cost: +r.cost || 0 }));
    if (!items.length || !supplier) { setErr("Beruvchi va kamida bitta mahsulot kerak"); return; }
    setBusy(true); setErr("");
    try { await post("/purchases", { supplier_id: supplier, status, items }); onSaved(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose} width={640}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>Yangi kirim</div>
      <div style={{ display: "flex", gap: 12, marginBottom: 14 }}>
        <select value={supplier} onChange={(e) => setSupplier(e.target.value)} style={inputStyle}>
          {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ ...inputStyle, width: 160 }}>
          <option value="received">To'langan</option>
          <option value="debt">Qarzga</option>
        </select>
      </div>
      {rows.map((r, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "2fr 0.7fr 0.9fr 1.1fr 30px", gap: 8, marginBottom: 8, alignItems: "center" }}>
          <select value={r.product_id} onChange={(e) => setRow(i, "product_id", e.target.value)} style={{ ...inputStyle, height: 42 }}>
            <option value="">Mahsulot...</option>
            {(products || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <input placeholder="Soni" value={r.qty} onChange={(e) => setRow(i, "qty", e.target.value.replace(/\D/g, ""))} style={{ ...inputStyle, height: 42, textAlign: "right" }} />
          <input placeholder="Narx" value={r.cost} onChange={(e) => setRow(i, "cost", e.target.value.replace(/\D/g, ""))} style={{ ...inputStyle, height: 42, textAlign: "right" }} />
          <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ok)", textAlign: "center" }} className="tabular">
            {(() => { const prod = (products || []).find((p) => p.id === r.product_id); return prod ? `${prod.stock} → ${prod.stock + (+r.qty || 0)}` : "—"; })()}
          </div>
          <button onClick={() => setRows((rr) => rr.filter((_, j) => j !== i))} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--faint)" }}>✕</button>
        </div>
      ))}
      <button onClick={() => setRows((r) => [...r, { product_id: "", qty: "", cost: "" }])} style={{ border: "1.5px dashed var(--accent-border)", background: "var(--surface)", borderRadius: 11, padding: "10px 16px", cursor: "pointer", fontWeight: 600, color: "var(--accent-ink)", marginTop: 4 }}>＋ Qator qo'shish</button>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border-soft)" }}>
        <div>{err && <span style={{ color: "var(--red)", fontSize: 13 }}>{err}</span>}</div>
        <div style={{ fontSize: 24, fontWeight: 800 }} className="tabular">{fmt(total)}</div>
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>Bekor</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : "Kirimni saqlash"}</button>
      </div>
    </Modal>
  );
}
