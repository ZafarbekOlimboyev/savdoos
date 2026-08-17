import { useEffect, useState } from "react";
import { api, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Modal, Topbar, inputStyle, td, th, useGet } from "@/components/ui";

interface Customer { id: string; code: string; full_name: string; phone: string | null; credit_balance: number; }

export function Customers() {
  const [q, setQ] = useState("");
  const [onlyDebt, setOnlyDebt] = useState(false);
  const path = `/customers?${onlyDebt ? "only_debt=true&" : ""}${q ? `q=${encodeURIComponent(q)}` : ""}`;
  const { data, err, reload } = useGet<Customer[]>(path);
  const [pay, setPay] = useState<Customer | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const rows = data || [];
  const totalDebt = rows.reduce((t, c) => t + c.credit_balance, 0);
  const debtors = rows.filter((c) => c.credit_balance > 0).length;

  return (
    <main className="main">
      <Topbar title="Mijozlar" sub="Mijozlar bazasi va nasiya hisobi" />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18, marginBottom: 20 }}>
          <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>Jami mijozlar</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8 }}>{rows.length}</div></div>
          <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>Qarzdorlar</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8, color: "#b8730c" }}>{debtors}</div></div>
          <div className="card"><div style={{ fontSize: 13, color: "var(--muted)" }}>Umumiy qarz</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 8, color: "var(--red)" }} className="tabular">{fmt(totalDebt)}</div></div>
        </div>

        <div style={{ display: "flex", gap: 12, marginBottom: 14 }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ism yoki telefon..." style={{ ...inputStyle, width: 320 }} />
          <button onClick={() => setOnlyDebt((v) => !v)} style={{ height: 44, padding: "0 16px", borderRadius: 11, fontSize: 13, fontWeight: 600, cursor: "pointer", border: `1px solid ${onlyDebt ? "var(--accent)" : "#e6e8f0"}`, background: onlyDebt ? "var(--accent-soft)" : "#fff", color: onlyDebt ? "var(--accent-ink)" : "#5b6072" }}>Faqat qarzdorlar</button>
        </div>

        {err && <div style={{ color: "var(--red)", marginBottom: 12 }}>{err}</div>}

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "#f8f9fc" }}>
              <th style={th}>Mijoz</th><th style={th}>ID</th><th style={th}>Telefon</th>
              <th style={{ ...th, textAlign: "right" }}>Qarz</th><th style={{ ...th, textAlign: "right" }}></th>
            </tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} onClick={() => setDetailId(c.id)} style={{ cursor: "pointer" }}>
                  <td style={{ ...td, fontWeight: 600 }}>{c.full_name}</td>
                  <td style={{ ...td, color: "#8b91a4" }}>{c.code}</td>
                  <td style={{ ...td, color: "#8b91a4" }} className="tabular">{c.phone}</td>
                  <td style={{ ...td, textAlign: "right", fontWeight: 700, color: c.credit_balance > 0 ? "#c93a3e" : "#c7cbd9" }} className="tabular">{c.credit_balance > 0 ? fmt(c.credit_balance) : "—"}</td>
                  <td style={{ ...td, textAlign: "right" }}>
                    {c.credit_balance > 0 && <button className="btn" style={{ background: "var(--green)", color: "#fff", padding: "8px 14px", fontSize: 13 }} onClick={(e) => { e.stopPropagation(); setPay(c); }}>Qarzni yopish</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>Mijoz topilmadi</div>}
        </div>
      </div>

      {pay && <PayModal c={pay} onClose={() => setPay(null)} onDone={() => { setPay(null); reload(); }} />}
      {detailId && <CustomerDetail id={detailId} onClose={() => setDetailId(null)} onChanged={reload} />}
    </main>
  );
}

interface Detail {
  full_name: string; phone: string | null; credit_balance: number; total_spent: number; visits: number;
  history: { date: string; items: number; amount: number; method: string }[];
  payments: { date: string; amount: number }[];
}

function CustomerDetail({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const { data } = useGet<Detail>(`/customers/${id}/detail`);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { if (data) { setName(data.full_name); setPhone(data.phone || ""); } }, [data]);

  async function save() {
    setBusy(true); setErr("");
    try { await api(`/customers/${id}`, { method: "PATCH", body: JSON.stringify({ full_name: name, phone }) }); onChanged(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function del() {
    if (!window.confirm(`"${name}" o'chirilsinmi?`)) return;
    setBusy(true); setErr("");
    try { await api(`/customers/${id}`, { method: "DELETE" }); onChanged(); onClose(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose} width={460}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 12 }}>Mijoz kartasi</div>
      <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ism" style={inputStyle} />
        <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Telefon" style={inputStyle} />
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 18 }}>
        <div style={{ flex: 1, background: "#f7f8fb", borderRadius: 12, padding: 14 }}><div style={{ fontSize: 11.5, color: "#8b91a4" }}>Umumiy xarid</div><div style={{ fontSize: 17, fontWeight: 700, marginTop: 3 }} className="tabular">{data ? fmt(data.total_spent) : "—"}</div></div>
        <div style={{ flex: 1, background: data && data.credit_balance > 0 ? "#fdecec" : "#e9f7ef", borderRadius: 12, padding: 14 }}><div style={{ fontSize: 11.5, color: "#8b91a4" }}>Joriy qarz</div><div style={{ fontSize: 17, fontWeight: 700, marginTop: 3, color: data && data.credit_balance > 0 ? "#c93a3e" : "#12915a" }} className="tabular">{data ? fmt(data.credit_balance) : "—"}</div></div>
      </div>

      {(data?.payments || []).length > 0 && (
        <>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#5b6072", marginBottom: 8 }}>Qarz to'lovlari</div>
          {data!.payments.map((p, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "5px 0" }}>
              <span style={{ color: "#5b6072" }}>↓ {new Date(p.date).toLocaleDateString("ru-RU")}</span>
              <span style={{ fontWeight: 700, color: "#12915a" }}>+{fmt(p.amount)}</span>
            </div>
          ))}
        </>
      )}

      <div style={{ fontSize: 13, fontWeight: 700, color: "#5b6072", margin: "14px 0 8px" }}>So'nggi xaridlar</div>
      {(data?.history || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>Hali xarid yo'q</div>}
      {(data?.history || []).map((h, i) => (
        <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "6px 0", borderTop: i ? "1px solid #f4f5f9" : "none" }}>
          <div><div style={{ fontWeight: 500 }}>{new Date(h.date).toLocaleDateString("ru-RU")}</div><div style={{ fontSize: 11.5, color: "#9aa0b4" }}>{h.items} ta · {h.method}</div></div>
          <div style={{ fontWeight: 700 }} className="tabular">{fmt(h.amount)}</div>
        </div>
      ))}
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <button className="btn" style={{ background: "#fdecec", color: "#c93a3e", padding: "0 16px" }} disabled={busy} onClick={del}>🗑</button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-ghost" onClick={onClose}>Yopish</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "..." : "Saqlash"}</button>
      </div>
    </Modal>
  );
}

function PayModal({ c, onClose, onDone }: { c: Customer; onClose: () => void; onDone: () => void }) {
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const amt = parseInt(amount.replace(/\D/g, ""), 10) || 0;

  async function confirm() {
    if (amt <= 0) return;
    setBusy(true); setErr("");
    try { await post(`/customers/${c.id}/payments`, { amount: amt, method: "cash" }); onDone(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose} width={400}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>Qarzni yopish</div>
      <div style={{ textAlign: "center", padding: "16px 0", background: "#fdecec", borderRadius: 13, marginBottom: 18 }}>
        <div style={{ fontSize: 12, color: "#8b91a4", fontWeight: 600 }}>{c.full_name} · joriy qarz</div>
        <div style={{ fontSize: 28, fontWeight: 800, color: "#c93a3e", marginTop: 3 }} className="tabular">{fmt(c.credit_balance)}</div>
      </div>
      <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} placeholder="To'lov summasi" style={{ ...inputStyle, height: 52, fontSize: 20, fontWeight: 700 }} />
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button className="btn btn-ghost" style={{ flex: 1, padding: 10 }} onClick={() => setAmount(String(Math.round(c.credit_balance / 2)))}>Yarmi</button>
        <button className="btn btn-ghost" style={{ flex: 1, padding: 10 }} onClick={() => setAmount(String(c.credit_balance))}>To'liq</button>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 14px", borderRadius: 11, background: "#f7f8fb", marginTop: 12 }}>
        <span style={{ fontSize: 13, color: "#8b91a4" }}>To'lovdan keyin</span>
        <span style={{ fontSize: 16, fontWeight: 800 }} className="tabular">{fmt(Math.max(0, c.credit_balance - amt))}</span>
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>Bekor</button>
        <button className="btn" style={{ flex: 1, background: "var(--green)", color: "#fff" }} disabled={busy} onClick={confirm}>{busy ? "..." : "Qabul qilish"}</button>
      </div>
    </Modal>
  );
}
