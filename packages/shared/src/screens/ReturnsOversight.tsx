import { useState } from "react";
import { fmt } from "@/lib/format";
import { Topbar, td, th, useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";

// Ega/menejer NAZORATI: qabul qilingan qaytarishlar tarixi (faqat ko'rish).
// Qaytarishni QABUL QILISH — POS (kassir) ishi. Bu yerda nimalar qaytganini kuzatasiz.
interface RetItem { name: string; qty: number }
interface RetRow {
  id: string; return_no: string; at: string; cashier: string | null; receipt_no: string | null;
  reason: string; refund_method: string; total: number; restock: boolean; items: RetItem[];
}
interface Resp { kpi: { count: number; total: number; restocked: number; writeoff: number }; returns: RetRow[] }

const PERIODS = [["today", "branch.period.today"], ["week", "branch.period.week"], ["month", "branch.period.month"], ["all", "pos.all"]];

function tm(s: string): string {
  const d = new Date(s);
  return isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function ReturnsOversight() {
  const [period, setPeriod] = useState("month");
  const { data, err } = useGet<Resp>(`/returns?period=${period}`);
  const t = useT();
  const rows = data?.returns || [];
  const k = data?.kpi;

  const kpi = [
    { label: t("returns.kpiCount"), value: String(k?.count ?? 0), color: "var(--text)" },
    { label: t("returns.kpiTotal"), value: fmt(k?.total ?? 0), color: "var(--danger)" },
    { label: t("returns.kpiRestocked"), value: String(k?.restocked ?? 0), color: "var(--ok)" },
    { label: t("returns.kpiWriteoff"), value: String(k?.writeoff ?? 0), color: "var(--warn)" },
  ];

  return (
    <main className="main">
      <Topbar title={t("nav.qaytarishlar")} sub={t("returns.oversightSub")} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {err && <div style={{ color: "var(--red)", marginBottom: 12 }}>{err}</div>}

        <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
          {PERIODS.map(([k2, lbl]) => {
            const on = period === k2;
            return <button key={k2} onClick={() => setPeriod(k2)} style={{ height: 36, padding: "0 15px", borderRadius: 10, fontSize: 13, fontWeight: 600, cursor: "pointer", border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`, background: on ? "var(--accent)" : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>{t(lbl)}</button>;
          })}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 18 }}>
          {kpi.map((x) => (
            <div key={x.label} className="card" style={{ padding: "15px 18px" }}>
              <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{x.label}</div>
              <div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 6, color: x.color }}>{x.value}</div>
            </div>
          ))}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--card-alt)" }}>
                <th style={th}>{t("returns.thReturnNo")}</th>
                <th style={th}>{t("returns.thDate")}</th>
                <th style={th}>{t("returns.thCashier")}</th>
                <th style={th}>{t("returns.thReceipt")}</th>
                <th style={th}>{t("returns.thItems")}</th>
                <th style={th}>{t("returns.thReason")}</th>
                <th style={th}>{t("returns.thMethod")}</th>
                <th style={{ ...th, textAlign: "right" }}>{t("returns.thRefund")}</th>
                <th style={th}>{t("returns.thRestock")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td style={{ ...td, color: "var(--muted)" }} colSpan={9}>{t("returns.noReturns")}</td></tr>
              )}
              {rows.map((r) => (
                <tr key={r.id}>
                  <td style={{ ...td, fontWeight: 600 }}>{r.return_no}</td>
                  <td style={{ ...td, color: "var(--text3)" }} className="tabular">{tm(r.at)}</td>
                  <td style={{ ...td, color: "var(--text3)" }}>{r.cashier || "—"}</td>
                  <td style={{ ...td, color: "var(--text3)" }}>{r.receipt_no || "—"}</td>
                  <td style={{ ...td, color: "var(--text3)", maxWidth: 220, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {r.items.map((it) => `${it.name} ×${it.qty}`).join(", ") || "—"}
                  </td>
                  <td style={td}><span style={{ fontSize: 12 }}>{t("returns.reason_" + r.reason)}</span></td>
                  <td style={{ ...td, color: "var(--text3)" }}>{t("pay." + r.refund_method)}</td>
                  <td style={{ ...td, textAlign: "right", fontWeight: 700, color: "var(--danger)" }} className="tabular">−{fmt(r.total)}</td>
                  <td style={td}>
                    <span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 11px", borderRadius: 9, background: r.restock ? "var(--ok-soft)" : "var(--warn-soft)", color: r.restock ? "var(--ok)" : "var(--warn)" }}>
                      {r.restock ? t("returns.restockYes") : t("returns.restockNo")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
