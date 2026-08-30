import { useState } from "react";
import { fmt } from "@/lib/format";
import { Modal, Stat, Topbar, td, th, useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { Chart, type SeriesPoint } from "./Dashboard";

interface Pnl { gross: number; discount: number; net: number; cogs: number; gross_profit: number; opex: number; net_profit: number; vat: number; margin: number; }
interface Top { name: string; qty: number; profit: number; }
interface Cat { name: string; sales: number; profit: number; margin: number; }
interface Alerts { low_stock: number; loss_making: number; }
interface Overview {
  kpi: { sales: number; profit: number; tx: number; avg_check: number };
  delta: { sales: number | null; profit: number | null; tx: number | null; avg: number | null };
  series: SeriesPoint[];
  payments: { method: string; amount: number }[]; credit_total: number;
  cashiers: { name: string; sales: number; tx: number; avg: number }[];
}
interface CashFlow {
  in: { naqd_savdo: number; qarz_qaytdi: number; qoshimcha: number; jami: number };
  out: { xarajat: number; inkassatsiya: number; qaytarish: number; beruvchiga: number; jami: number };
  opening: number; kassada: number; noncash: { karta: number; qr: number; nasiya: number };
}
interface Abc { returns: { count: number; sum: number; voided: number }; a_share: number; abc: { name: string; units: number; revenue: number; profit: number; share: number; cls: string }[]; }
interface InvValue { total_cost: number; total_retail: number; potential_profit: number; item_count: number; by_category: { name: string; value: number }[]; top_items: { name: string; qty: number; value: number }[]; }
interface DeadStock { days: number; count: number; frozen_value: number; items: { name: string; qty: number; value: number; last_sold: string | null; days_idle: number | null }[]; }
interface Debtors { total: number; count: number; rows: { name: string; phone: string | null; balance: number; last_payment: string | null; days_since: number | null }[]; }

const METHOD_COLOR: Record<string, string> = { cash: "#2ec77e", card: "#8b7ff0", qr: "#2bc4c4", credit: "var(--warn)" };
const PERIODS = [["today", "sales2.today"], ["week", "sales2.week"], ["month", "sales2.month"], ["all", "rep.periodAll"]];
const CLS_COLOR: Record<string, string> = { A: "var(--ok)", B: "var(--warn)", C: "var(--faint)" };

// Hisobot davri -> overview/cashflow davri (ular 'today'/'all' bilmaydi)
const ovP = (p: string) => (p === "today" ? "day" : p === "all" ? "month" : p);

// Ixtiyoriy sana oralig'i so'rov qo'shimchasi (from/to bo'lsa — preset e'tiborsiz)
export const rq = (from: string, to: string) => (from && to ? `&from_date=${from}&to_date=${to}` : "");

export function Reports() {
  const [tab, setTab] = useState("umumiy");
  const [period, setPeriod] = useState("month");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const custom = !!(from && to);
  const t = useT();
  const TABS: [string, string][] = [
    ["umumiy", t("rep.tabOverview")], ["kassa", t("rep.tabCash")], ["mahsulot", t("rep.tabAbc")],
    ["ombor", t("rep.tabStock")], ["mijoz", t("rep.tabDebt")],
  ];

  return (
    <main className="main">
      <Topbar title={t("nav.hisobotlar")} sub={t("rep.sub")}
        right={
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: 6, background: "var(--surface)", borderRadius: 11, padding: 3 }}>
              {PERIODS.map(([k, l]) => (
                <button key={k} onClick={() => { setFrom(""); setTo(""); setPeriod(k); }} style={{ height: 34, padding: "0 13px", border: "none", borderRadius: 8, cursor: "pointer", fontSize: 13, fontWeight: 600, background: (!custom && period === k) ? "var(--card)" : "transparent", color: (!custom && period === k) ? "var(--accent-strong)" : "var(--muted)", boxShadow: (!custom && period === k) ? "0 1px 3px rgba(0,0,0,0.12)" : "none" }}>{t(l)}</button>
              ))}
            </div>
            {/* Ixtiyoriy sana oralig'i */}
            <div style={{ display: "flex", gap: 6, alignItems: "center", border: custom ? "1.5px solid var(--accent-strong)" : "1px solid var(--border-input)", borderRadius: 10, padding: "3px 8px", background: "var(--card)" }}>
              <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} title={t("rep.from")} style={{ border: "none", background: "transparent", font: "inherit", fontSize: 13, color: "var(--text)", outline: "none", colorScheme: "light dark" as any }} />
              <span style={{ color: "var(--muted)" }}>—</span>
              <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} title={t("rep.to")} style={{ border: "none", background: "transparent", font: "inherit", fontSize: 13, color: "var(--text)", outline: "none", colorScheme: "light dark" as any }} />
              {custom && <button onClick={() => { setFrom(""); setTo(""); }} title={t("common.cancel")} style={{ border: "none", background: "transparent", cursor: "pointer", color: "var(--muted)", fontSize: 16, lineHeight: 1, padding: "0 2px" }}>×</button>}
            </div>
            <button className="btn btn-ghost" style={{ padding: "10px 14px" }} onClick={() => window.print()}>🖨 {t("rep.print")}</button>
          </div>
        } />

      {/* Bo'limlar (tab) */}
      <div style={{ display: "flex", gap: 4, padding: "0 24px", borderBottom: "1px solid var(--border)", background: "var(--card)" }}>
        {TABS.map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} style={{ padding: "14px 16px", border: "none", background: "transparent", cursor: "pointer", fontSize: 14, fontWeight: 700, color: tab === k ? "var(--accent-strong)" : "var(--muted)", borderBottom: tab === k ? "2.5px solid var(--accent-strong)" : "2.5px solid transparent", marginBottom: -1 }}>{l}</button>
        ))}
      </div>

      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {tab === "umumiy" && <OverviewTab period={period} from={from} to={to} />}
        {tab === "kassa" && <CashTab period={period} from={from} to={to} />}
        {tab === "mahsulot" && <AbcTab period={period} from={from} to={to} />}
        {tab === "ombor" && <StockTab />}
        {tab === "mijoz" && <DebtTab />}
      </div>
    </main>
  );
}

// ═══ Delta ko'rsatkichi (↑/↓ %) ═══
function Delta({ v }: { v: number | null | undefined }) {
  const t = useT();
  if (v == null) return <span style={{ fontSize: 12, fontWeight: 600, color: "var(--faint)" }}>{t("dash.newBadge")}</span>;
  const up = v >= 0;
  return <span style={{ fontSize: 12.5, fontWeight: 700, color: up ? "var(--ok)" : "var(--danger)" }}>{up ? "↑ +" : "↓ "}{Math.abs(v)}%</span>;
}

// ═══ UMUMIY: KPI+delta, grafik, to'lov mix, P&L, top, kategoriya ═══
function OverviewTab({ period, from, to }: { period: string; from: string; to: string }) {
  const t = useT();
  const r = rq(from, to);
  // 'Butun' (all) tanlanса, overview/cashflow all-time bilmaydi va 'oy'ga tushadi. Shu tabда
  // P&L/mahsulot/kategoriya ham SHU davrga (oy) tenglashtiramiz — aks holда bir ekranда KPI=oy,
  // P&L=butun-davr chiqиб, sarlavha KPI'lari P&L bilan ochiqdан-ochiq zid bo'lардi. ('today'/'day'
  // semantik teng — faqat 'all' muammoli, shu bois faqat uni moslaymiz.)
  const pP = period === "all" ? "month" : period;
  const ov = useGet<Overview>(`/reports/overview?period=${ovP(period)}${r}`);
  const pnl = useGet<Pnl>(`/reports/pnl?period=${pP}${r}`);
  const top = useGet<Top[]>(`/reports/top-products?period=${pP}${r}`);
  const cats = useGet<Cat[]>(`/reports/categories?period=${pP}${r}`);
  const [alertModal, setAlertModal] = useState<"low" | "loss" | null>(null);
  const alerts = useGet<Alerts>("/reports/alerts");
  const o = ov.data; const p = pnl.data;
  const k = o?.kpi;
  const KPIS = [
    { title: t("branch.kpi.revenue"), value: k ? fmt(k.sales) : "—", d: o?.delta.sales, color: undefined },
    { title: t("dash.grossProfit"), value: k ? fmt(k.profit) : "—", d: o?.delta.profit, color: "var(--green)" },
    { title: t("dash.transactions"), value: k ? k.tx.toLocaleString("ru-RU") : "—", d: o?.delta.tx, color: undefined },
    { title: t("dash.avgCheck"), value: k ? fmt(k.avg_check) : "—", d: o?.delta.avg, color: undefined },
  ];
  const payRows = o ? [...o.payments, ...(o.credit_total ? [{ method: "credit", amount: o.credit_total }] : [])] : [];
  const payTot = Math.max(1, payRows.reduce((a, x) => a + x.amount, 0));

  // Xatoni YASHIRMAYMIZ — aks holда fetch muvaffaqiyatsizligи "savdo yo'q" / abadiy yuklanish
  // bo'lиб ko'rinарди va rahbар bo'sh/eskирган ma'lumot ustида qaror qabul qilардi.
  const loadErr = ov.err || pnl.err || top.err || cats.err;
  return (
    <>
      {loadErr && (
        <div style={{ padding: "10px 14px", marginBottom: 14, borderRadius: 10, background: "var(--danger-soft)", color: "var(--danger)", fontSize: 13, fontWeight: 600 }}>
          {t("common.error")}: {String(loadErr)}
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 18 }}>
        {KPIS.map((x) => (
          <div key={x.title} className="card" style={{ padding: 18 }}>
            <div style={{ fontSize: 13, color: "var(--muted)", fontWeight: 500 }}>{x.title}</div>
            <div className="tabular" style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-0.03em", marginTop: 10, color: x.color }}>{x.value}</div>
            <div style={{ marginTop: 6 }}><Delta v={x.d} /></div>
          </div>
        ))}
      </div>

      {/* Grafik + to'lov usullari */}
      <div style={{ display: "grid", gridTemplateColumns: "1.7fr 1fr", gap: 18, marginBottom: 18 }}>
        <div className="card" style={{ padding: 22 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{t("dash.salesProfit")}</div>
            <div style={{ display: "flex", gap: 16, fontSize: 12, color: "var(--muted)" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: "#8b7ff0" }} />{t("dash.salesLegend")}</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: "#2ec77e" }} />{t("dash.profitLegend")}</span>
            </div>
          </div>
          <Chart series={o?.series} fmtLabel={(r) => (period === "today" || r.length <= 5 ? r : r.slice(5))} onPick={() => {}} noData={t("dash.noSalesYet")} />
        </div>
        <div className="card" style={{ padding: 22 }}>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 18 }}>{t("branch.payMethods")}</div>
          {payRows.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("dash.noPayToday")}</div>}
          {payRows.map((pm) => (
            <div key={pm.method} style={{ marginBottom: 15 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 7 }}>
                <span style={{ display: "flex", alignItems: "center", gap: 7, fontWeight: 600 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: METHOD_COLOR[pm.method] || "var(--muted)" }} />{pm.method === "credit" ? t("dash.creditUnpaid") : t("pay." + pm.method)}</span>
                <span className="tabular" style={{ color: "var(--muted)" }}>{fmt(pm.amount)}</span>
              </div>
              <div style={{ height: 8, borderRadius: 4, background: "var(--border)", overflow: "hidden" }}><div style={{ height: "100%", width: `${Math.round((pm.amount / payTot) * 100)}%`, background: METHOD_COLOR[pm.method] || "var(--muted)", borderRadius: 4 }} /></div>
            </div>
          ))}
        </div>
      </div>

      {/* P&L + Top + Kassirlar */}
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 18 }}>
        <div className="card">
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>{t("rep.pnl")}</div>
          {p ? [
            [t("rep.gross"), p.gross, false], [t("rep.discounts"), -p.discount, false],
            [t("rep.net"), p.net, true], [t("rep.cogs"), -p.cogs, false],
            [t("rep.grossProfit"), p.gross_profit, true],
          ].map(([label, val, bold], i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: bold ? "12px 0" : "8px 0", borderTop: bold ? "1px solid var(--border)" : "none" }}>
              <span style={{ fontSize: (bold ? 14.5 : 13.5), fontWeight: bold ? 700 : 500, color: bold ? "var(--ink)" : "var(--text3)" }}>{label as string}</span>
              <span className="tabular" style={{ fontSize: (bold ? 14.5 : 13.5), fontWeight: bold ? 700 : 500, color: (val as number) < 0 ? "var(--muted)" : "var(--text2)" }}>{(val as number) < 0 ? "−" : ""}{fmt(Math.abs(val as number))}</span>
            </div>
          )) : <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("common.loading")}</div>}
          {p && (
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16, padding: "16px 18px", borderRadius: 14, background: "var(--ok-soft)", border: "1px solid var(--ok-border)" }}>
              <div><div style={{ fontSize: 13, fontWeight: 600, color: "var(--ok)" }}>{t("rep.netProfit")}</div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{t("rep.marginLabel", { n: p.margin })}</div></div>
              <div style={{ fontSize: 28, fontWeight: 800, color: "var(--ok)" }} className="tabular">{fmt(p.net_profit)}</div>
            </div>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div className="card">
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>{t("rep.topProducts")}</div>
            {(top.data || []).map((tp, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "7px 0" }}>
                <div style={{ width: 22, height: 22, borderRadius: 7, background: i === 0 ? "var(--accent-soft)" : "var(--border)", color: i === 0 ? "var(--accent-ink)" : "var(--text3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700 }}>{i + 1}</div>
                <div style={{ flex: 1, fontSize: 13, fontWeight: 600 }}>{tp.name}</div>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ok)" }} className="tabular">{fmt(tp.profit)}</div>
              </div>
            ))}
            {(top.data || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("rep.noData")}</div>}
          </div>
          <div className="card">
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>{t("rep.cashiers")}</div>
            {(o?.cashiers || []).map((c, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "7px 0" }}>
                <div style={{ width: 22, height: 22, borderRadius: 7, background: i === 0 ? "var(--accent-soft)" : "var(--border)", color: i === 0 ? "var(--accent-ink)" : "var(--text3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700 }}>{i + 1}</div>
                <div style={{ flex: 1, minWidth: 0, fontSize: 13, fontWeight: 600 }}>{c.name}<span style={{ color: "var(--muted)", fontWeight: 400 }}> · {t("sales.pcs", { n: c.tx })}</span></div>
                <div style={{ fontSize: 13, fontWeight: 700 }} className="tabular">{fmt(c.sales)}</div>
              </div>
            ))}
            {(o?.cashiers || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("rep.noData")}</div>}
          </div>
        </div>
      </div>

      {/* Kategoriya + ogohlantirishlar */}
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 18, marginTop: 18 }}>
        <div className="card">
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>{t("rep.byCategory")}</div>
          {(cats.data || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("rep.noSalesPeriod")}</div>}
          {(cats.data || []).map((cc, i) => {
            const max = Math.max(1, ...(cats.data || []).map((x) => x.profit));
            return (
              <div key={i} style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
                  <span style={{ fontWeight: 600 }}>{cc.name}</span>
                  <span style={{ color: "var(--muted)" }}>{t("rep.profitLc")} <b style={{ color: "var(--ok)" }}>{fmt(cc.profit)}</b> · {cc.margin}%</span>
                </div>
                <div style={{ height: 9, borderRadius: 5, background: "var(--border-soft)", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${Math.round((cc.profit / max) * 100)}%`, background: i === 0 ? "var(--accent)" : "var(--accent-border)", borderRadius: 5 }} />
                </div>
              </div>
            );
          })}
        </div>
        <div className="card">
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>{t("dash.attention")}</div>
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
      {alertModal && <AlertModal type={alertModal} onClose={() => setAlertModal(null)} />}
    </>
  );
}

// ═══ KASSA: naqd oqim + soatlik peak ═══
function CashTab({ period, from, to }: { period: string; from: string; to: string }) {
  const t = useT();
  const cf = useGet<CashFlow>(`/reports/cashflow?period=${ovP(period)}${rq(from, to)}`);
  const hourly = useGet<{ hour: number; sales: number }[]>("/reports/hourly");
  const c = cf.data;
  const hrs = hourly.data || [];
  const hmax = Math.max(1, ...hrs.map((h) => h.sales));
  const peak = hrs.reduce((a, h) => (h.sales > a.sales ? h : a), { hour: 0, sales: 0 });

  const inRows = c ? [
    [t("rep.cf.cashSale"), c.in.naqd_savdo], [t("rep.cf.debtBack"), c.in.qarz_qaytdi], [t("rep.cf.extra"), c.in.qoshimcha],
  ] : [];
  const outRows = c ? [
    [t("rep.cf.expense"), c.out.xarajat], [t("rep.cf.collection"), c.out.inkassatsiya], [t("rep.cf.refund"), c.out.qaytarish], [t("rep.cf.toSupplier"), c.out.beruvchiga],
  ] : [];

  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 18 }}>
        <Stat label={t("rep.cf.opening")} value={c ? fmt(c.opening) : "—"} />
        <Stat label={t("rep.cf.in")} value={c ? fmt(c.in.jami) : "—"} color="var(--ok)" />
        <Stat label={t("rep.cf.out")} value={c ? fmt(c.out.jami) : "—"} color="var(--danger)" />
        <Stat label={t("rep.cf.inDrawer")} value={c ? fmt(c.kassada) : "—"} color="var(--accent-strong)" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginBottom: 18 }}>
        <div className="card">
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12, color: "var(--ok)" }}>↓ {t("rep.cf.in")}</div>
          {inRows.map(([l, v], i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "9px 0", borderTop: i ? "1px solid var(--border-soft)" : "none", fontSize: 13.5 }}>
              <span style={{ color: "var(--text3)" }}>{l as string}</span><span className="tabular" style={{ fontWeight: 600 }}>{fmt(v as number)}</span>
            </div>
          ))}
        </div>
        <div className="card">
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12, color: "var(--danger)" }}>↑ {t("rep.cf.out")}</div>
          {outRows.map(([l, v], i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "9px 0", borderTop: i ? "1px solid var(--border-soft)" : "none", fontSize: 13.5 }}>
              <span style={{ color: "var(--text3)" }}>{l as string}</span><span className="tabular" style={{ fontWeight: 600 }}>{fmt(v as number)}</span>
            </div>
          ))}
        </div>
      </div>

      {c && (c.noncash.karta > 0 || c.noncash.qr > 0 || c.noncash.nasiya > 0) && (
        <div className="card" style={{ marginBottom: 18, display: "flex", gap: 40 }}>
          <div><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("pay.card")}</div><div className="tabular" style={{ fontSize: 18, fontWeight: 800, marginTop: 4 }}>{fmt(c.noncash.karta)}</div></div>
          <div><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("pay.qr")}</div><div className="tabular" style={{ fontSize: 18, fontWeight: 800, marginTop: 4 }}>{fmt(c.noncash.qr)}</div></div>
          <div><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("dash.creditUnpaid")}</div><div className="tabular" style={{ fontSize: 18, fontWeight: 800, marginTop: 4, color: "var(--warn)" }}>{fmt(c.noncash.nasiya)}</div></div>
        </div>
      )}

      {/* Soatlik savdo (bugun) */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>{t("rep.hourly")}</div>
          {peak.sales > 0 && <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("rep.peakHour")}: <b style={{ color: "var(--accent-strong)" }}>{String(peak.hour).padStart(2, "0")}:00</b></div>}
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 150 }}>
          {hrs.map((h) => (
            <div key={h.hour} title={`${String(h.hour).padStart(2, "0")}:00 — ${fmt(h.sales)}`} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", height: "100%" }}>
              <div style={{ width: "100%", height: `${(h.sales / hmax) * 100}%`, minHeight: h.sales > 0 ? 3 : 0, background: h.hour === peak.hour && peak.sales > 0 ? "var(--accent-strong)" : "var(--accent-border)", borderRadius: "3px 3px 0 0" }} />
              {h.hour % 3 === 0 && <div style={{ fontSize: 9.5, color: "var(--muted)", marginTop: 4 }}>{h.hour}</div>}
            </div>
          ))}
        </div>
        {peak.sales === 0 && <div style={{ color: "var(--muted)", fontSize: 13, textAlign: "center", padding: 20 }}>{t("dash.noSalesYet")}</div>}
      </div>
    </>
  );
}

// ═══ ABC: mahsulot 80/20 tahlili ═══
function AbcTab({ period, from, to }: { period: string; from: string; to: string }) {
  const t = useT();
  const det = useGet<Abc>(`/reports/detail?period=${period}${rq(from, to)}`);
  const d = det.data;
  const abc = d?.abc || [];
  const counts = { A: 0, B: 0, C: 0 };
  abc.forEach((x) => { counts[(x.cls as "A" | "B" | "C")]++; });

  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 18 }}>
        <Stat label={t("rep.classA") + " (80%)"} value={String(counts.A)} color="var(--ok)" note={t("rep.aShare", { n: d?.a_share ?? 0 })} />
        <Stat label={t("rep.classB") + " (15%)"} value={String(counts.B)} color="var(--warn)" />
        <Stat label={t("rep.classC") + " (5%)"} value={String(counts.C)} color="var(--faint)" />
        <Stat label={t("rep.returns")} value={d ? String(d.returns.count) : "—"} note={d ? fmt(d.returns.sum) : ""} />
      </div>
      <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 12 }}>{t("rep.abcDesc")}</div>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ background: "var(--card-alt)" }}>
            <th style={{ ...th, width: 40 }}></th>
            <th style={th}>{t("sales.thProduct")}</th>
            <th style={{ ...th, textAlign: "right" }}>{t("recv.qty")}</th>
            <th style={{ ...th, textAlign: "right" }}>{t("rep.revenue")}</th>
            <th style={{ ...th, textAlign: "right" }}>{t("rep.profit")}</th>
            <th style={{ ...th, textAlign: "right" }}>{t("rep.share")}</th>
          </tr></thead>
          <tbody>
            {abc.map((x, i) => (
              <tr key={i}>
                <td style={{ ...td, textAlign: "center" }}><span style={{ fontSize: 11, fontWeight: 800, color: "#fff", background: CLS_COLOR[x.cls], borderRadius: 6, padding: "2px 8px" }}>{x.cls}</span></td>
                <td style={{ ...td, fontWeight: 600 }}>{x.name}</td>
                <td style={{ ...td, textAlign: "right" }} className="tabular">{x.units}</td>
                <td style={{ ...td, textAlign: "right" }} className="tabular">{fmt(x.revenue)}</td>
                <td style={{ ...td, textAlign: "right", fontWeight: 700, color: "var(--ok)" }} className="tabular">{fmt(x.profit)}</td>
                <td style={{ ...td, textAlign: "right", color: "var(--muted)" }} className="tabular">{x.share}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        {abc.length === 0 && <div style={{ padding: 30, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>{t("rep.noSalesPeriod")}</div>}
      </div>
    </>
  );
}

// ═══ OMBOR: qiymat + o'lik tovarlar ═══
function StockTab() {
  const t = useT();
  const inv = useGet<InvValue>("/reports/inventory-value");
  const [days, setDays] = useState(30);
  const dead = useGet<DeadStock>(`/reports/dead-stock?days=${days}`);
  const v = inv.data; const ds = dead.data;
  const catMax = Math.max(1, ...(v?.by_category || []).map((c) => c.value));

  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 18 }}>
        <Stat label={t("rep.stockValue")} value={v ? fmt(v.total_cost) : "—"} />
        <Stat label={t("rep.retailValue")} value={v ? fmt(v.total_retail) : "—"} />
        <Stat label={t("rep.potentialProfit")} value={v ? fmt(v.potential_profit) : "—"} color="var(--green)" />
        <Stat label={t("rep.itemsInStock")} value={v ? String(v.item_count) : "—"} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.3fr", gap: 18 }}>
        <div className="card">
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>{t("rep.byCategoryValue")}</div>
          {(v?.by_category || []).map((cc, i) => (
            <div key={i} style={{ marginBottom: 11 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 5 }}>
                <span style={{ fontWeight: 600 }}>{cc.name}</span><span className="tabular" style={{ color: "var(--muted)" }}>{fmt(cc.value)}</span>
              </div>
              <div style={{ height: 8, borderRadius: 4, background: "var(--border-soft)", overflow: "hidden" }}><div style={{ height: "100%", width: `${Math.round((cc.value / catMax) * 100)}%`, background: "var(--accent-border)", borderRadius: 4 }} /></div>
            </div>
          ))}
          {(v?.by_category || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("rep.noData")}</div>}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px 12px" }}>
            <div><div style={{ fontSize: 15, fontWeight: 700 }}>{t("rep.deadStock")}</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{ds ? t("rep.frozenValue") + ": " : ""}<b style={{ color: "var(--danger)" }}>{ds ? fmt(ds.frozen_value) : ""}</b></div></div>
            <div style={{ display: "flex", gap: 4, background: "var(--surface)", borderRadius: 9, padding: 3 }}>
              {[30, 60, 90].map((dv) => (
                <button key={dv} onClick={() => setDays(dv)} style={{ height: 30, padding: "0 10px", border: "none", borderRadius: 7, cursor: "pointer", fontSize: 12, fontWeight: 700, background: days === dv ? "var(--card)" : "transparent", color: days === dv ? "var(--accent-strong)" : "var(--muted)" }}>{dv} {t("rep.days")}</button>
              ))}
            </div>
          </div>
          <div style={{ maxHeight: 360, overflowY: "auto" }} className="no-sb">
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ background: "var(--card-alt)" }}>
                <th style={th}>{t("sales.thProduct")}</th><th style={{ ...th, textAlign: "right" }}>{t("purch.stock")}</th><th style={{ ...th, textAlign: "right" }}>{t("rep.frozenValue")}</th><th style={{ ...th, textAlign: "right" }}>{t("rep.lastSold")}</th>
              </tr></thead>
              <tbody>
                {(ds?.items || []).map((it, i) => (
                  <tr key={i}>
                    <td style={{ ...td, fontWeight: 600 }}>{it.name}</td>
                    <td style={{ ...td, textAlign: "right" }} className="tabular">{it.qty}</td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(it.value)}</td>
                    <td style={{ ...td, textAlign: "right", color: "var(--muted)", fontSize: 12.5 }}>{it.last_sold ? t("rep.daysIdleN", { n: it.days_idle ?? 0 }) : t("rep.neverSold")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(ds?.items || []).length === 0 && <div style={{ padding: 30, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>{t("rep.noDeadStock")}</div>}
          </div>
        </div>
      </div>
    </>
  );
}

// ═══ MIJOZLAR: qarzlar (aging) ═══
function DebtTab() {
  const t = useT();
  const deb = useGet<Debtors>("/reports/debtors");
  const d = deb.data;
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16, marginBottom: 18 }}>
        <Stat label={t("cust.totalDebt")} value={d ? fmt(d.total) : "—"} color="var(--danger)" />
        <Stat label={t("cust.debtors")} value={d ? String(d.count) : "—"} />
        <Stat label={t("rep.avgDebt")} value={d && d.count ? fmt(d.total / d.count) : "—"} />
      </div>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ background: "var(--card-alt)" }}>
            <th style={th}>{t("purch.name")}</th><th style={th}>{t("cust.thPhone")}</th><th style={{ ...th, textAlign: "right" }}>{t("purch.debt")}</th><th style={{ ...th, textAlign: "right" }}>{t("rep.lastPayment")}</th>
          </tr></thead>
          <tbody>
            {(d?.rows || []).map((r, i) => (
              <tr key={i}>
                <td style={{ ...td, fontWeight: 600 }}>{r.name}</td>
                <td style={{ ...td, color: "var(--text3)" }}>{r.phone || "—"}</td>
                <td style={{ ...td, textAlign: "right", fontWeight: 700, color: "var(--danger)" }} className="tabular">{fmt(r.balance)}</td>
                <td style={{ ...td, textAlign: "right", fontSize: 12.5, color: (r.days_since ?? 0) > 30 ? "var(--danger)" : "var(--muted)" }}>{r.last_payment ? t("rep.daysAgoN", { n: r.days_since ?? 0 }) : t("rep.noPayment")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(d?.rows || []).length === 0 && <div style={{ padding: 30, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>{t("rep.noDebtors")}</div>}
      </div>
    </>
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
