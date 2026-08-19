import { useState } from "react";
import { fmt } from "@/lib/format";
import { Modal, Stat, Topbar, useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";

interface Pnl { gross: number; discount: number; net: number; cogs: number; gross_profit: number; opex: number; net_profit: number; vat: number; margin: number; }
interface Top { name: string; qty: number; profit: number; }
interface Alerts { low_stock: number; loss_making: number; }

const PERIODS = [["today", "sales2.today"], ["week", "sales2.week"], ["month", "sales2.month"], ["all", "rep.periodAll"]];

export function Reports() {
  const [period, setPeriod] = useState("month");
  const pnl = useGet<Pnl>(`/reports/pnl?period=${period}`);
  const top = useGet<Top[]>(`/reports/top-products?period=${period}`);
  const alerts = useGet<Alerts>("/reports/alerts");
  const cats = useGet<{ name: string; sales: number; profit: number; margin: number }[]>(`/reports/categories?period=${period}`);
  const [alertModal, setAlertModal] = useState<"low" | "loss" | null>(null);
  const t = useT();
  const p = pnl.data;

  const rows = p ? [
    [t("rep.gross"), p.gross, false],
    [t("rep.discounts"), -p.discount, false],
    [t("rep.net"), p.net, true],
    [t("rep.cogs"), -p.cogs, false],
    [t("rep.grossProfit"), p.gross_profit, true],
    [t("rep.opex"), -p.opex, false],
  ] as [string, number, boolean][] : [];

  function exportCsv() {
    if (!p) return;
    const data: (string | number)[][] = [
      ["SavdoOS — " + t("rep.pnl"), period],
      [t("rep.gross"), Math.round(p.gross)],
      [t("rep.discounts"), -Math.round(p.discount)],
      [t("rep.net"), Math.round(p.net)],
      [t("rep.cogs"), -Math.round(p.cogs)],
      [t("rep.grossProfit"), Math.round(p.gross_profit)],
      [t("rep.opex"), -Math.round(p.opex)],
      [t("rep.netProfit"), Math.round(p.net_profit)],
      [t("rep.margin"), p.margin + "%"],
      [t("rep.vat12"), Math.round(p.vat)],
      ["", ""],
      [t("rep.topProducts"), t("rep.profit")],
      ...(top.data || []).map((tp) => [tp.name, Math.round(tp.profit)] as (string | number)[]),
    ];
    const csv = data.map((r) => r.join(";")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `hisobot_${period}.csv`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  return (
    <main className="main">
      <Topbar title={t("nav.hisobotlar")} sub={t("rep.sub")}
        right={
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <div style={{ display: "flex", gap: 6, background: "var(--surface)", borderRadius: 11, padding: 3 }}>
              {PERIODS.map(([k, l]) => (
                <button key={k} onClick={() => setPeriod(k)} style={{ height: 34, padding: "0 14px", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 13, fontWeight: 600, background: period === k ? "var(--card)" : "transparent", color: period === k ? "var(--accent-strong)" : "var(--muted)", boxShadow: period === k ? "0 1px 3px rgba(0,0,0,0.12)" : "none" }}>{t(l)}</button>
              ))}
            </div>
            <button className="btn btn-ghost" style={{ padding: "10px 16px" }} onClick={exportCsv}>📊 Excel</button>
          </div>
        } />

      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 18, marginBottom: 20 }}>
          <Stat label={t("rep.net")} value={p ? fmt(p.net) : "—"} />
          <Stat label={t("rep.netProfit")} value={p ? fmt(p.net_profit) : "—"} color="var(--green)" />
          <Stat label={t("rep.margin")} value={p ? p.margin + "%" : "—"} />
          <Stat label={t("rep.vat12")} value={p ? fmt(p.vat) : "—"} color="var(--warn)" />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 18 }}>
          <div className="card">
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>{t("rep.pnl")}</div>
            {rows.map(([label, val, bold], i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: bold ? "12px 0" : "8px 0", borderTop: bold ? "1px solid var(--border)" : "none" }}>
                <span style={{ fontSize: bold ? 14.5 : 13.5, fontWeight: bold ? 700 : 500, color: bold ? "var(--ink)" : "var(--text3)" }}>{label}</span>
                <span className="tabular" style={{ fontSize: bold ? 14.5 : 13.5, fontWeight: bold ? 700 : 500, color: val < 0 ? "var(--muted)" : "var(--text2)" }}>{val < 0 ? "−" : ""}{fmt(Math.abs(val))}</span>
              </div>
            ))}
            {p && (() => {
              const seg = [
                { label: t("rep.cost"), val: p.cogs, color: "var(--faint)" },
                { label: t("rep.expenses"), val: p.opex, color: "var(--warn)" },
                { label: t("pos.discount"), val: p.discount, color: "var(--border-input)" },
                p.net_profit >= 0
                  ? { label: t("rep.profit"), val: p.net_profit, color: "var(--ok)" }
                  : { label: t("rep.loss"), val: -p.net_profit, color: "var(--danger)" },
              ].filter((s) => s.val > 0);
              const g = Math.max(1, seg.reduce((acc, s) => acc + s.val, 0));
              return (
                <div style={{ marginTop: 18 }}>
                  <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 8 }}>{t("rep.whereEachSom")}</div>
                  <div style={{ display: "flex", height: 14, borderRadius: 7, overflow: "hidden", marginBottom: 8, background: "var(--surface)" }}>
                    {seg.map((s, i) => <div key={i} title={`${s.label}: ${fmt(s.val)}`} style={{ width: `${(s.val / g) * 100}%`, background: s.color }} />)}
                  </div>
                  <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                    {seg.map((s, i) => <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11.5, color: "var(--text3)" }}><span style={{ width: 9, height: 9, borderRadius: 3, background: s.color }} />{s.label} {Math.round((s.val / g) * 100)}%</span>)}
                  </div>
                </div>
              );
            })()}
            {p && (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16, padding: "18px 20px", borderRadius: 14, background: "var(--ok-soft)", border: "1px solid var(--ok-border)" }}>
                <div><div style={{ fontSize: 13, fontWeight: 600, color: "var(--ok)" }}>{t("rep.netProfit")}</div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{t("rep.marginLabel", { n: p.margin })}</div></div>
                <div style={{ fontSize: 30, fontWeight: 800, color: "var(--ok)" }} className="tabular">{fmt(p.net_profit)}</div>
              </div>
            )}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <div className="card">
              <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>{t("rep.topProducts")}</div>
              {(top.data || []).map((tp, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0" }}>
                  <div style={{ width: 24, height: 24, borderRadius: 7, background: i === 0 ? "var(--accent-soft)" : "var(--border)", color: i === 0 ? "var(--accent-ink)" : "var(--text3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700 }}>{i + 1}</div>
                  <div style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>{tp.name}</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ok)" }} className="tabular">{fmt(tp.profit)}</div>
                </div>
              ))}
              {(top.data || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("rep.noData")}</div>}
            </div>

            <div className="card">
              <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>{t("dash.attention")}</div>
              <button onClick={() => setAlertModal("low")} style={{ width: "100%", textAlign: "left", cursor: "pointer", border: "none", display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px", borderRadius: 11, background: "var(--warn-soft)", marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{t("dash.lowStock")}</span>
                <span style={{ fontSize: 16, fontWeight: 800, color: "var(--warn)" }}>{alerts.data?.low_stock ?? "—"} ›</span>
              </button>
              <button onClick={() => setAlertModal("loss")} style={{ width: "100%", textAlign: "left", cursor: "pointer", border: "none", display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px", borderRadius: 11, background: "var(--danger-soft)" }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{t("rep.lossSold")}</span>
                <span style={{ fontSize: 16, fontWeight: 800, color: "var(--danger)" }}>{alerts.data?.loss_making ?? "—"} ›</span>
              </button>
            </div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 18 }}>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>{t("rep.byCategory")}</div>
          {(cats.data || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("rep.noSalesPeriod")}</div>}
          {(cats.data || []).map((cc, i) => {
            const max = Math.max(1, ...(cats.data || []).map((x) => x.profit));
            return (
              <div key={i} style={{ marginBottom: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
                  <span style={{ fontWeight: 600 }}>{cc.name}{i === 0 && <span style={{ marginLeft: 8, fontSize: 10, fontWeight: 700, color: "var(--accent-ink)", background: "var(--accent-soft)", padding: "2px 7px", borderRadius: 6 }}>{t("rep.mostProfitable")}</span>}</span>
                  <span style={{ color: "var(--muted)" }}>{t("rep.salesLc")} {fmt(cc.sales)}</span>
                </div>
                <div style={{ height: 10, borderRadius: 5, background: "var(--border-soft)", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${Math.round((cc.profit / max) * 100)}%`, background: i === 0 ? "var(--accent)" : "var(--accent-border)", borderRadius: 5 }} />
                </div>
                <div style={{ fontSize: 12, color: "var(--text3)", marginTop: 6 }}>{t("rep.profitLc")} <b style={{ color: "var(--ok)" }}>{fmt(cc.profit)}</b> · {t("rep.marginLabel", { n: cc.margin })}</div>
              </div>
            );
          })}
        </div>
      </div>

      {alertModal && <AlertModal type={alertModal} onClose={() => setAlertModal(null)} />}
    </main>
  );
}

function AlertModal({ type, onClose }: { type: "low" | "loss"; onClose: () => void }) {
  const { data } = useGet<{ name: string; note: string; right: string }[]>(`/reports/alerts/detail?type=${type}`);
  const t = useT();
  return (
    <Modal onClose={onClose} width={520}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 4 }}>{type === "low" ? t("dash.lowStock") : t("rep.lossSold")}</div>
      <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 14 }}>{t("sales.pcs", { n: (data || []).length })}</div>
      <div style={{ maxHeight: "60vh", overflowY: "auto" }}>
        {(data || []).map((it, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "11px 0", borderTop: i ? "1px solid var(--surface)" : "none" }}>
            <div><div style={{ fontWeight: 600, fontSize: 13.5 }}>{it.name}</div><div style={{ fontSize: 12, color: "var(--muted)" }}>{it.note}</div></div>
            <div style={{ fontWeight: 700, color: "var(--danger)", whiteSpace: "nowrap" }}>{it.right}</div>
          </div>
        ))}
        {(data || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13, padding: 20, textAlign: "center" }}>{t("rep.empty")}</div>}
      </div>
      <button className="btn btn-primary" style={{ width: "100%", marginTop: 14, height: 46 }} onClick={onClose}>{t("common.close")}</button>
    </Modal>
  );
}
