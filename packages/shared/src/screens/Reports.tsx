import { useState } from "react";
import { fmt } from "@/lib/format";
import { Modal, Stat, Topbar, useGet } from "@/components/ui";

interface Pnl { gross: number; discount: number; net: number; cogs: number; gross_profit: number; opex: number; net_profit: number; vat: number; margin: number; }
interface Top { name: string; qty: number; profit: number; }
interface Alerts { low_stock: number; loss_making: number; }

const PERIODS = [["today", "Bugun"], ["week", "Hafta"], ["month", "Oy"], ["all", "Butun"]];

export function Reports() {
  const [period, setPeriod] = useState("month");
  const pnl = useGet<Pnl>(`/reports/pnl?period=${period}`);
  const top = useGet<Top[]>(`/reports/top-products?period=${period}`);
  const alerts = useGet<Alerts>("/reports/alerts");
  const cats = useGet<{ name: string; sales: number; profit: number; margin: number }[]>(`/reports/categories?period=${period}`);
  const [alertModal, setAlertModal] = useState<"low" | "loss" | null>(null);
  const p = pnl.data;

  const rows = p ? [
    ["Yalpi savdo", p.gross, false],
    ["Chegirmalar", -p.discount, false],
    ["Sof tushum", p.net, true],
    ["Sotilgan tovar tannarxi", -p.cogs, false],
    ["Yalpi foyda", p.gross_profit, true],
    ["Operatsion xarajatlar", -p.opex, false],
  ] as [string, number, boolean][] : [];

  function exportCsv() {
    if (!p) return;
    const data: (string | number)[][] = [
      ["SavdoOS — Foyda va zarar", period],
      ["Yalpi savdo", Math.round(p.gross)],
      ["Chegirmalar", -Math.round(p.discount)],
      ["Sof tushum", Math.round(p.net)],
      ["Sotilgan tovar tannarxi", -Math.round(p.cogs)],
      ["Yalpi foyda", Math.round(p.gross_profit)],
      ["Operatsion xarajatlar", -Math.round(p.opex)],
      ["Sof foyda", Math.round(p.net_profit)],
      ["Foyda marjasi", p.margin + "%"],
      ["QQS (12%)", Math.round(p.vat)],
      ["", ""],
      ["Eng foydali mahsulotlar", "Foyda"],
      ...(top.data || []).map((t) => [t.name, Math.round(t.profit)] as (string | number)[]),
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
      <Topbar title="Hisobotlar" sub="Moliyaviy natijalar"
        right={
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <div style={{ display: "flex", gap: 6, background: "#f2f3f7", borderRadius: 11, padding: 3 }}>
              {PERIODS.map(([k, l]) => (
                <button key={k} onClick={() => setPeriod(k)} style={{ height: 34, padding: "0 14px", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 13, fontWeight: 600, background: period === k ? "#fff" : "transparent", color: period === k ? "var(--ink)" : "#8b91a4", boxShadow: period === k ? "0 1px 3px rgba(28,31,43,0.12)" : "none" }}>{l}</button>
              ))}
            </div>
            <button className="btn btn-ghost" style={{ padding: "10px 16px" }} onClick={exportCsv}>📊 Excel</button>
          </div>
        } />

      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 18, marginBottom: 20 }}>
          <Stat label="Sof tushum" value={p ? fmt(p.net) : "—"} />
          <Stat label="Sof foyda" value={p ? fmt(p.net_profit) : "—"} color="var(--green)" />
          <Stat label="Foyda marjasi" value={p ? p.margin + "%" : "—"} />
          <Stat label="QQS (12%)" value={p ? fmt(p.vat) : "—"} color="#b8730c" />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 18 }}>
          <div className="card">
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>Foyda va zarar</div>
            {rows.map(([label, val, bold], i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: bold ? "12px 0" : "8px 0", borderTop: bold ? "1px solid #eef0f5" : "none" }}>
                <span style={{ fontSize: bold ? 14.5 : 13.5, fontWeight: bold ? 700 : 500, color: bold ? "var(--ink)" : "#6b7183" }}>{label}</span>
                <span className="tabular" style={{ fontSize: bold ? 14.5 : 13.5, fontWeight: bold ? 700 : 500, color: val < 0 ? "#8b91a4" : "#3a3f52" }}>{val < 0 ? "−" : ""}{fmt(Math.abs(val))}</span>
              </div>
            ))}
            {p && (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16, padding: "18px 20px", borderRadius: 14, background: "linear-gradient(180deg,#effaf3,#e7f6ee)", border: "1px solid #d3ecdd" }}>
                <div><div style={{ fontSize: 13, fontWeight: 600, color: "#12915a" }}>Sof foyda</div><div style={{ fontSize: 11.5, color: "#5b9578" }}>marja {p.margin}%</div></div>
                <div style={{ fontSize: 30, fontWeight: 800, color: "#0f7a4d" }} className="tabular">{fmt(p.net_profit)}</div>
              </div>
            )}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <div className="card">
              <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Eng foydali mahsulotlar</div>
              {(top.data || []).map((t, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0" }}>
                  <div style={{ width: 24, height: 24, borderRadius: 7, background: i === 0 ? "var(--accent-soft)" : "#eef0f5", color: i === 0 ? "var(--accent-ink)" : "#5b6072", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700 }}>{i + 1}</div>
                  <div style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>{t.name}</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#12915a" }} className="tabular">{fmt(t.profit)}</div>
                </div>
              ))}
              {(top.data || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>Ma'lumot yo'q</div>}
            </div>

            <div className="card">
              <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Diqqat talab qiladi</div>
              <button onClick={() => setAlertModal("low")} style={{ width: "100%", textAlign: "left", cursor: "pointer", border: "none", display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px", borderRadius: 11, background: "#fff8ef", marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>Kam qoldiqdagi mahsulotlar</span>
                <span style={{ fontSize: 16, fontWeight: 800, color: "#b8730c" }}>{alerts.data?.low_stock ?? "—"} ›</span>
              </button>
              <button onClick={() => setAlertModal("loss")} style={{ width: "100%", textAlign: "left", cursor: "pointer", border: "none", display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px", borderRadius: 11, background: "#fdf2f2" }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>Zarar bilan sotilgan</span>
                <span style={{ fontSize: 16, fontWeight: 800, color: "#c93a3e" }}>{alerts.data?.loss_making ?? "—"} ›</span>
              </button>
            </div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 18 }}>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>Kategoriyalar bo'yicha (foyda)</div>
          {(cats.data || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>Bu davrda savdo yo'q</div>}
          {(cats.data || []).map((cc, i) => {
            const max = Math.max(1, ...(cats.data || []).map((x) => x.profit));
            return (
              <div key={i} style={{ marginBottom: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
                  <span style={{ fontWeight: 600 }}>{cc.name}{i === 0 && <span style={{ marginLeft: 8, fontSize: 10, fontWeight: 700, color: "var(--accent-ink)", background: "var(--accent-soft)", padding: "2px 7px", borderRadius: 6 }}>Eng foydali</span>}</span>
                  <span style={{ color: "var(--muted)" }}>savdo {fmt(cc.sales)}</span>
                </div>
                <div style={{ height: 10, borderRadius: 5, background: "#f1f2f7", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${Math.round((cc.profit / max) * 100)}%`, background: i === 0 ? "var(--accent)" : "#b9b1e8", borderRadius: 5 }} />
                </div>
                <div style={{ fontSize: 12, color: "#6b7183", marginTop: 6 }}>foyda <b style={{ color: "#12915a" }}>{fmt(cc.profit)}</b> · marja {cc.margin}%</div>
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
  return (
    <Modal onClose={onClose} width={520}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 4 }}>{type === "low" ? "Kam qoldiqdagi mahsulotlar" : "Zarar bilan sotilgan"}</div>
      <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 14 }}>{(data || []).length} ta</div>
      <div style={{ maxHeight: "60vh", overflowY: "auto" }}>
        {(data || []).map((it, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "11px 0", borderTop: i ? "1px solid #f4f5f9" : "none" }}>
            <div><div style={{ fontWeight: 600, fontSize: 13.5 }}>{it.name}</div><div style={{ fontSize: 12, color: "#9aa0b4" }}>{it.note}</div></div>
            <div style={{ fontWeight: 700, color: "#c93a3e", whiteSpace: "nowrap" }}>{it.right}</div>
          </div>
        ))}
        {(data || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13, padding: 20, textAlign: "center" }}>Bo'sh</div>}
      </div>
      <button className="btn btn-primary" style={{ width: "100%", marginTop: 14, height: 46 }} onClick={onClose}>Yopish</button>
    </Modal>
  );
}
