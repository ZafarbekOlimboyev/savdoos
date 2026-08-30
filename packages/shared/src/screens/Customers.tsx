import { useRef, useState } from "react";
import { ArrowDown, MagnifyingGlass, PencilSimple, Plus, Trash, User, UserPlus, X } from "@phosphor-icons/react";
import { api, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { readPrefs } from "@/lib/prefs";
import { Modal, Topbar, inputStyle, td, th, useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";

interface Customer { id: string; code: string; full_name: string; phone: string | null; credit_balance: number; }

export function Customers() {
  const t = useT();
  const prefs = readPrefs();
  const [q, setQ] = useState("");
  const [onlyDebt, setOnlyDebt] = useState(false);
  const path = `/customers?${onlyDebt ? "only_debt=true&" : ""}${q ? `q=${encodeURIComponent(q)}` : ""}`;
  const { data, err, reload } = useGet<Customer[]>(path);
  const [selId, setSelId] = useState<string | null>(null);
  const [pay, setPay] = useState<Customer | null>(null);
  const [payVer, setPayVer] = useState(0); // to'lovdan keyin panel tarixini yangilash
  const [add, setAdd] = useState(false);

  const rows = data || [];
  const totalDebt = rows.reduce((t, c) => t + c.credit_balance, 0);
  const debtors = rows.filter((c) => c.credit_balance > 0).length;
  const sel = rows.find((c) => c.id === selId) || null;

  return (
    <main className="main">
      <Topbar title={t("nav.mijozlar")} sub={t("cust.subDb")} right={
        <button className="btn btn-primary" style={{ display: "flex", alignItems: "center", gap: 7 }} onClick={() => setAdd(true)}>
          <UserPlus size={17} />{t("pos.newCustomer")}
        </button>
      } />
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <div className="scroll" style={{ flex: 1, padding: 24 }}>
          <div style={{ display: "grid", gridTemplateColumns: prefs.qarz ? "repeat(3,1fr)" : "repeat(2,1fr)", gap: 16, marginBottom: 18 }}>
            <div className="card" style={{ padding: "15px 18px" }}><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("cust.totalCustomers")}</div><div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }}>{rows.length}</div></div>
            {prefs.qarz && <div className="card" style={{ padding: "15px 18px" }}><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("cust.debtors")}</div><div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 6, color: "var(--warn)" }}>{debtors}</div></div>}
            {prefs.qarz && <div className="card" style={{ padding: "15px 18px" }}><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("cust.totalDebt")}</div><div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 6, color: "var(--danger)" }}>{fmt(totalDebt)}</div></div>}
          </div>

          <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
            <div style={{ flex: 1, minWidth: 240, position: "relative" }}>
              <MagnifyingGlass size={17} color="var(--muted)" style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)" }} />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("cust.searchPlaceholder")} style={{ width: "100%", height: 44, padding: "0 14px 0 40px", border: "1px solid var(--border-input)", borderRadius: 12, background: "var(--surface)", color: "var(--text)", font: "inherit", fontSize: 14, outline: "none" }} />
            </div>
            {prefs.qarz && <button onClick={() => setOnlyDebt((v) => !v)} style={{ height: 44, padding: "0 16px", borderRadius: 11, fontSize: 13, fontWeight: 600, cursor: "pointer", border: `1px solid ${onlyDebt ? "var(--accent)" : "var(--border)"}`, background: onlyDebt ? "var(--accent-soft)" : "var(--card)", color: onlyDebt ? "var(--accent-strong)" : "var(--text3)" }}>{t("cust.onlyDebtors")}</button>}
          </div>

          {err && <div style={{ color: "var(--red)", marginBottom: 12 }}>{err}</div>}

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ background: "var(--card-alt)" }}>
                <th style={th}>{t("cust.thCustomer")}</th><th style={th}>ID</th><th style={th}>{t("cust.thPhone")}</th>
                {prefs.qarz && <th style={{ ...th, textAlign: "right" }}>{t("cust.thDebt")}</th>}
              </tr></thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} onClick={() => setSelId(c.id)} style={{ cursor: "pointer", background: selId === c.id ? "var(--surface)" : undefined }}>
                    <td style={td}>
                      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                        <div style={{ width: 34, height: 34, flex: "none", borderRadius: "50%", background: c.credit_balance > 0 ? "var(--danger-soft)" : "var(--accent-soft)", color: c.credit_balance > 0 ? "var(--danger)" : "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700 }}>{c.full_name.charAt(0)}</div>
                        <span style={{ fontWeight: 600 }}>{c.full_name}</span>
                      </div>
                    </td>
                    <td style={{ ...td, color: "var(--muted)" }} className="tabular">{c.code}</td>
                    <td style={{ ...td, color: "var(--muted)" }} className="tabular">{c.phone || "—"}</td>
                    {prefs.qarz && <td style={{ ...td, textAlign: "right", fontWeight: 700, color: c.credit_balance > 0 ? "var(--danger)" : "var(--faint)" }} className="tabular">{c.credit_balance > 0 ? fmt(c.credit_balance) : "—"}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>{t("pos.custNotFound")}</div>}
          </div>
        </div>

        {sel && <CustomerPanel key={`${sel.id}:${payVer}`} customer={sel} showDebt={prefs.qarz} onClose={() => setSelId(null)} onPay={() => setPay(sel)} onChanged={reload} />}
      </div>

      {pay && <PayModal c={pay} onClose={() => setPay(null)} onDone={() => { setPay(null); reload(); setPayVer((v) => v + 1); }} />}
      {add && <AddModal onClose={() => setAdd(false)} onSaved={() => { setAdd(false); reload(); }} />}
    </main>
  );
}

interface Detail {
  full_name: string; phone: string | null; credit_balance: number; total_spent: number; visits: number;
  history: { date: string; items: number; amount: number; method: string }[];
  payments: { date: string; amount: number }[];
}

function CustomerPanel({ customer, showDebt, onClose, onPay, onChanged }: { customer: Customer; showDebt: boolean; onClose: () => void; onPay: () => void; onChanged: () => void }) {
  const t = useT();
  const { data } = useGet<Detail>(`/customers/${customer.id}/detail`);
  const [editing, setEditing] = useState(false);
  const [panelErr, setPanelErr] = useState("");
  const [name, setName] = useState(customer.full_name);
  const [phone, setPhone] = useState(customer.phone || "");
  const [busy, setBusy] = useState(false);
  const debt = customer.credit_balance;

  async function save() {
    setBusy(true);
    try { await api(`/customers/${customer.id}`, { method: "PATCH", body: JSON.stringify({ full_name: name, phone }) }); setEditing(false); onChanged(); }
    catch (e: any) { setPanelErr(e?.message || t("common.error")); } finally { setBusy(false); }
  }
  async function del() {
    if (!window.confirm(t("cust.deleteConfirm", { name: customer.full_name }))) return;
    try { await api(`/customers/${customer.id}`, { method: "DELETE" }); onChanged(); onClose(); } catch (e: any) { setPanelErr(e?.message || t("common.error")); }
  }

  return (
    <aside style={{ width: 380, flex: "none", borderLeft: "1px solid var(--border)", background: "var(--card)", display: "flex", flexDirection: "column", overflowY: "auto" }}>
      <div style={{ padding: "20px 22px", display: "flex", alignItems: "flex-start", gap: 14 }}>
        <div style={{ width: 52, height: 52, flex: "none", borderRadius: "50%", background: debt > 0 ? "var(--danger-soft)" : "var(--accent-soft)", color: debt > 0 ? "var(--danger)" : "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, fontWeight: 800 }}>{customer.full_name.charAt(0)}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          {editing ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <input value={name} onChange={(e) => setName(e.target.value)} style={{ ...inputStyle, height: 38 }} />
              <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder={t("cust.thPhone")} style={{ ...inputStyle, height: 38 }} />
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-primary" style={{ padding: "6px 14px", fontSize: 13 }} disabled={busy} onClick={save}>{t("common.save")}</button>
                <button className="btn btn-ghost" style={{ padding: "6px 14px", fontSize: 13 }} onClick={() => setEditing(false)}>{t("common.cancel")}</button>
              </div>
            </div>
          ) : (
            <>
              <div style={{ fontSize: 18, fontWeight: 800 }}>{customer.full_name}</div>
              <div className="tabular" style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>{customer.code} · {customer.phone || t("cust.noPhone")}</div>
            </>
          )}
        </div>
        {!editing && <button onClick={onClose} style={{ width: 32, height: 32, border: "none", background: "var(--surface)", borderRadius: 9, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={16} /></button>}
      </div>

      {showDebt && (
        <div style={{ padding: "0 22px" }}>
          <div style={{ background: debt > 0 ? "var(--danger-soft)" : "var(--ok-soft)", borderRadius: 14, padding: "16px 18px", textAlign: "center" }}>
            <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600 }}>{t("cust.currentDebt")}</div>
            <div className="tabular" style={{ fontSize: 30, fontWeight: 800, marginTop: 4, color: debt > 0 ? "var(--danger)" : "var(--ok)" }}>{fmt(debt)}</div>
          </div>
          {debt > 0 && <button className="btn" style={{ width: "100%", marginTop: 12, height: 46, background: "var(--ok)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }} onClick={onPay}><ArrowDown size={17} weight="bold" />{t("cust.closeDebt")}</button>}
        </div>
      )}

      <div style={{ padding: "16px 22px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div style={{ background: "var(--surface)", borderRadius: 12, padding: 14 }}><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{t("cust.totalSpent")}</div><div className="tabular" style={{ fontSize: 17, fontWeight: 800, marginTop: 3 }}>{data ? fmt(data.total_spent) : "…"}</div></div>
        <div style={{ background: "var(--surface)", borderRadius: 12, padding: 14 }}><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{t("cust.visits")}</div><div className="tabular" style={{ fontSize: 17, fontWeight: 800, marginTop: 3 }}>{data ? data.visits : "…"}</div></div>
      </div>

      {showDebt && (data?.payments || []).length > 0 && (
        <div style={{ padding: "0 22px 8px" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text3)", marginBottom: 6 }}>{t("cust.debtPayments")}</div>
          {data!.payments.map((p, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "6px 0" }}>
              <span style={{ color: "var(--text3)" }}>{new Date(p.date).toLocaleDateString("ru-RU")}</span>
              <span style={{ fontWeight: 700, color: "var(--ok)" }}>+{fmt(p.amount)}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{ padding: "8px 22px 12px" }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text3)", marginBottom: 6 }}>{t("cust.recentPurchases")}</div>
        {(data?.history || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("cust.noPurchases")}</div>}
        {(data?.history || []).map((h, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "7px 0", borderTop: i ? "1px solid var(--border-soft)" : "none" }}>
            <div><div style={{ fontWeight: 500 }}>{new Date(h.date).toLocaleDateString("ru-RU")}</div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{t("sales.pcs", { n: h.items })} · {["cash", "card", "qr", "credit"].includes(h.method) ? t("pay." + h.method) : h.method}</div></div>
            <div className="tabular" style={{ fontWeight: 700 }}>{fmt(h.amount)}</div>
          </div>
        ))}
      </div>

      {panelErr && <div style={{ padding: "0 22px 8px", color: "var(--danger)", fontSize: 12.5 }}>{panelErr}</div>}
      {!editing && (
        <div style={{ padding: "8px 22px 22px", marginTop: "auto", display: "flex", gap: 10 }}>
          <button className="btn btn-ghost" style={{ flex: 1, height: 44, display: "flex", alignItems: "center", justifyContent: "center", gap: 7 }} onClick={() => setEditing(true)}><PencilSimple size={16} />{t("cust.edit")}</button>
          <button className="btn" style={{ width: 44, height: 44, background: "var(--danger-soft)", color: "var(--danger)", display: "flex", alignItems: "center", justifyContent: "center" }} onClick={del}><Trash size={16} /></button>
        </div>
      )}
    </aside>
  );
}

function AddModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const t = useT();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    if (!name.trim()) return;
    setBusy(true); setErr("");
    try { await post("/customers", { full_name: name, phone: phone || null }); onSaved(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose} width={400}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <div style={{ width: 40, height: 40, borderRadius: 11, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center" }}><User size={20} weight="fill" /></div>
        <div style={{ fontSize: 18, fontWeight: 800 }}>{t("pos.newCustomer")}</div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input placeholder={t("cust.fullName")} value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} />
        <input placeholder={t("pos.phonePlaceholder")} value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" style={inputStyle} />
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : t("common.add")}</button>
      </div>
    </Modal>
  );
}

function PayModal({ c, onClose, onDone }: { c: Customer; onClose: () => void; onDone: () => void }) {
  const t = useT();
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const amt = parseInt(amount.replace(/\D/g, ""), 10) || 0;
  // Barqaror idempotentlik kaliti (bitta modal = bitta to'lov) — qayta bosilса server ikki marta
  // qarзни kamaytirмасин (ux_custpay_client_uuid).
  const payUuid = useRef(crypto.randomUUID());

  async function confirm() {
    if (amt <= 0) return;
    setBusy(true); setErr("");
    try { await post(`/customers/${c.id}/payments`, { amount: amt, method: "cash", client_uuid: payUuid.current }); onDone(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose} width={400}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>{t("cust.closeDebt")}</div>
      <div style={{ textAlign: "center", padding: "16px 0", background: "var(--danger-soft)", borderRadius: 13, marginBottom: 18 }}>
        <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600 }}>{c.full_name} · {t("cust.currentDebtShort")}</div>
        <div className="tabular" style={{ fontSize: 28, fontWeight: 800, color: "var(--danger)", marginTop: 3 }}>{fmt(c.credit_balance)}</div>
      </div>
      <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} placeholder={t("pay.amount")} style={{ ...inputStyle, height: 52, fontSize: 20, fontWeight: 700 }} />
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button className="btn btn-ghost" style={{ flex: 1, padding: 10 }} onClick={() => setAmount(String(Math.round(c.credit_balance / 2)))}>{t("cust.half")}</button>
        <button className="btn btn-ghost" style={{ flex: 1, padding: 10 }} onClick={() => setAmount(String(Math.round(c.credit_balance)))}>{t("cust.full")}</button>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 14px", borderRadius: 11, background: "var(--surface)", marginTop: 12 }}>
        <span style={{ fontSize: 13, color: "var(--muted)" }}>{t("cust.afterPayment")}</span>
        <span className="tabular" style={{ fontSize: 16, fontWeight: 800 }}>{fmt(Math.max(0, c.credit_balance - amt))}</span>
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn" style={{ flex: 1, background: "var(--ok)", color: "#fff" }} disabled={busy} onClick={confirm}>{busy ? "..." : t("cust.accept")}</button>
      </div>
    </Modal>
  );
}
