import { useRef, useState } from "react";
import { ArrowUUpLeft, DownloadSimple, Printer, Receipt, X } from "@phosphor-icons/react";
import { get } from "@/lib/api";
import { fmt } from "@/lib/format";
import { printReceipt } from "@/lib/receipt";
import { readPrefs } from "@/lib/prefs";
import { Topbar, inputStyle, td, th, useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";

interface Row { id: string; receipt_no: string; sold_at: string; cashier: string; method: string; item_count: number; first_item: string; total: number; }
interface Detail { id: string; receipt_no: string; uid?: string | null; total: number; sold_at: string; items: { name_snapshot: string; qty: number; unit_price: number; line_total: number }[]; }

const M: Record<string, [string, string, string]> = {
  cash: ["Naqd", "var(--ok-soft)", "var(--ok)"], card: ["Karta", "var(--accent-soft)", "var(--accent-strong)"],
  qr: ["QR", "var(--info-soft)", "#3b82f6"], credit: ["Qarz", "var(--warn-soft)", "var(--warn)"],
};
const PERIODS = [["today", "Bugun"], ["week", "Hafta"], ["month", "Oy"]];

export function Sales() {
  const t = useT();
  const prefs = readPrefs();
  const [period, setPeriod] = useState("today");
  const [method, setMethod] = useState("all");
  const [cashier, setCashier] = useState("all");
  const [q, setQ] = useState("");
  const cashiers = useGet<string[]>("/sales/cashiers");
  const path = `/sales?limit=300&period=${period}${method !== "all" ? `&method=${method}` : ""}${cashier !== "all" ? `&cashier=${encodeURIComponent(cashier)}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`;
  const { data, err } = useGet<Row[]>(path);
  const summaryPath = `/sales/summary?period=${period}${method !== "all" ? `&method=${method}` : ""}${cashier !== "all" ? `&cashier=${encodeURIComponent(cashier)}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`;
  const summary = useGet<{ count: number; total: number }>(summaryPath);
  const [sel, setSel] = useState<{ d: Detail; row: Row } | null>(null);

  const lastOpenId = useRef("");
  async function open(row: Row) {
    lastOpenId.current = row.id;
    try {
      const d = await get<Detail>(`/sales/${row.id}`);
      if (lastOpenId.current === row.id) setSel({ d, row });
    } catch { /* ignore */ }
  }

  const rows = data || [];
  const totalSum = rows.reduce((t, r) => t + r.total, 0);

  const chips: [string, string][] = [["all", "Barchasi"], ["cash", "Naqd"], ...(prefs.karta ? [["card", "Karta"]] as [string, string][] : []), ...(prefs.qr ? [["qr", "QR"]] as [string, string][] : []), ...(prefs.qarz ? [["credit", "Qarz"]] as [string, string][] : [])];

  function exportCsv() {
    const head = [t("sales.receipt"), t("sales.thTime"), t("sales2.thCashier"), t("sales.thPay"), t("sales.thSum")];
    const lines = rows.map((r) => [r.receipt_no, new Date(r.sold_at).toLocaleString("ru-RU"), r.cashier, (M[r.method] ? t("pay." + r.method) : r.method), String(Math.round(r.total))]);
    const csv = "﻿" + [head, ...lines].map((row) => row.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url; a.download = `sotuvlar_${period}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="main">
      <Topbar title={t("nav.sotuvlar")} sub={t("sales2.sub")} right={
        <button className="btn btn-ghost" style={{ display: "flex", alignItems: "center", gap: 7 }} onClick={exportCsv}>
          <DownloadSimple size={17} />{t("sales2.exportExcel")}
        </button>
      } />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {/* Period segmented control */}
        <div style={{ display: "inline-flex", gap: 2, padding: 3, borderRadius: 12, border: "1px solid var(--border)", background: "var(--card)", marginBottom: 14 }}>
          {PERIODS.map(([k, l]) => {
            const on = period === k;
            return <button key={k} onClick={() => setPeriod(k)} style={{ height: 34, padding: "0 18px", borderRadius: 9, border: "none", cursor: "pointer", font: "inherit", fontSize: 13, fontWeight: 600, background: on ? "var(--surface)" : "transparent", color: on ? "var(--accent-strong)" : "var(--text3)" }}>{t("sales2." + k)}</button>;
          })}
        </div>

        <div style={{ display: "flex", gap: 10, marginBottom: 6, alignItems: "center", flexWrap: "wrap" }}>
          {chips.map(([k, l]) => {
            const on = method === k;
            return <button key={k} onClick={() => setMethod(k)} style={{ height: 40, padding: "0 15px", borderRadius: 11, fontSize: 13, fontWeight: 600, cursor: "pointer", border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`, background: on ? "var(--accent)" : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>{k === "all" ? t("pos.all") : t("pay." + k)}</button>;
          })}
          <select value={cashier} onChange={(e) => setCashier(e.target.value)} style={{ ...inputStyle, width: 180, height: 40 }}>
            <option value="all">{t("sales2.allCashiers")}</option>
            {(cashiers.data || []).map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("sales.searchReceipt")} style={{ ...inputStyle, width: 200, height: 40 }} />
        </div>
        <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14 }}>
          <b style={{ color: "var(--text2)" }}>{summary.data?.count ?? rows.length}</b> {t("sales2.salesWord")} · {t("sales2.totalWord")} <b style={{ color: "var(--text2)" }}>{fmt(summary.data?.total ?? totalSum)}</b>
        </div>

        {err && <div style={{ color: "var(--red)", marginBottom: 12 }}>{err}</div>}

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ background: "var(--card-alt)" }}>
                <th style={th}>{t("sales.receipt")}</th><th style={th}>{t("sales.thTime")}</th><th style={th}>{t("sales2.thCashier")}</th>
                <th style={th}>{t("sales.thProduct")}</th><th style={th}>{t("sales.thPay")}</th><th style={{ ...th, textAlign: "right" }}>{t("sales.thSum")}</th>
              </tr></thead>
              <tbody>
                {rows.map((r) => {
                  const m = M[r.method] || [r.method, "var(--surface)", "var(--muted)"];
                  return (
                    <tr key={r.id} onClick={() => open(r)} style={{ cursor: "pointer" }}>
                      <td style={{ ...td, fontWeight: 700 }}>{r.receipt_no}</td>
                      <td style={{ ...td, color: "var(--muted)" }}>{new Date(r.sold_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</td>
                      <td style={td}>
                        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                          <div style={{ width: 26, height: 26, flex: "none", borderRadius: "50%", background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700 }}>{(r.cashier || "?").charAt(0)}</div>
                          <span style={{ color: "var(--text2)" }}>{r.cashier}</span>
                        </div>
                      </td>
                      <td style={{ ...td, color: "var(--text3)" }}>{t("sales.pcs", { n: r.item_count })}{r.first_item ? ` (${r.first_item}${r.item_count > 1 ? ", …" : ""})` : ""}</td>
                      <td style={td}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: m[1], color: m[2] }}>{M[r.method] ? t("pay." + r.method) : r.method}</span></td>
                      <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(r.total)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {rows.length === 0 && (
            <div style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>
              <Receipt size={34} color="var(--faint)" /><div style={{ marginTop: 8 }}>{t("sales2.notFound")}</div>
            </div>
          )}
        </div>
      </div>

      {sel && (
        <div onClick={() => setSel(null)} style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.55)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ width: 428, background: "var(--card)", borderRadius: 20, padding: 26, boxShadow: "0 24px 60px rgba(0,0,0,0.4)", maxHeight: "92vh", overflowY: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 18, fontWeight: 800 }}>{t("sales.receipt")} {sel.d.receipt_no}</div>
                <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>{sel.row.cashier} · {new Date(sel.d.sold_at).toLocaleString("ru-RU")}</div>
              </div>
              <button onClick={() => setSel(null)} style={{ border: "none", background: "var(--surface)", borderRadius: 9, width: 34, height: 34, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={16} /></button>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {sel.d.items.map((it, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5 }}>
                  <div><div style={{ fontWeight: 600 }}>{it.name_snapshot}</div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{it.qty} × {fmt(it.unit_price)}</div></div>
                  <div style={{ fontWeight: 700 }} className="tabular">{fmt(it.line_total)}</div>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 14, paddingTop: 14, borderTop: "1px dashed var(--border-input)", fontSize: 13.5, color: "var(--text3)" }}>
              <span>{t("sales2.payMethod")}</span>
              <span style={{ fontWeight: 600, color: (M[sel.row.method] || ["", "", "var(--text)"])[2] }}>{M[sel.row.method] ? t("pay." + sel.row.method) : sel.row.method}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, paddingTop: 14, borderTop: "1px dashed var(--border-input)" }}>
              <span style={{ fontSize: 14, fontWeight: 700 }}>{t("pos.total")}</span>
              <span style={{ fontSize: 24, fontWeight: 800 }} className="tabular">{fmt(sel.d.total)}</span>
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
              <button className="btn btn-ghost" style={{ flex: 1, height: 46, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
                onClick={() => printReceipt({ receipt_no: sel.d.receipt_no, offline: false, store: prefs.storeName, branch: prefs.branchName, cashier: sel.row.cashier, items: sel.d.items.map((it) => ({ name: it.name_snapshot, qty: it.qty, price: it.unit_price, line: it.line_total })), total: sel.d.total, method: sel.row.method, given: 0, change: 0, date: new Date(sel.d.sold_at).toLocaleString("ru-RU") })}>
                <Printer size={17} />{t("sales2.print")}
              </button>
              {prefs.returns && (
                <a href="#/qaytarishlar" className="btn" style={{ flex: 1, height: 46, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, border: "1.5px solid var(--danger-border)", background: "var(--card)", color: "var(--danger)", textDecoration: "none" }}>
                  <ArrowUUpLeft size={17} />{t("sales2.doReturn")}
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
