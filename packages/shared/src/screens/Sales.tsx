import { useState } from "react";
import { get } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Modal, Topbar, inputStyle, td, th, useGet } from "@/components/ui";

interface Row { id: string; receipt_no: string; sold_at: string; cashier: string; method: string; item_count: number; total: number; }
interface Detail { id: string; receipt_no: string; total: number; items: { name_snapshot: string; qty: number; unit_price: number; line_total: number }[]; }

const M: Record<string, [string, string, string]> = {
  cash: ["Naqd", "#e9f7ef", "#12915a"], card: ["Karta", "#efedfb", "#5a4bc4"],
  qr: ["QR", "#eaf3ff", "#2b6cb0"], credit: ["Qarz", "#fef3e2", "#b8730c"],
};

export function Sales() {
  const [method, setMethod] = useState("all");
  const [cashier, setCashier] = useState("all");
  const [q, setQ] = useState("");
  const cashiers = useGet<string[]>("/sales/cashiers");
  const path = `/sales?limit=100${method !== "all" ? `&method=${method}` : ""}${cashier !== "all" ? `&cashier=${encodeURIComponent(cashier)}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`;
  const { data, err } = useGet<Row[]>(path);
  const [sel, setSel] = useState<Detail | null>(null);

  async function open(id: string) {
    try { setSel(await get<Detail>(`/sales/${id}`)); } catch { /* ignore */ }
  }

  const rows = data || [];
  const totalSum = rows.reduce((t, r) => t + r.total, 0);

  return (
    <main className="main">
      <Topbar title="Sotuvlar" sub="Barcha savdolar tarixi" />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
          {[["all", "Barchasi"], ["cash", "Naqd"], ["card", "Karta"], ["qr", "QR"], ["credit", "Qarz"]].map(([k, l]) => {
            const on = method === k;
            return <button key={k} onClick={() => setMethod(k)} style={{ height: 40, padding: "0 15px", borderRadius: 11, fontSize: 13, fontWeight: 600, cursor: "pointer", border: `1px solid ${on ? "var(--accent)" : "#e6e8f0"}`, background: on ? "var(--accent)" : "#fff", color: on ? "#fff" : "#5b6072" }}>{l}</button>;
          })}
          <select value={cashier} onChange={(e) => setCashier(e.target.value)} style={{ ...inputStyle, width: 180, height: 40 }}>
            <option value="all">Barcha kassirlar</option>
            {(cashiers.data || []).map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Chek raqami..." style={{ ...inputStyle, width: 200, height: 40 }} />
          <div style={{ marginLeft: "auto", fontSize: 13, color: "var(--muted)" }}>
            <b style={{ color: "#3a3f52" }}>{rows.length}</b> ta savdo · jami <b style={{ color: "#3a3f52" }}>{fmt(totalSum)}</b>
          </div>
        </div>

        {err && <div style={{ color: "var(--red)", marginBottom: 12 }}>{err}</div>}

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "#f8f9fc" }}>
              <th style={th}>Chek</th><th style={th}>Vaqt</th><th style={th}>Kassir</th>
              <th style={{ ...th, textAlign: "right" }}>Mahsulot</th><th style={th}>To'lov</th><th style={{ ...th, textAlign: "right" }}>Summa</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => {
                const m = M[r.method] || [r.method, "#eee", "#555"];
                return (
                  <tr key={r.id} onClick={() => open(r.id)} style={{ cursor: "pointer" }}>
                    <td style={{ ...td, fontWeight: 700 }}>{r.receipt_no}</td>
                    <td style={{ ...td, color: "#8b91a4" }}>{new Date(r.sold_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</td>
                    <td style={{ ...td, color: "#3a3f52" }}>{r.cashier}</td>
                    <td style={{ ...td, textAlign: "right", color: "#5b6072" }} className="tabular">{r.item_count}</td>
                    <td style={td}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: m[1], color: m[2] }}>{m[0]}</span></td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(r.total)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>Savdo topilmadi</div>}
        </div>
      </div>

      {sel && (
        <Modal onClose={() => setSel(null)} width={420}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
            <div style={{ fontSize: 18, fontWeight: 800 }}>Chek {sel.receipt_no}</div>
            <button onClick={() => setSel(null)} style={{ border: "none", background: "#f5f6fa", borderRadius: 9, width: 34, height: 34, cursor: "pointer" }}>✕</button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {sel.items.map((it, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5 }}>
                <div><div style={{ fontWeight: 600 }}>{it.name_snapshot}</div><div style={{ fontSize: 11.5, color: "#9aa0b4" }}>{it.qty} × {fmt(it.unit_price)}</div></div>
                <div style={{ fontWeight: 700 }} className="tabular">{fmt(it.line_total)}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 16, paddingTop: 16, borderTop: "1px dashed #e2e4ee" }}>
            <span style={{ fontSize: 14, fontWeight: 700 }}>JAMI</span>
            <span style={{ fontSize: 24, fontWeight: 800 }} className="tabular">{fmt(sel.total)}</span>
          </div>
        </Modal>
      )}
    </main>
  );
}
