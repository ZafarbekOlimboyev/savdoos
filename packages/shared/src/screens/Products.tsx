import { useMemo, useState } from "react";
import { api, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Modal, Stat, Topbar, inputStyle, td, th, useGet } from "@/components/ui";

interface Product { id: string; article_code: string; name: string; category_id: string | null; base_buy_price: number; base_sell_price: number; stock: number; }
interface Category { id: string; name: string }
interface Overview { total_products: number; low_count: number; out_count: number; moves_today: number; }

export function Products() {
  const products = useGet<Product[]>("/products");
  const cats = useGet<Category[]>("/categories");
  const ov = useGet<Overview>("/inventory/overview");
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const [add, setAdd] = useState(false);
  const [imp, setImp] = useState(false);
  const [edit, setEdit] = useState<Product | null>(null);

  const rows = useMemo(() => {
    const list = products.data || [];
    const qq = q.trim().toLowerCase();
    return list.filter(
      (p) =>
        (cat === "all" || p.category_id === cat) &&
        (!qq || p.name.toLowerCase().includes(qq) || p.article_code.includes(qq))
    );
  }, [products.data, q, cat]);

  const catName = (id: string | null) => (cats.data || []).find((c) => c.id === id)?.name || "—";

  return (
    <main className="main">
      <Topbar title="Mahsulotlar / Ombor" sub="Zaxira holati va katalog"
        right={
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn btn-ghost" onClick={() => setImp(true)}>📥 Import</button>
            <button className="btn btn-primary" onClick={() => setAdd(true)}>＋ Mahsulot qo'shish</button>
          </div>
        } />

      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 18, marginBottom: 20 }}>
          <Stat label="Jami mahsulot" value={ov.data?.total_products ?? "—"} />
          <Stat label="Kam qolgan" value={ov.data?.low_count ?? "—"} color="#b8730c" />
          <Stat label="Tugagan" value={ov.data?.out_count ?? "—"} color="var(--red)" />
          <Stat label="Bugungi harakatlar" value={ov.data?.moves_today ?? "—"} color="var(--accent)" />
        </div>

        <div style={{ display: "flex", gap: 12, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nomi yoki artikul..." style={{ ...inputStyle, width: 300 }} />
          {[{ id: "all", name: "Barchasi" }, ...(cats.data || [])].map((c) => {
            const on = cat === c.id;
            return (
              <button key={c.id} onClick={() => setCat(c.id)} style={{ height: 40, padding: "0 16px", borderRadius: 11, fontSize: 13, fontWeight: 600, cursor: "pointer", border: `1px solid ${on ? "var(--accent)" : "#e6e8f0"}`, background: on ? "var(--accent)" : "#fff", color: on ? "#fff" : "#5b6072" }}>{c.name}</button>
            );
          })}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "#f8f9fc" }}>
              <th style={th}>Mahsulot</th><th style={th}>Artikul</th><th style={th}>Kategoriya</th>
              <th style={{ ...th, textAlign: "right" }}>Kelish</th><th style={{ ...th, textAlign: "right" }}>Sotish</th>
              <th style={{ ...th, textAlign: "right" }}>Qoldiq</th><th style={th}>Holat</th>
            </tr></thead>
            <tbody>
              {rows.map((p) => {
                const out = p.stock <= 0, low = p.stock > 0 && p.stock <= 5;
                const st = out ? ["Tugagan", "#fdecec", "#c93a3e"] : low ? ["Kam qoldi", "#fef3e2", "#b8730c"] : ["Faol", "#e9f7ef", "#12915a"];
                return (
                  <tr key={p.id} onClick={() => setEdit(p)} style={{ cursor: "pointer" }}>
                    <td style={{ ...td, fontWeight: 600 }}>{p.name}</td>
                    <td style={{ ...td, color: "#5b6072" }} className="tabular">{p.article_code}</td>
                    <td style={{ ...td, color: "#5b6072" }}>{catName(p.category_id)}</td>
                    <td style={{ ...td, textAlign: "right", color: "#5b6072" }} className="tabular">{fmt(p.base_buy_price)}</td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(p.base_sell_price)}</td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 600, color: out ? "#c93a3e" : low ? "#e5484d" : "#3a3f52" }} className="tabular">{p.stock}</td>
                    <td style={td}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 11px", borderRadius: 9, background: st[1], color: st[2] }}>{st[0]}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>Mahsulot topilmadi</div>}
        </div>
      </div>

      {add && <AddModal cats={cats.data || []} onClose={() => setAdd(false)} onSaved={() => { setAdd(false); products.reload(); ov.reload(); }} />}
      {edit && <EditModal product={edit} cats={cats.data || []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); products.reload(); ov.reload(); }} />}
      {imp && <ImportWizard onClose={() => setImp(false)} onDone={() => { setImp(false); products.reload(); ov.reload(); }} />}
    </main>
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

  const ST: Record<string, [string, string, string]> = { new: ["Yangi", "#e9f7ef", "#12915a"], existing: ["Mavjud", "#eef0f5", "#8b91a4"], error: ["Xato", "#fdecec", "#c93a3e"] };

  return (
    <Modal onClose={onClose} width={560}>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, fontSize: 12.5, fontWeight: 700 }}>
        <span style={{ color: step >= 1 ? "var(--accent-ink)" : "#9aa0b4" }}>1 · Fayl</span>›
        <span style={{ color: step >= 2 ? "var(--accent-ink)" : "#9aa0b4" }}>2 · Tekshirish</span>›
        <span style={{ color: step >= 3 ? "var(--accent-ink)" : "#9aa0b4" }}>3 · Import</span>
      </div>

      {step === 1 && (
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>Excel / CSV / 1C import</div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 12 }}>Har qator: <b>nom;kategoriya;kelish;sotish;qoldiq;barcode</b> (nuqtali vergul bilan)</div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={SAMPLE} style={{ width: "100%", height: 160, padding: 12, border: "1.5px solid #e2e4ee", borderRadius: 11, fontSize: 13, fontFamily: "monospace", outline: "none", boxSizing: "border-box", resize: "vertical" }} />
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
            {[["Jami", preview.total, "#5b6072"], ["Yangi", preview.new, "#12915a"], ["Mavjud", preview.existing, "#8b91a4"], ["Xato", preview.error, "#c93a3e"]].map(([l, v, c]) => (
              <div key={l as string} style={{ background: "#f7f8fb", borderRadius: 12, padding: 12, textAlign: "center" }}>
                <div style={{ fontSize: 20, fontWeight: 800, color: c as string }}>{v as number}</div>
                <div style={{ fontSize: 11.5, color: "#8b91a4" }}>{l as string}</div>
              </div>
            ))}
          </div>
          <div style={{ maxHeight: 220, overflowY: "auto", border: "1px solid #eef0f5", borderRadius: 12 }}>
            {preview.sample.map((r, i) => {
              const st = ST[r.status] || ["?", "#eee", "#555"];
              return (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", borderTop: i ? "1px solid #f4f5f9" : "none", fontSize: 13 }}>
                  <span style={{ fontWeight: 600 }}>{r.name}</span>
                  <span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 8, background: st[1], color: st[2] }}>{st[0]}</span>
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
          <div style={{ fontSize: 44 }}>✅</div>
          <div style={{ fontSize: 20, fontWeight: 800, marginTop: 8 }}>Import yakunlandi</div>
          <div style={{ fontSize: 13.5, color: "var(--muted)", marginTop: 6 }}>{imported} ta yangi mahsulot qo'shildi</div>
          <button className="btn btn-primary" style={{ width: "100%", marginTop: 20, height: 48 }} onClick={onDone}>Katalogni ochish</button>
        </div>
      )}
    </Modal>
  );
}

function EditModal({ product, cats, onClose, onSaved }: { product: Product; cats: Category[]; onClose: () => void; onSaved: () => void }) {
  const detail = useGet<{ created_by_name: string; created_at: string }>(`/products/${product.id}`);
  const [name, setName] = useState(product.name);
  const [cat, setCat] = useState(product.category_id || "");
  const [buy, setBuy] = useState(String(product.base_buy_price));
  const [sell, setSell] = useState(String(product.base_sell_price));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    setBusy(true); setErr("");
    try {
      await api(`/products/${product.id}`, { method: "PATCH", body: JSON.stringify({ name, category_id: cat || null, buy_price: +buy || 0, sell_price: +sell || 0 }) });
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function del() {
    if (!window.confirm(`"${product.name}" o'chirilsinmi?`)) return;
    setBusy(true); setErr("");
    try { await api(`/products/${product.id}`, { method: "DELETE" }); onSaved(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 4 }}>Mahsulotni tahrirlash</div>
      <div style={{ fontSize: 12.5, color: "var(--muted)" }} className="tabular">{product.article_code}</div>
      {detail.data && (
        <div style={{ fontSize: 12.5, color: "var(--muted)", margin: "6px 0 16px", padding: "8px 12px", background: "#f7f8fb", borderRadius: 9 }}>
          👤 Qo'shgan: <b style={{ color: "#3a3f52" }}>{detail.data.created_by_name}</b>{detail.data.created_at ? ` · ${new Date(detail.data.created_at).toLocaleDateString("ru-RU")}` : ""}
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} />
        <select value={cat} onChange={(e) => setCat(e.target.value)} style={inputStyle}>
          {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <div style={{ display: "flex", gap: 10 }}>
          <input value={buy} onChange={(e) => setBuy(e.target.value.replace(/\D/g, ""))} placeholder="Kelish" style={inputStyle} />
          <input value={sell} onChange={(e) => setSell(e.target.value.replace(/\D/g, ""))} placeholder="Sotish" style={inputStyle} />
        </div>
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn" style={{ background: "#fdecec", color: "#c93a3e", padding: "0 16px" }} disabled={busy} onClick={del}>🗑 O'chirish</button>
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
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    if (!name.trim()) return;
    setBusy(true); setErr("");
    try {
      await post("/products/bulk", { items: [{ name, category_id: cat || null, buy_price: +buy || 0, sell_price: +sell || 0, stock: +stock || 0 }] });
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>Yangi mahsulot</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input placeholder="Nomi" value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} />
        <select value={cat} onChange={(e) => setCat(e.target.value)} style={{ ...inputStyle }}>
          {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <div style={{ display: "flex", gap: 10 }}>
          <input placeholder="Kelish narxi" value={buy} onChange={(e) => setBuy(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
          <input placeholder="Sotish narxi" value={sell} onChange={(e) => setSell(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
        </div>
        <input placeholder="Boshlang'ich qoldiq" value={stock} onChange={(e) => setStock(e.target.value.replace(/\D/g, ""))} style={inputStyle} />
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>Bekor</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : "Saqlash"}</button>
      </div>
    </Modal>
  );
}
