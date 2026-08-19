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
type Pays = { cash: number; card: number; qr: number; credit: number };
interface SeriesPoint { label: string; subtotal: number; discount: number; returns: number; sales: number; cost: number; profit: number; tx: number; pays: Pays }
interface Overview {
  period: string; tz_hours: number;
  kpi: { sales: number; profit: number; tx: number; avg_check: number };
  delta: { sales: number | null; profit: number | null; tx: number | null; avg: number | null };
  series: SeriesPoint[];
  payments: { method: string; amount: number }[];
  credit_total: number;
  top_products: { name: string; revenue: number; qty: number }[];
  cashiers: { name: string; sales: number; tx: number; avg: number }[];
  recent: { receipt_no: string; time: string; cashier: string; method: string; amount: number; refunded: boolean }[];
  branches: { name: string; sales: number; growth: number | null }[];
  branch_count: number;
  vat_on: boolean; vat_rate: number;
}
interface Dash { debt: { total: number; debtors: number; paid_today: number }; low_stock: { name: string; qty: number; min: number }[]; }
interface Product { stock: number; min_stock: number; expiry_date: string | null }
type Tr = (k: string, vars?: Record<string, string | number>) => string;

const METHOD_COLOR: Record<string, string> = { cash: "#2ec77e", card: "#8b7ff0", qr: "#2bc4c4", credit: "var(--warn)" };

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
    { title: t("dash.grossProfit"), value: kpi ? fmt(kpi.profit) : "—", d: ov?.delta.profit, Icon: TrendUp, bg: "var(--ok-soft)", fg: "var(--ok)" },
    { title: t("dash.transactions"), value: kpi ? kpi.tx.toLocaleString("ru-RU") : "—", d: ov?.delta.tx, Icon: Receipt, bg: "var(--border)", fg: "var(--text3)" },
    { title: t("dash.avgCheck"), value: kpi ? fmt(kpi.avg_check) : "—", d: ov?.delta.avg, Icon: Scales, bg: "var(--border)", fg: "var(--text3)" },
  ];

  const multiBranch = (ov?.branch_count || 0) >= 2;

  return (
    <main className="main">
      <div className="topbar" style={{ flexWrap: "wrap", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div>
            <div className="h1">{t("dash.title")}</div>
            <div className="sub">{prefs.storeName} · {t("dash.period." + period)}</div>
          </div>
          {multiBranch && (
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
                    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 11px", borderRadius: 9, background: "var(--accent-soft)" }}>
                      <Buildings size={17} color="var(--accent-strong)" /><span style={{ flex: 1, fontSize: 13.5, fontWeight: 600, color: "var(--accent-strong)" }}>{t("dash.allBranches")}</span><Check size={15} weight="bold" color="var(--accent-strong)" />
                    </div>
                    {(ov?.branches || []).map((b) => (
                      <a key={b.name} href="#/filiallar" onClick={() => setBranchOpen(false)} style={{ display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "10px 11px", borderRadius: 9, textDecoration: "none", background: "transparent" }}>
                        <Storefront size={17} color="var(--muted)" /><span style={{ flex: 1, fontSize: 13.5, fontWeight: 500, color: "var(--text2)" }}>{b.name}</span>
                      </a>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
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
              <Delta v={k.d} t={t} />
            </div>
          ))}
        </div>

        {/* Filiallar natijasi — faqat 2+ REAL filial bo'lsa */}
        {multiBranch && (
          <div className="card" style={{ marginBottom: 18, padding: "18px 22px" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <div style={{ fontSize: 16, fontWeight: 700 }}>{t("dash.branchResults")}</div>
              <a href="#/filiallar" style={{ fontSize: 12.5, color: "var(--accent-strong)", textDecoration: "none", fontWeight: 600 }}>{t("dash.viewAll")}</a>
            </div>
            {(ov?.branches || []).map((b, i) => (
              <a key={b.name} href="#/filiallar" className="click-row" style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 10px", borderTop: i ? "1px solid var(--border-soft)" : "none", textDecoration: "none", color: "inherit", borderRadius: 8 }}>
                <div style={{ width: 34, height: 34, flex: "none", borderRadius: 9, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 700 }}>{b.name.charAt(0)}</div>
                <div style={{ flex: 1, minWidth: 0, fontSize: 14, fontWeight: 600 }}>{b.name}</div>
                <div className="tabular" style={{ fontSize: 15, fontWeight: 700 }}>{fmt(b.sales)}</div>
                <div style={{ minWidth: 78, textAlign: "right", fontSize: 13, fontWeight: 700, color: b.growth == null ? "var(--faint)" : b.growth >= 0 ? "var(--ok)" : "var(--danger)" }}>{b.growth == null ? t("dash.newBadge") : (b.growth >= 0 ? "↑ +" : "↓ ") + Math.abs(b.growth) + "%"}</div>
                <CaretRight size={15} color="var(--faint)" />
              </a>
            ))}
          </div>
        )}

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
            {(ov?.payments || []).length === 0 && !ov?.credit_total && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("dash.noPayToday")}</div>}
            {(() => {
              const rows = [...(ov?.payments || [])];
              if (ov?.credit_total) rows.push({ method: "credit", amount: ov.credit_total });
              const tot = Math.max(1, rows.reduce((a, p) => a + p.amount, 0));
              return rows.map((p) => (
                <div key={p.method} style={{ marginBottom: 16 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 7 }}>
                    <span style={{ display: "flex", alignItems: "center", gap: 7, fontWeight: 600 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: METHOD_COLOR[p.method] || "var(--muted)" }} />{p.method === "credit" ? t("dash.creditUnpaid") : t("pay." + p.method)}</span>
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
              const max = Math.max(1, ...tp.map((p) => p.revenue));
              return tp.map((p) => (
                <div key={p.name} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 15 }}>
                  <div style={{ width: 34, height: 34, flex: "none", borderRadius: 9, background: "var(--border)", color: "var(--text3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15, fontWeight: 700 }}>{p.name.charAt(0)}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, fontWeight: 600 }}><span>{p.name}</span><span className="tabular">{fmt(p.revenue)}</span></div>
                    <div style={{ height: 6, borderRadius: 3, background: "var(--border)", marginTop: 6, overflow: "hidden" }}><div style={{ height: "100%", borderRadius: 3, background: "#8b7ff0", width: `${Math.round((p.revenue / max) * 100)}%` }} /></div>
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
                  <tr key={i} style={{ borderTop: "1px solid var(--border)", fontSize: 13, opacity: r.refunded ? 0.55 : 1 }}>
                    <td style={{ padding: "11px 4px", fontWeight: 600 }}>{r.receipt_no.startsWith("#") ? r.receipt_no : "#" + r.receipt_no}{r.refunded && <span style={{ marginLeft: 6, fontSize: 10, color: "var(--danger)", fontWeight: 700 }}>↩</span>}</td>
                    <td style={{ padding: "11px 4px", color: "var(--muted)" }}>{r.time}</td>
                    <td style={{ padding: "11px 4px", color: "var(--text3)" }}>{r.cashier}</td>
                    <td style={{ padding: "11px 4px" }}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "3px 9px", borderRadius: 8, background: r.method === "cash" ? "var(--ok-soft)" : "var(--accent-soft)", color: r.method === "cash" ? "var(--ok)" : "var(--accent-strong)" }}>{t("pay." + r.method)}</span></td>
                    <td className="tabular" style={{ padding: "11px 4px", fontWeight: 700, textAlign: "right", textDecoration: r.refunded ? "line-through" : "none" }}>{fmt(r.amount)}</td>
                  </tr>
                ))}
                {(ov?.recent || []).length === 0 && <tr><td colSpan={5} style={{ padding: 16, color: "var(--muted)", fontSize: 13 }}>{t("dash.noSalesYet")}</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {daySel !== null && ov && ov.series[daySel] && (
        <DayReport pt={ov.series[daySel]} period={period} vatOn={ov.vat_on} vatRate={ov.vat_rate} store={prefs.storeName} fmtLabel={fmtLabel} onClose={() => setDaySel(null)} t={t} />
      )}
    </main>
  );
}

function Delta({ v, t }: { v: number | null | undefined; t: Tr }) {
  if (v === null || v === undefined) return <div style={{ marginTop: 6, fontSize: 12, fontWeight: 600, color: "var(--faint)" }}>{t("dash.newBadge")}</div>;
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

function Chart({ series, fmtLabel, onPick, noData }: { series?: SeriesPoint[]; fmtLabel: (r: string) => string; onPick: (i: number) => void; noData: string }) {
  const pts = series || [];
  const n = pts.length;
  if (!n) return <div style={{ height: 250, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)", fontSize: 13 }}>{noData}</div>;
  const sales = pts.map((p) => p.sales);
  const profit = pts.map((p) => p.profit);
  const top = nice(Math.max(1, ...sales));
  const bottom = Math.min(0, ...profit);
  const bnice = bottom < 0 ? -nice(-bottom) : 0;     // manfiy foydani ham ko'rsatamiz
  const span = top - bnice;
  const px = (i: number) => (n <= 1 ? 50 : (i / (n - 1)) * 100);
  const py = (v: number) => ((top - v) / span) * 100;
  const salesD = smooth(sales.map((v, i) => [px(i), py(v)]));
  const profitD = smooth(profit.map((v, i) => [px(i), py(v)]));
  const zeroY = py(0);
  const areaD = salesD + ` L 100 ${zeroY.toFixed(2)} L 0 ${zeroY.toFixed(2)} Z`;
  const yTicks = [0, 1, 2, 3, 4].map((k) => { const val = top - (span * k) / 4; return { top: `${(k / 4) * 100}%`, label: fmtShort(val) }; });
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
        {pts.map((_p, i) => (
          <div key={"h" + i} onClick={() => onPick(i)} title={fmtShort(sales[i])} style={{ position: "absolute", left: `${px(i)}%`, top: 0, bottom: 0, width: `${100 / n}%`, transform: "translateX(-50%)", cursor: "pointer" }} />
        ))}
        {pts.map((_p, i) => (
          <div key={"d" + i} style={{ position: "absolute", left: `${px(i)}%`, top: `${py(sales[i])}%`, width: 11, height: 11, borderRadius: "50%", background: "var(--card)", border: "2.5px solid #8b7ff0", transform: "translate(-50%,-50%)", pointerEvents: "none" }} />
        ))}
        {pts.map((p, i) => (
          <div key={"l" + i} style={{ position: "absolute", left: `${px(i)}%`, bottom: -24, transform: "translateX(-50%)", fontSize: 11.5, color: "var(--muted)", fontWeight: 500, whiteSpace: "nowrap", pointerEvents: "none" }}>{fmtLabel(p.label)}</div>
        ))}
      </div>
    </div>
  );
}

// ── Kunlik moliyaviy hisobot (P&L) — 100% REAL per-bucket ma'lumot ──
function DayReport({ pt, period, vatOn, vatRate, store, fmtLabel, onClose, t }: { pt: SeriesPoint; period: Period; vatOn: boolean; vatRate: number; store: string; fmtLabel: (r: string) => string; onClose: () => void; t: Tr }) {
  const r = useMemo(() => {
    const netRev = pt.subtotal - pt.discount - pt.returns;
    const grossProfit = netRev - pt.cost;
    const vat = vatOn && vatRate ? Math.round(netRev * vatRate / (100 + vatRate)) : 0;
    const avg = pt.tx ? Math.round(pt.sales / pt.tx) : 0;
    return { netRev, grossProfit, vat, avg };
  }, [pt, vatOn, vatRate]);
  const title = period === "day" ? t("dash.rep.hourly") : period === "month" ? t("dash.rep.weekly") : t("dash.rep.daily");
  const rows: { label: string; raw: number; strong?: boolean; ok?: boolean; muted?: boolean }[] = [
    { label: t("dash.finGross"), raw: pt.subtotal },
    ...(pt.discount ? [{ label: t("dash.finDiscount"), raw: -pt.discount }] : []),
    ...(pt.returns ? [{ label: t("dash.finReturns"), raw: -pt.returns }] : []),
    { label: t("dash.finNetRev"), raw: r.netRev, strong: true },
    { label: t("dash.finCogs"), raw: -pt.cost },
    { label: t("dash.grossProfit"), raw: r.grossProfit, strong: true, ok: true },
    ...(r.vat ? [{ label: t("dash.finVat", { rate: vatRate }), raw: r.vat, muted: true }] : []),
  ];
  const payEntries: [string, number][] = [["cash", pt.pays.cash], ["card", pt.pays.card], ["qr", pt.pays.qr]];
  const payList: [string, number][] = payEntries.filter((x) => x[1] > 0);
  if (pt.pays.credit > 0) payList.push(["credit", pt.pays.credit]);
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 40, background: "rgba(5,8,14,0.62)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 560, maxHeight: "86vh", background: "var(--card)", border: "1px solid var(--border)", borderRadius: 20, boxShadow: "0 24px 60px rgba(0,0,0,0.45)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ padding: "22px 24px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div><div style={{ fontSize: 19, fontWeight: 800, letterSpacing: "-0.02em" }}>{title}</div><div style={{ fontSize: 13, color: "var(--muted)", marginTop: 3 }}>{fmtLabel(pt.label)} · {store}</div></div>
          <button onClick={onClose} style={{ width: 34, height: 34, border: "none", background: "var(--border)", borderRadius: 9, cursor: "pointer", color: "var(--text3)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={16} /></button>
        </div>
        <div className="scroll" style={{ padding: "20px 24px", overflowY: "auto" }}>
          <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
            <div style={{ flex: 1, background: "var(--surface-accent)", borderRadius: 13, padding: "14px 16px" }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("branch.kpi.revenue")}</div><div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 3 }}>{fmt(pt.sales)}</div></div>
            <div style={{ flex: 1, background: "var(--ok-soft)", borderRadius: 13, padding: "14px 16px" }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("dash.grossProfit")}</div><div className="tabular" style={{ fontSize: 22, fontWeight: 800, marginTop: 3, color: "var(--ok)" }}>{fmt(r.grossProfit)}</div></div>
          </div>
          <div style={{ display: "flex", gap: 24, fontSize: 12.5, color: "var(--muted)", marginBottom: 18 }}><span>{t("dash.receipts")}: <b style={{ color: "var(--text2)" }}>{pt.tx}</b></span><span>{t("dash.avgCheck")}: <b style={{ color: "var(--text2)" }}>{fmt(r.avg)}</b></span></div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>{t("dash.finReport")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginBottom: 20 }}>
            {rows.map((x, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "10px 14px", borderRadius: 9, background: x.strong ? "var(--surface)" : "transparent", fontSize: 13.5 }}>
                <span style={{ color: x.strong ? "var(--text)" : x.muted ? "var(--muted)" : "var(--text3)", fontWeight: x.strong ? 700 : 500 }}>{x.label}</span>
                <span className="tabular" style={{ fontWeight: x.strong ? 700 : 500, color: x.ok ? "var(--ok)" : x.raw < 0 ? "var(--text3)" : "var(--text)" }}>{x.raw < 0 ? "−" : ""}{fmt(Math.abs(x.raw))}</span>
              </div>
            ))}
          </div>
          {payList.length > 0 && <>
            <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 10 }}>{t("branch.payMethods")}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {payList.map(([m, amt]) => (<div key={m} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13.5 }}><span style={{ display: "flex", alignItems: "center", gap: 8 }}><span style={{ width: 9, height: 9, borderRadius: "50%", background: METHOD_COLOR[m] || "var(--muted)" }} />{m === "credit" ? t("dash.creditUnpaid") : t("pay." + m)}</span><span className="tabular" style={{ fontWeight: 600 }}>{fmt(amt)}</span></div>))}
            </div>
          </>}
        </div>
        <div style={{ padding: "16px 24px", borderTop: "1px solid var(--border)", display: "flex", gap: 10 }}>
          <button onClick={() => { try { window.print(); } catch { /* ignore */ } }} className="btn btn-ghost" style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 18px", height: 48, fontSize: 14 }}><Printer size={17} />{t("dash.print")}</button>
          <button onClick={() => exportDayCsv(pt, r, fmtLabel, t)} className="btn btn-primary" style={{ flex: 1, height: 48, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, fontSize: 14 }}><DownloadSimple size={17} />{t("dash.exportCsv")}</button>
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
function exportOverviewCsv(ov: Overview, period: string, t: Tr) {
  const out: (string | number)[][] = [["SavdoOS — " + t("dash.report"), t("dash.period." + period)], ["", ""]];
  out.push([t("branch.kpi.revenue"), Math.round(ov.kpi.sales)], [t("dash.grossProfit"), Math.round(ov.kpi.profit)], [t("dash.transactions"), ov.kpi.tx], [t("dash.avgCheck"), Math.round(ov.kpi.avg_check)], ["", ""]);
  out.push([t("dash.topSold"), ""]);
  ov.top_products.forEach((p) => out.push([p.name, Math.round(p.revenue)]));
  downloadCsv(`hisobot_${period}.csv`, out);
}
function exportDayCsv(pt: SeriesPoint, r: { netRev: number; grossProfit: number; vat: number; avg: number }, fmtLabel: (s: string) => string, t: Tr) {
  const out: (string | number)[][] = [["SavdoOS — " + t("dash.finReport"), fmtLabel(pt.label)], ["", ""]];
  out.push([t("dash.finGross"), pt.subtotal]);
  if (pt.discount) out.push([t("dash.finDiscount"), -pt.discount]);
  if (pt.returns) out.push([t("dash.finReturns"), -pt.returns]);
  out.push([t("dash.finNetRev"), r.netRev], [t("dash.finCogs"), -pt.cost], [t("dash.grossProfit"), r.grossProfit]);
  if (r.vat) out.push([t("dash.finVat", { rate: "" }).replace("()", ""), r.vat]);
  out.push(["", ""], [t("dash.receipts"), pt.tx], [t("dash.avgCheck"), r.avg]);
  downloadCsv(`hisobot_${pt.label}.csv`, out);
}
