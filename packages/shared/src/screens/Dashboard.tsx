import { ClockCountdown, Package, Prohibit, Warning, CaretRight } from "@phosphor-icons/react";
import { fmt, fmtShort } from "@/lib/format";
import { useAuth } from "@/store/auth";
import { readPrefs } from "@/lib/prefs";
import { Topbar, useGet } from "@/components/ui";
import { statusOf } from "@/lib/status";
import { useT } from "@/lib/i18n";

interface Dash {
  today_sales: number;
  today_profit: number;
  debt: { total: number; debtors: number; paid_today: number };
  low_stock: { name: string; qty: number; min: number }[];
  weekly: { day: string; sales: number }[];
  payments: { method: string; amount: number }[];
}
interface Product { stock: number; min_stock: number; expiry_date: string | null }

const METHOD: Record<string, [string, string]> = {
  cash: ["Naqd", "#2ec77e"], card: ["Karta", "#8b7ff0"], qr: ["QR", "#2bc4c4"], credit: ["Qarz", "var(--warn)"],
};

export function Dashboard() {
  const { data, err } = useGet<Dash>("/reports/dashboard");
  const prods = useGet<Product[]>("/products");
  const employee = useAuth((s) => s.employee);
  const prefs = readPrefs();
  const t = useT();
  const DOW = [t("dow.0"), t("dow.1"), t("dow.2"), t("dow.3"), t("dow.4"), t("dow.5"), t("dow.6")];

  const wk = data?.weekly || [];
  const maxWk = Math.max(1, ...wk.map((w) => w.sales));
  const totalPay = Math.max(1, (data?.payments || []).reduce((t, p) => t + p.amount, 0));

  // "E'tibor" sanagichlari — Products bilan YAGONA statusOf formulasi (har mahsulot bitta toifada)
  const list = prods.data || [];
  const att = { soon: 0, low: 0, near: 0, expired: 0 };
  list.forEach((p) => {
    const st = statusOf(p);
    if (st === "expired") att.expired++;
    else if (st === "soon") att.soon++;
    else if (st === "low") att.low++;
    if (st === "out") att.near++;
  });
  const ATT = [
    { key: "soon", label: t("dash.att_soon"), n: att.soon, Icon: ClockCountdown, color: "var(--warn)", soft: "var(--warn-soft)" },
    { key: "low", label: t("dash.att_low"), n: att.low, Icon: Package, color: "#3b82f6", soft: "var(--info-soft)" },
    { key: "near", label: t("dash.att_near"), n: att.near, Icon: Warning, color: "var(--warn)", soft: "var(--warn-soft)" },
    { key: "expired", label: t("dash.att_expired"), n: att.expired, Icon: Prohibit, color: "var(--danger)", soft: "var(--danger-soft)" },
  ];

  // Chiziqli grafik pathlari
  const n = wk.length;
  const px = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * 100);
  const py = (v: number) => 96 - (v / maxWk) * 86;
  const lineD = n === 1
    ? `M 0 ${py(wk[0].sales).toFixed(1)} L 100 ${py(wk[0].sales).toFixed(1)}`
    : wk.map((w, i) => `${i === 0 ? "M" : "L"} ${px(i).toFixed(1)} ${py(w.sales).toFixed(1)}`).join(" ");
  const areaD = n ? `${lineD} L 100 100 L 0 100 Z` : "";

  return (
    <main className="main">
      <Topbar title={t("dash.title")} sub={t("dash.welcome", { name: employee?.full_name || "" })} />
      <div className="scroll" style={{ flex: 1, padding: 28 }}>
        {err && <div style={{ color: "var(--red)", marginBottom: 16 }}>{t("dash.serverErr")}: {err}</div>}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 18 }}>
          <Kpi label={t("dash.todaySales")} value={data ? fmt(data.today_sales) : "—"} color="var(--accent-strong)" />
          <Kpi label={t("dash.todayProfit")} value={data ? fmt(data.today_profit) : "—"} color="var(--ok)" />
          <Kpi label={t("dash.debtors")} value={data ? String(data.debt.debtors) : "—"} color="var(--warn)" note={t("dash.creditNote")} />
          <Kpi label={t("dash.paidToday")} value={data ? fmt(data.debt.paid_today) : "—"} color="var(--ok)" note={t("dash.paidTodayNote")} />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 18 }}>
          {/* Chiziqli grafik */}
          <div className="card">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
              <div style={{ fontSize: 16, fontWeight: 700 }}>{t("dash.sales7")}</div>
              <div style={{ display: "flex", gap: 14, fontSize: 12, color: "var(--muted)" }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span style={{ width: 10, height: 3, borderRadius: 2, background: "#8b7ff0" }} />{t("dash.salesLegend")}</span>
              </div>
            </div>
            {n === 0 ? (
              <div style={{ color: "var(--muted)", fontSize: 13, height: 220, display: "flex", alignItems: "center", justifyContent: "center" }}>{t("dash.noSalesYet")}</div>
            ) : (
              <>
                <div style={{ position: "relative", height: 230 }}>
                  <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: "100%", height: "100%", overflow: "visible" }}>
                    <defs>
                      <linearGradient id="dashArea" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#8b7ff0" stopOpacity="0.32" />
                        <stop offset="100%" stopColor="#8b7ff0" stopOpacity="0" />
                      </linearGradient>
                    </defs>
                    {[0, 25, 50, 75, 100].map((y) => <line key={y} x1="0" y1={y} x2="100" y2={y} stroke="var(--border)" strokeWidth="0.4" />)}
                    <path d={areaD} fill="url(#dashArea)" />
                    <path d={lineD} fill="none" stroke="#8b7ff0" strokeWidth="1" vectorEffect="non-scaling-stroke" style={{ strokeWidth: 3 }} />
                  </svg>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
                  {wk.map((w, i) => {
                    const d = new Date(w.day + "T00:00:00");
                    return <div key={i} style={{ flex: 1, textAlign: "center", fontSize: 11, color: "var(--muted)" }}>
                      <div className="tabular" style={{ fontWeight: 700, color: "var(--text3)" }}>{fmtShort(w.sales)}</div>
                      {DOW[d.getDay()] || ""}
                    </div>;
                  })}
                </div>
              </>
            )}
          </div>

          {/* To'lov usullari */}
          <div className="card">
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>{t("dash.payMethodsToday")}</div>
            {(data?.payments || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("dash.noPayToday")}</div>}
            {(data?.payments || []).map((p) => {
              const m = METHOD[p.method] || [p.method, "var(--muted)"];
              const pct = Math.round((p.amount / totalPay) * 100);
              return (
                <div key={p.method} style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 5 }}>
                    <span style={{ fontWeight: 600 }}>{METHOD[p.method] ? t("pay." + p.method) : p.method}</span>
                    <span className="tabular" style={{ fontWeight: 700 }}>{fmt(p.amount)}</span>
                  </div>
                  <div style={{ height: 8, borderRadius: 4, background: "var(--surface)", overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${pct}%`, background: m[1], borderRadius: 4 }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* E'tibor qaratish kerak */}
        <div className="card" style={{ marginTop: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{t("dash.attention")}</div>
            <a href="#/mahsulotlar" style={{ color: "var(--accent)", fontWeight: 600, fontSize: 13, textDecoration: "none" }}>{t("dash.viewAll")}</a>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
            {ATT.map((a) => (
              <a key={a.key} href="#/mahsulotlar" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 12, padding: 14, borderRadius: 12, background: "var(--surface)" }}>
                <div style={{ width: 40, height: 40, flex: "none", borderRadius: 11, background: a.soft, color: a.color, display: "flex", alignItems: "center", justifyContent: "center" }}><a.Icon size={20} weight="fill" /></div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="tabular" style={{ fontSize: 20, fontWeight: 800, color: "var(--text)" }}>{a.n}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)" }}>{a.label}</div>
                </div>
                <CaretRight size={15} color="var(--faint)" />
              </a>
            ))}
          </div>
        </div>

        {/* Qarz bloki (nasiya yoqilgan bo'lsa) */}
        {prefs.qarz && (
          <div className="card" style={{ marginTop: 18, display: "flex", alignItems: "center", justifyContent: "space-between", borderColor: "var(--warn-border)" }}>
            <div style={{ display: "flex", gap: 36 }}>
              <div><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("cust.totalDebt")}</div><div style={{ fontSize: 22, fontWeight: 800, color: "var(--danger)" }} className="tabular">{data ? fmt(data.debt.total) : "—"}</div></div>
              <div><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("cust.debtors")}</div><div style={{ fontSize: 22, fontWeight: 800 }}>{data?.debt.debtors ?? "—"}</div></div>
              <div><div style={{ fontSize: 13, color: "var(--muted)" }}>{t("dash.paidToday")}</div><div style={{ fontSize: 22, fontWeight: 800, color: "var(--ok)" }} className="tabular">{data ? fmt(data.debt.paid_today) : "—"}</div></div>
            </div>
            <a href="#/mijozlar" style={{ color: "var(--accent)", fontWeight: 600, fontSize: 13, textDecoration: "none" }}>{t("dash.customers")}</a>
          </div>
        )}

        {/* Kam qolgan */}
        <div className="card" style={{ marginTop: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>{t("dash.lowStock")}</div>
            <a href="#/mahsulotlar" style={{ color: "var(--accent)", fontWeight: 600, fontSize: 13, textDecoration: "none" }}>{t("dash.warehouse")}</a>
          </div>
          {(data?.low_stock || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("dash.allEnough")}</div>}
          {(data?.low_stock || []).map((l, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 0", borderTop: i ? "1px solid var(--border-soft)" : "none" }}>
              <span style={{ fontWeight: 600, fontSize: 13.5 }}>{l.name}</span>
              <span style={{ fontWeight: 700, fontSize: 13.5, color: l.qty <= 5 ? "var(--danger)" : "var(--warn)" }} className="tabular">{l.qty} / {l.min} {t("pos.unit")}</span>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}

function Kpi({ label, value, color, note }: { label: string; value: string; color: string; note?: string }) {
  return (
    <div className="card" style={{ padding: "16px 18px" }}>
      <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{label}</div>
      <div className="tabular" style={{ fontSize: 24, fontWeight: 800, color, marginTop: 6, letterSpacing: "-0.02em" }}>{value}</div>
      {note && <div style={{ fontSize: 11.5, color: "var(--faint)", marginTop: 3 }}>{note}</div>}
    </div>
  );
}
