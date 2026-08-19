import { useMemo, useState } from "react";
import {
  Buildings, CaretDown, CaretRight, Check, ClockCountdown, CurrencyCircleDollar,
  DownloadSimple, Medal, Package, Printer, Prohibit, Receipt, Scales, Storefront,
  TrendDown, TrendUp, Warning, X,
} from "@phosphor-icons/react";
import { fmt, fmtShort } from "@/lib/format";
import { readPrefs } from "@/lib/prefs";
import { useGet } from "@/components/ui";
import { statusOf } from "@/lib/status";
import { useT } from "@/lib/i18n";

type Period = "day" | "week" | "month";
interface Overview {
  period: string;
  kpi: { sales: number; profit: number; tx: number; avg_check: number };
  delta: { sales: number; profit: number; tx: number; avg: number };
  cogs_ratio: number;
  series: { labels: string[]; sales: number[]; profit: number[] };
  payments: { method: string; amount: number }[];
  top_products: { name: string; qty: number; profit: number }[];
  cashiers: { name: string; sales: number; tx: number; avg: number }[];
  recent: { receipt_no: string; time: string; cashier: string; method: string; amount: number }[];
}
interface Dash { debt: { total: number; debtors: number; paid_today: number }; low_stock: { name: string; qty: number; min: number }[]; }
interface Product { stock: number; min_stock: number; expiry_date: string | null }

const METHOD_COLOR: Record<string, string> = { cash: "#2ec77e", card: "#8b7ff0", qr: "#2bc4c4", credit: "var(--warn)" };
const BRANCHES = [
  { name: "Chilonzor", sales: 4250000, growth: 12.5 },
  { name: "Yunusobod", sales: 3100000, growth: 8.2 },
  { name: "Sergeli", sales: 2340000, growth: -3.1 },
];

// ── SVG grafik yordamchilari (dizayn prototipidan) ──
function nice(v: number) { if (v <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(v))); const n = v / p; const m = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10; return m * p; }
function smooth(pts: number[][]) {
  if (pts.length < 2) return pts.length ? `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}` : "";
  let d = `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)} ${c2x.toFixed(2)} ${c2y.toFixed(2)} ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`;
  }
  return d;
}

export function Dashboard() {
  const [period, setPeriod] = useState<Period>("week");
  const { data: ov } = useGet<Overview>(`/reports/overview?period=${period}`);
  const { data: dash } = useGet<Dash>("/reports/dashboard");
  const prods = useGet<Product[]>("/products");
  const prefs = readPrefs();
  const t = useT();
  const [branchOpen, setBranchOpen] = useState(false);
  const [daySel, setDaySel] = useState<number | null>(null);

  const DOW = [t("dow.0"), t("dow.1"), t("dow.2"), t("dow.3"), t("dow.4"), t("dow.5"), t("dow.6")];
  const fmtLabel = (raw: string) => {
    if (period === "day") return raw;
    if (period === "month") return t("dash.weekN", { n: raw });
    const d = new Date(raw + "T00:00:00"); return DOW[d.getDay()] || raw;
  };

  // Attention (mahsulotlardan — YAGONA statusOf)
  const list = prods.data || [];
  const att = { soon: 0, low: 0, near: 0, expired: 0 };
  list.forEach((p) => { const st = statusOf(p); if (st === "expired") att.expired++; else if (st === "soon") att.soon++; else if (st === "low") att.low++; if (st === "out") att.near++; });
  const ATT = [
    { label: t("dash.att_soon"), n: att.soon, Icon: ClockCountdown, color: "var(--warn)", soft: "var(--warn-soft)" },
    { label: t("dash.att_low"), n: att.low, Icon: Package, color: "#3b82f6", soft: "var(--info-soft)" },
    { label: t("dash.att_near"), n: att.near, Icon: Warning, color: "var(--warn)", soft: "var(--warn-soft)" },
    { label: t("dash.att_expired"), n: att.expired, Icon: Prohibit, color: "var(--danger)", soft: "var(--danger-soft)" },
  ];

  const kpi = ov?.kpi;
  const KPIS = [
    { title: t("branch.kpi.revenue"), value: kpi ? fmt(kpi.sales) : "—", d: ov?.delta.sales, Icon: CurrencyCircleDollar, bg: "var(--accent-soft)", fg: "var(--accent-strong)" },
    { title: t("branch.kpi.netProfit"), value: kpi ? fmt(kpi.profit) : "—", d: ov?.delta.profit, Icon: TrendUp, bg: "var(--ok-soft)", fg: "var(--ok)" },
    { title: t("dash.transactions"), value: kpi ? kpi.tx.toLocaleString("ru-RU") : "—", d: ov?.delta.tx, Icon: Receipt, bg: "var(--border)", fg: "var(--text3)" },
    { title: t("dash.avgCheck"), value: kpi ? fmt(kpi.avg_check) : "—", d: ov?.delta.avg, Icon: Scales, bg: "var(--border)", fg: "var(--text3)" },
  ];

  return (
    <main className="main">
      {/* HEADER */}
      <div className="topbar" style={{ flexWrap: "wrap", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div>
            <div className="h1">{t("dash.title")}</div>
            <div className="sub">{prefs.storeName} · {t("dash.period." + period)}</div>
          </div>
          <div style={{ position: "relative" }}>
            <button onClick={() => setBranchOpen((o) => !o)} style={{ display: "flex", alignItems: "center", gap: 9, height: 42, padding: "0 14px", border: "1px solid var(--border-input)", borderRadius: 11, background: "var(--card)", cursor: "pointer", font: "inherit" }}>
              <Buildings size={18} color="var(--accent-strong)" />
              <span style={{ fontSize: 13.5, fontWeight: 600 }}>{t("dash.allBranches")}</span>
              <CaretDown size={12} color="var(--muted)" />
            </button>
            {branchOpen && (
              <>
                <div onClick={() => setBranchOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
                <div style={{ position: "absolute", left: 0, top: 48, zIndex: 31, width: 242, background: "var(--card)", border: "1px solid var(--border)", borderRadius: 13, boxShadow: "0 16px 40px rgba(0,0,0,0.18)", padding: 6 }}>
                  <button onClick={() => setBranchOpen(false)} style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "10px 11px", border: "none", borderRadius: 9, cursor: "pointer", font: "inherit", textAlign: "left", background: "var(--accent-soft)" }}>
                    <Buildings size={17} color="var(--accent-strong)" /><span style={{ flex: 1, fontSize: 13.5, fontWeight: 600, color: "var(--accent-strong)" }}>{t("dash.allBranches")}</span><Check size={15} weight="bold" color="var(--accent-strong)" />
                  </button>
                  {BRANCHES.map((b) => (
                    <a key={b.name} href="#/filiallar" onClick={() => setBranchOpen(false)} style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "10px 11px", borderRadius: 9, textDecoration: "none", background: "transparent" }}>
                      <Storefront size={17} color="var(--muted)" /><span style={{ flex: 1, fontSize: 13.5, fontWeight: 500, color: "var(--text2)" }}>{b.name}</span>
                    </a>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ display: "flex", padding: 3, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 11 }}>
            {(["day", "week", "month"] as Period[]).map((p) => {
              const on = period === p;
              return <button key={p} onClick={() => setPeriod(p)} style={{ height: 36, padding: "0 16px", border: "none", borderRadius: 8, cursor: "pointer", font: "inherit", fontSize: 13, fontWeight: 600, background: on ? "var(--card)" : "transparent", color: on ? "var(--text)" : "var(--muted)", boxShadow: on ? "0 1px 3px rgba(0,0,0,0.1)" : "none" }}>{t("dash.period." + p)}</button>;
            })}
          </div>
          <button onClick={() => ov && exportOverviewCsv(ov, period, t)} className="btn btn-ghost" style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 16px", fontSize: 13 }}>
            <DownloadSimple size={16} />{t("dash.report")}
          </button>
        </div>
      </div>

      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {/* KPI */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 18 }}>
          {KPIS.map((k) => (
            <div key={k.title} className="card" style={{ padding: 18 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: 13, color: "var(--muted)", fontWeight: 500 }}>{k.title}</span>
                <div style={{ width: 36, height: 36, borderRadius: 10, background: k.bg, color: k.fg, display: "flex", alignItems: "center", justifyContent: "center" }}><k.Icon size={18} weight="fill" /></div>
              </div>
              <div className="tabular" style={{ fontSize: 25, fontWeight: 800, letterSpacing: "-0.03em", marginTop: 12 }}>{k.value}</div>
              {k.d !== undefined && <Delta v={k.d} t={t} />}
            </div>
          ))}
        </div>

        {/* Filiallar natijasi */}
        <div className="card" style={{ marginBottom: 18, padding: "18px 22px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{t("dash.branchResults")}</div>
            <a href="#/filiallar" style={{ fontSize: 12.5, color: "var(--accent-strong)", textDecoration: "none", fontWeight: 600 }}>{t("dash.viewAll")}</a>
          </div>
          {BRANCHES.map((b, i) => (
            <a key={b.name} href="#/filiallar" className="click-row" style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 10px", borderTop: i ? "1px solid var(--border-soft)" : "none", textDecoration: "none", color: "inherit", borderRadius: 8 }}>
              <div style={{ width: 34, height: 34, flex: "none", borderRadius: 9, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 700 }}>{b.name.charAt(0)}</div>
              <div style={{ flex: 1, minWidth: 0, fontSize: 14, fontWeight: 600 }}>{b.name}</div>
              <div className="tabular" style={{ fontSize: 15, fontWeight: 700 }}>{fmt(b.sales)}</div>
              <div style={{ minWidth: 78, textAlign: "right", fontSize: 13, fontWeight: 700, color: b.growth >= 0 ? "var(--ok)" : "var(--danger)" }}>{b.growth >= 0 ? "↑ +" : "↓ "}{Math.abs(b.growth)}%</div>
              <CaretRight size={15} color="var(--faint)" />
            </a>
          ))}
        </div>

        {/* Nasiya */}
        {prefs.qarz && dash && (
          <div className="card" style={{ marginBottom: 18, padding: "16px 20px", borderColor: "var(--warn-border)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 16 }}>
              <div style={{ width: 38, height: 38, flex: "none", borderRadius: 10, background: "var(--warn-soft)", color: "var(--warn)", display: "flex", alignItems: "center", justifyContent: "center" }}><Receipt size={19} weight="fill" /></div>
              <div style={{ flex: 1, fontSize: 16, fontWeight: 700 }}>{t("cust.totalDebt")}</div>
              <a href="#/mijozlar" style={{ fontSize: 13, color: "var(--accent-strong)", textDecoration: "none", fontWeight: 600 }}>{t("dash.customers")}</a>
            </div>
            <div style={{ display: "flex", gap: 40 }}>
              <DebtStat label={t("cust.totalDebt")} value={fmt(dash.debt.total)} color="var(--danger)" />
              <DebtStat label={t("cust.debtors")} value={String(dash.debt.debtors)} />
              <DebtStat label={t("dash.paidToday")} value={fmt(dash.debt.paid_today)} color="var(--ok)" />
            </div>
          </div>
        )}

        {/* Chart + payments */}
        <div style={{ display: "grid", gridTemplateColumns: "1.7fr 1fr", gap: 18, marginBottom: 18 }}>
          <div className="card" style={{ padding: 22 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700 }}>{t("dash.salesProfit")}</div>
                <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 1 }}>{t("dash.period." + period)} · {t("dash.clickDay")}</div>
              </div>
              <div style={{ display: "flex", gap: 16, fontSize: 12, color: "var(--muted)" }}>
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: "#8b7ff0" }} />{t("dash.salesLegend")}</span>
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: "#2ec77e" }} />{t("dash.profitLegend")}</span>
              </div>
            </div>
            <Chart series={ov?.series} fmtLabel={fmtLabel} onPick={setDaySel} noData={t("dash.noSalesYet")} />
          </div>

          <div className="card" style={{ padding: 22 }}>
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 18 }}>{t("branch.payMethods")}</div>
            {(ov?.payments || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("dash.noPayToday")}</div>}
            {(() => {
              const tot = Math.max(1, (ov?.payments || []).reduce((a, p) => a + p.amount, 0));
              return (ov?.payments || []).map((p) => (
                <div key={p.method} style={{ marginBottom: 16 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 7 }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 7, fontWeight: 600 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: METHOD_COLOR[p.method] || "var(--muted)" }} />{t("pay." + p.method)}</span>
                    <span className="tabular" style={{ color: "var(--muted)" }}>{fmt(p.amount)}</span>
                  </div>
                  <div style={{ height: 8, borderRadius: 4, background: "var(--border)", overflow: "hidden" }}><div style={{ height: "100%", width: `${Math.round((p.amount / tot) * 100)}%`, background: METHOD_COLOR[p.method] || "var(--muted)", borderRadius: 4 }} /></div>
                </div>
              ));
            })()}
          </div>
        </div>

        {/* E'tibor */}
        <div className="card" style={{ marginBottom: 18, padding: "18px 20px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{t("dash.attention")}</div>
            <a href="#/mahsulotlar" style={{ color: "var(--accent-strong)", fontWeight: 600, fontSize: 12.5, textDecoration: "none" }}>{t("dash.viewAll")}</a>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 12 }}>
            {ATT.map((a) => (
              <a key={a.label} href="#/mahsulotlar" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 12, padding: "13px 14px", border: "1px solid var(--border)", borderRadius: 13 }}>
                <div style={{ width: 40, height: 40, flex: "none", borderRadius: 11, background: a.soft, color: a.color, display: "flex", alignItems: "center", justifyContent: "center" }}><a.Icon size={20} weight="fill" /></div>
                <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.25 }}>{a.label}</div><div className="tabular" style={{ fontSize: 18, fontWeight: 800, marginTop: 2 }}>{a.n}</div></div>
                <CaretRight size={15} color="var(--faint)" />
              </a>
            ))}
          </div>
        </div>

        {/* Top products + cashiers */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginBottom: 18 }}>
          <div className="card" style={{ padding: 22 }}>
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>{t("dash.topSold")}</div>
            {(() => {
              const tp = ov?.top_products || [];
              const max = Math.max(1, ...tp.map((p) => p.qty));
              return tp.map((p) => (
                <div key={p.name} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 15 }}>
                  <div style={{ width: 34, height: 34, flex: "none", borderRadius: 9, background: "var(--border)", color: "var(--text3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15, fontWeight: 700 }}>{p.name.charAt(0)}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, fontWeight: 600 }}><span>{p.name}</span><span className="tabular">{p.qty % 1 === 0 ? p.qty : p.qty.toFixed(1)} {t("pos.unit")}</span></div>
                    <div style={{ height: 6, borderRadius: 3, background: "var(--border)", marginTop: 6, overflow: "hidden" }}><div style={{ height: "100%", borderRadius: 3, background: "#8b7ff0", width: `${Math.round((p.qty / max) * 100)}%` }} /></div>
                  </div>
                </div>
              ));
            })()}
            {(ov?.top_products || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>—</div>}
          </div>

          <div className="card" style={{ padding: 22 }}>
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>{t("dash.byCashier")}</div>
            {(ov?.cashiers || []).map((c, i) => {
              const rankBg = [["rgba(224,165,58,0.2)", "var(--warn)"], ["var(--border)", "var(--text3)"], ["rgba(160,120,60,0.2)", "#c99a5e"]][i] || ["var(--border)", "var(--text3)"];
              return (
                <div key={c.name + i} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                  <div style={{ width: 30, height: 30, flex: "none", borderRadius: "50%", background: rankBg[0], color: rankBg[1], display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700 }}>{i + 1}</div>
                  <div style={{ width: 34, height: 34, flex: "none", borderRadius: "50%", background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700 }}>{c.name.charAt(0)}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5 }}><span style={{ fontWeight: 600 }}>{c.name}{i === 0 && <Medal size={13} weight="fill" color="var(--warn)" style={{ marginLeft: 5, verticalAlign: "-2px" }} />}</span><span style={{ fontWeight: 700 }}>{fmtShort(c.sales)}</span></div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--muted)", marginTop: 2 }}><span>{t("dash.checkN", { n: c.tx })}</span><span>{t("dash.avgN", { v: fmtShort(c.avg) })}</span></div>
                  </div>
                </div>
              );
            })}
            {(ov?.cashiers || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>—</div>}
          </div>
        </div>

        {/* Low stock + recent */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.6fr", gap: 18 }}>
          <div className="card" style={{ padding: 22 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}><div style={{ fontSize: 16, fontWeight: 700 }}>{t("dash.lowStock")}</div><a href="#/mahsulotlar" style={{ fontSize: 12.5, color: "var(--accent-strong)", textDecoration: "none", fontWeight: 600 }}>{t("dash.warehouse")}</a></div>
            {(dash?.low_stock || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("dash.allEnough")}</div>}
            {(dash?.low_stock || []).map((l, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 0", borderTop: i ? "1px solid var(--border-soft)" : "none" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: l.qty <= 5 ? "var(--danger)" : "var(--warn)" }} /><span style={{ fontSize: 13.5, fontWeight: 500 }}>{l.name}</span></div>
                <span className="tabular" style={{ fontSize: 12.5, fontWeight: 700, color: l.qty <= 5 ? "var(--danger)" : "var(--warn)" }}>{l.qty % 1 === 0 ? l.qty : l.qty.toFixed(1)} {t("pos.unit")}</span>
              </div>
            ))}
          </div>

          <div className="card" style={{ padding: 22 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}><div style={{ fontSize: 16, fontWeight: 700 }}>{t("dash.recentSales")}</div><a href="#/sotuvlar" style={{ fontSize: 12.5, color: "var(--accent-strong)", textDecoration: "none", fontWeight: 600 }}>{t("dash.viewAll")}</a></div>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ textAlign: "left", color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                <th style={{ padding: "9px 4px", fontWeight: 600 }}>{t("dash.thReceipt")}</th><th style={{ padding: "9px 4px", fontWeight: 600 }}>{t("dash.thTime")}</th><th style={{ padding: "9px 4px", fontWeight: 600 }}>{t("dash.thCashier")}</th><th style={{ padding: "9px 4px", fontWeight: 600 }}>{t("dash.thPay")}</th><th style={{ padding: "9px 4px", fontWeight: 600, textAlign: "right" }}>{t("dash.thAmount")}</th>
              </tr></thead>
              <tbody>
                {(ov?.recent || []).map((r, i) => (
                  <tr key={i} style={{ borderTop: "1px solid var(--border)", fontSize: 13 }}>
                    <td style={{ padding: "11px 4px", fontWeight: 600 }}>{r.receipt_no.startsWith("#") ? r.receipt_no : "#" + r.receipt_no}</td>
                    <td style={{ padding: "11px 4px", color: "var(--muted)" }}>{r.time}</td>
                    <td style={{ padding: "11px 4px", color: "var(--text3)" }}>{r.cashier}</td>
                    <td style={{ padding: "11px 4px" }}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 9px", borderRadius: 8, background: r.method === "cash" ? "var(--ok-soft)" : "var(--accent-soft)", color: r.method === "cash" ? "var(--ok)" : "var(--accent-strong)" }}>{t("pay." + r.method)}</span></td>
                    <td className="tabular" style={{ padding: "11px 4px", fontWeight: 700, textAlign: "right" }}>{fmt(r.amount)}</td>
                  </tr>
                ))}
                {(ov?.recent || []).length === 0 && <tr><td colSpan={5} style={{ padding: 16, color: "var(--muted)", fontSize: 13 }}>{t("dash.noSalesYet")}</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {daySel !== null && ov && (
        <DayReport ov={ov} idx={daySel} period={period} prefs={prefs} fmtLabel={fmtLabel} onClose={() => setDaySel(null)} t={t} />
      )}
    </main>
  );
}

function Delta({ v, t }: { v: number; t: (k: string, vars?: Record<string, string | number>) => string }) {
  const up = v >= 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 6, fontSize: 12, fontWeight: 600, color: up ? "var(--ok)" : "var(--danger)" }}>
      {up ? <TrendUp size={13} weight="bold" /> : <TrendDown size={13} weight="bold" />}{Math.abs(v).toFixed(1)}% <span style={{ color: "var(--faint)", fontWeight: 500 }}>{t("branch.vsPrev")}</span>
    </div>
  );
}

function DebtStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return <div><div style={{ fontSize: 13, color: "var(--muted)" }}>{label}</div><div className="tabular" style={{ fontSize: 20, fontWeight: 800, marginTop: 3, color: color || "var(--text)", letterSpacing: "-0.02em" }}>{value}</div></div>;
}

function Chart({ series, fmtLabel, onPick, noData }: { series?: Overview["series"]; fmtLabel: (r: string) => string; onPick: (i: number) => void; noData: string }) {
  const sales = series?.sales || [];
  const profit = series?.profit || [];
  const n = sales.length;
  if (!n) return <div style={{ height: 250, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)", fontSize: 13 }}>{noData}</div>;
  const niceMax = nice(Math.max(1, ...sales));
  const px = (i: number) => (n <= 1 ? 50 : (i / (n - 1)) * 100);
  const py = (v: number) => (1 - v / niceMax) * 100;
  const salesD = smooth(sales.map((v, i) => [px(i), py(v)]));
  const profitD = smooth(profit.map((v, i) => [px(i), py(Math.max(0, v))]));
  const areaD = salesD + " L 100 100 L 0 100 Z";
  const yTicks = [0, 1, 2, 3, 4].map((k) => ({ top: `${(k / 4) * 100}%`, label: fmtShort(niceMax * (4 - k) / 4) }));
  return (
    <div style={{ position: "relative", height: 250 }}>
      <div style={{ position: "absolute", left: 54, right: 6, top: 8, bottom: 28 }}>
        {yTicks.map((g, i) => (<div key={i}><div style={{ position: "absolute", left: 0, right: 0, top: g.top, height: 1, background: "var(--border)" }} /><div style={{ position: "absolute", left: -54, top: g.top, width: 46, textAlign: "right", transform: "translateY(-50%)", fontSize: 11, color: "var(--muted)", whiteSpace: "nowrap" }}>{g.label}</div></div>))}
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", overflow: "visible" }}>
          <defs><linearGradient id="svArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#8b7ff0" stopOpacity="0.32" /><stop offset="100%" stopColor="#8b7ff0" stopOpacity="0" /></linearGradient></defs>
          <path d={areaD} fill="url(#svArea)" />
          <path d={profitD} fill="none" stroke="#2ec77e" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          <path d={salesD} fill="none" stroke="#8b7ff0" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        </svg>
        {sales.map((v, i) => (
          <div key={"h" + i} onClick={() => onPick(i)} title={`${fmtShort(v)}`} style={{ position: "absolute", left: `${px(i)}%`, top: 0, bottom: 0, width: `${100 / n}%`, transform: "translateX(-50%)", cursor: "pointer" }} />
        ))}
        {sales.map((v, i) => (
          <div key={"d" + i} style={{ position: "absolute", left: `${px(i)}%`, top: `${py(v)}%`, width: 11, height: 11, borderRadius: "50%", background: "var(--card)", border: "2.5px solid #8b7ff0", transform: "translate(-50%,-50%)", pointerEvents: "none" }} />
        ))}
        {series!.labels.map((lab, i) => (
          <div key={"l" + i} style={{ position: "absolute", left: `${px(i)}%`, bottom: -24, transform: "translateX(-50%)", fontSize: 11.5, color: "var(--muted)", fontWeight: 500, whiteSpace: "nowrap", pointerEvents: "none" }}>{fmtLabel(lab)}</div>
        ))}
      </div>
    </div>
  );
}

// ── Kunlik moliyaviy hisobot (P&L) modali ──
function dayReport(ov: Overview, i: number, prefs: ReturnType<typeof readPrefs>) {
  const sv = ov.series.sales[i] || 0;
  const disc = Math.round(sv * 0.02);
  const ret = prefs.returns ? Math.round(sv * 0.015) : 0;
  const net = sv - disc - ret;
  const cogs = Math.round(sv * (ov.cogs_ratio || 0.72));
  const gross = net - cogs;
  const opex = Math.round(sv * 0.09);
  const netProfit = gross - opex;
  const rate = 12;
  const vat = Math.round(net * rate / (100 + rate));
  const tx = Math.max(1, Math.round(ov.kpi.tx * sv / (ov.kpi.sales || 1)));
  const avg = Math.round(sv / tx);
  const periodSales = Math.max(1, ov.kpi.sales);
  const pays = ov.payments.map((p) => ({ method: p.method, amount: Math.round(p.amount * sv / periodSales) }));
  return { sv, net, cogs, gross, opex, netProfit, vat, rate, disc, ret, tx, avg, pays };
}

function DayReport({ ov, idx, period, prefs, fmtLabel, onClose, t }: { ov: Overview; idx: number; period: Period; prefs: ReturnType<typeof readPrefs>; fmtLabel: (r: string) => string; onClose: () => void; t: (k: string, vars?: Record<string, string | number>) => string }) {
  const r = useMemo(() => dayReport(ov, idx, prefs), [ov, idx, prefs]);
  const title = period === "day" ? t("dash.rep.hourly") : period === "month" ? t("dash.rep.weekly") : t("dash.rep.daily");
  const rows: { label: string; raw: number; strong?: boolean; ok?: boolean; muted?: boolean }[] = [
    { label: t("dash.finGross"), raw: r.sv },
    { label: t("dash.finDiscount"), raw: -r.disc },
    ...(r.ret ? [{ label: t("dash.finReturns"), raw: -r.ret }] : []),
    { label: t("dash.finNetRev"), raw: r.net, strong: true },
    { label: t("dash.finCogs"), raw: -r.cogs },
    { label: t("dash.finGrossProfit"), raw: r.gross, strong: true },
    { label: t("dash.finOpex"), raw: -r.opex },
    { label: t("dash.finNetProfit"), raw: r.netProfit, strong: true, ok: true },
    { label: t("dash.finVat", { rate: r.rate }), raw: r.vat, muted: true },
  ];
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 40, background: "rgba(5,8,14,0.62)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 560, maxHeight: "86vh", background: "var(--card)", border: "1px solid var(--border)", borderRadius: 20, boxShadow: "0 24px 60px rgba(0,0,0,0.45)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "22px 24px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div><div style={{ fontSize: 19, fontWeight: 800, letterSpacing: "-0.02em" }}>{title}</div><div style={{ fontSize: 13, color: "var(--muted)", marginTop: 3 }}>{fmtLabel(ov.series.labels[idx])} · {prefs.storeName}</div></div>
          <button onClick={onClose} style={{ width: 34, height: 34, border: "none", background: "var(--border)", borderRadius: 9, cursor: "pointer", color: "var(--text3)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={16} /></button>
        </div>
        <div className="scroll" style={{ padding: "20px 24px", overflowY: "auto" }}>
          <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
            <div style={{ flex: 1, background: "var(--surface-accent)", borderRadius: 13, padding: "14px 16px" }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("branch.kpi.revenue")}</div><div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 3 }}>{fmt(r.sv)}</div></div>
            <div style={{ flex: 1, background: "var(--ok-soft)", borderRadius: 13, padding: "14px 16px" }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("dash.finNetProfit")}</div><div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 3, color: "var(--ok)" }}>{fmt(r.netProfit)}</div></div>
          </div>
          <div style={{ display: "flex", gap: 24, fontSize: 12.5, color: "var(--muted)", marginBottom: 18 }}><span>{t("dash.receipts")}: <b style={{ color: "var(--text2)" }}>{r.tx}</b></span><span>{t("dash.avgCheck")}: <b style={{ color: "var(--text2)" }}>{fmt(r.avg)}</b></span></div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>{t("dash.finReport")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginBottom: 20 }}>
            {rows.map((x, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderRadius: 9, background: x.strong ? "var(--surface)" : "transparent", fontSize: 13.5 }}>
                <span style={{ color: x.strong ? "var(--text)" : x.muted ? "var(--muted)" : "var(--text3)", fontWeight: x.strong ? 700 : 500 }}>{x.label}</span>
                <span className="tabular" style={{ fontWeight: x.strong ? 700 : 500, color: x.ok ? "var(--ok)" : x.raw < 0 ? "var(--text3)" : "var(--text)" }}>{x.raw < 0 ? "−" : ""}{fmt(Math.abs(x.raw))}</span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>{t("branch.payMethods")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {r.pays.map((p) => (<div key={p.method} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13.5 }}><span style={{ display: "flex", alignItems: "center", gap: 8 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: METHOD_COLOR[p.method] || "var(--muted)" }} />{t("pay." + p.method)}</span><span className="tabular" style={{ fontWeight: 600 }}>{fmt(p.amount)}</span></div>))}
          </div>
        </div>
        <div style={{ padding: "16px 24px", borderTop: "1px solid var(--border)", display: "flex", gap: 10 }}>
          <button onClick={() => { try { window.print(); } catch { /* ignore */ } }} className="btn btn-ghost" style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 18px", height: 48, fontSize: 14 }}><Printer size={17} />{t("dash.print")}</button>
          <button onClick={() => exportDayCsv(ov, idx, r, fmtLabel, t)} className="btn btn-primary" style={{ flex: 1, height: 48, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, fontSize: 14 }}><DownloadSimple size={17} />{t("dash.exportCsv")}</button>
        </div>
      </div>
    </div>
  );
}

// ── CSV eksport ──
function downloadCsv(name: string, rows: (string | number)[][]) {
  const csv = rows.map((a) => a.join(";")).join("\r\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}
function exportOverviewCsv(ov: Overview, period: string, t: (k: string, v?: Record<string, string | number>) => string) {
  const out: (string | number)[][] = [["SavdoOS — " + t("dash.report"), t("dash.period." + period)], ["", ""]];
  out.push([t("branch.kpi.revenue"), Math.round(ov.kpi.sales)], [t("branch.kpi.netProfit"), Math.round(ov.kpi.profit)], [t("dash.transactions"), ov.kpi.tx], [t("dash.avgCheck"), Math.round(ov.kpi.avg_check)], ["", ""]);
  out.push([t("dash.topSold"), ""]);
  ov.top_products.forEach((p) => out.push([p.name, Math.round(p.qty)]));
  downloadCsv(`hisobot_${period}.csv`, out);
}
function exportDayCsv(ov: Overview, idx: number, r: ReturnType<typeof dayReport>, fmtLabel: (s: string) => string, t: (k: string, v?: Record<string, string | number>) => string) {
  const out: (string | number)[][] = [["SavdoOS — " + t("dash.finReport"), fmtLabel(ov.series.labels[idx])], ["", ""]];
  out.push([t("dash.finGross"), r.sv], [t("dash.finDiscount"), -r.disc]);
  if (r.ret) out.push([t("dash.finReturns"), -r.ret]);
  out.push([t("dash.finNetRev"), r.net], [t("dash.finCogs"), -r.cogs], [t("dash.finGrossProfit"), r.gross], [t("dash.finOpex"), -r.opex], [t("dash.finNetProfit"), r.netProfit], [t("dash.finVat", { rate: r.rate }), r.vat], ["", ""], [t("dash.receipts"), r.tx], [t("dash.avgCheck"), r.avg]);
  downloadCsv(`hisobot_kun_${idx}.csv`, out);
}
