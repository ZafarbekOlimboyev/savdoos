import { useMemo, useState } from "react";
import {
  ArrowLeft,
  Buildings,
  ChartLineUp,
  Clock,
  CreditCard,
  CrownSimple,
  Lightbulb,
  ListBullets,
  LockKey,
  MapPin,
  Medal,
  Money,
  Package,
  Plus,
  SquaresFour,
  Tag,
  TrendDown,
  TrendUp,
  UsersThree,
  Warning,
} from "@phosphor-icons/react";
import { fmt, fmtShort } from "@/lib/format";
import { Topbar, Modal } from "@/components/ui";
import { useT } from "@/lib/i18n";

// Do'kon tarmog'i + filial analitikasi — dizayn prototipi (Filiallar.dc.html) + BILLZ uslubidagi P&L.
type T = (k: string, vars?: Record<string, string | number>) => string;
type Branch = { name: string; address: string; cashiers: number; sales: number };

const BRANCHES: Branch[] = [
  { name: "Chilonzor", address: "Chilonzor t., Bunyodkor ko'chasi 12", cashiers: 5, sales: 4250000 },
  { name: "Yunusobod", address: "Yunusobod t., Amir Temur 88", cashiers: 4, sales: 3100000 },
  { name: "Sergeli", address: "Sergeli t., Yangi yo'l 5", cashiers: 3, sales: 2340000 },
];

const VIEW_KEY = "savdoos_filiallar_view";
type Period = "today" | "week" | "month";
const PERIOD_MULT: Record<Period, number> = { today: 1, week: 6.8, month: 28.5 };

const CASHIER_NAMES = [
  ["Aziza K.", "Bekzod T.", "Dilnoza R.", "Sardor M.", "Nodira A."],
  ["Kamola S.", "Jasur X.", "Malika N.", "Rustam B."],
  ["Umid Q.", "Feruza O.", "Sherzod A."],
];
const TOP_PRODUCTS = ["Mol go'shti", "Sut 1L", "Non", "Coca-Cola 0.5L", "Pishloq"];
const PEAK_W = [0.35, 0.5, 0.72, 0.88, 0.64, 0.52, 0.6, 0.78, 0.92, 1.0, 0.82, 0.54]; // 10:00..21:00

type Analytics = ReturnType<typeof analytics>;

function analytics(b: Branch, i: number, period: Period) {
  const mult = PERIOD_MULT[period];
  const revenue = Math.round(b.sales * mult);
  const cogs = Math.round(revenue * (0.6 + i * 0.02));
  const grossProfit = revenue - cogs;
  const discounts = Math.round(revenue * (0.03 + i * 0.006));
  const returns = Math.round(revenue * (0.015 + i * 0.008));
  const opex = Math.round(revenue * (0.135 + i * 0.012));
  const netProfit = grossProfit - discounts - returns - opex;
  const margin = revenue ? netProfit / revenue : 0;
  const avgCheck = 52000 + i * 9000;
  const receipts = Math.max(1, Math.round(revenue / avgCheck));
  const avgItems = 3.6 + i * 0.5;
  const units = Math.round(receipts * avgItems);
  const growth = [12.4, -3.1, 7.8][i] ?? 5;
  const stockValue = Math.round(b.sales * (5.5 + i));

  // To'lov usullari (%)
  const payRaw = [
    { key: "cash", pct: 46 - i * 3 },
    { key: "card", pct: 32 + i * 2 },
    { key: "qr", pct: 13 + i },
    { key: "credit", pct: 9 },
  ];
  const paySum = payRaw.reduce((s, p) => s + p.pct, 0);
  const pay = payRaw.map((p) => ({ ...p, pct: Math.round((p.pct / paySum) * 100), amount: Math.round((p.pct / paySum) * revenue) }));

  // 7 kunlik trend
  const shape = [0.68, 0.55, 0.82, 1.0, 0.62, 0.9, 0.74];
  const perDay = revenue / shape.reduce((s, x) => s + x, 0);
  const trend = shape.map((x) => Math.round(x * perDay));

  // Top mahsulotlar
  const shares = [0.3, 0.24, 0.19, 0.15, 0.12];
  const products = TOP_PRODUCTS.map((name, k) => ({
    name,
    revenue: Math.round(revenue * shares[(k + i) % shares.length] * 0.55),
    margin: Math.round((22 + ((k * 7 + i * 5) % 18))),
  })).sort((a, b2) => b2.revenue - a.revenue);

  // Kassirlar
  const names = (CASHIER_NAMES[i] || CASHIER_NAMES[0]).slice(0, b.cashiers);
  const wsum = names.reduce((s, _n, k) => s + (names.length - k), 0);
  const cashiers = names.map((name, k) => ({ name, sales: Math.round(revenue * ((names.length - k) / wsum)) }));

  // Peak soatlar
  const peakSum = PEAK_W.reduce((s, x) => s + x, 0);
  const peak = PEAK_W.map((w, h) => ({ hour: 10 + h, amount: Math.round(revenue * (w / peakSum)) }));
  const peakHour = 10 + PEAK_W.indexOf(Math.max(...PEAK_W));

  return {
    revenue, cogs, grossProfit, discounts, returns, opex, netProfit, margin,
    avgCheck, receipts, avgItems, units, growth, stockValue,
    pay, trend, products, cashiers, peak, peakHour,
  };
}

export function Filiallar() {
  const t = useT();
  const [view, setView] = useState<"list" | "card">(() => {
    try { return localStorage.getItem(VIEW_KEY) === "card" ? "card" : "list"; } catch { return "list"; }
  });
  const [limitOpen, setLimitOpen] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  const setViewMode = (v: "list" | "card") => {
    setView(v);
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* ignore */ }
  };

  if (selected !== null) {
    return <BranchDetail branch={BRANCHES[selected]} index={selected} onBack={() => setSelected(null)} t={t} />;
  }

  const total = BRANCHES.length;
  const totalCashiers = BRANCHES.reduce((s, b) => s + b.cashiers, 0);
  const totalSales = BRANCHES.reduce((s, b) => s + b.sales, 0);

  const stats = [
    { icon: <Buildings size={21} />, bg: "var(--accent-soft)", fg: "var(--accent-strong)", value: total, label: t("filiallar.totalBranches") },
    { icon: <UsersThree size={21} />, bg: "var(--ok-soft)", fg: "var(--ok)", value: totalCashiers, label: t("filiallar.totalCashiers") },
    { icon: <ChartLineUp size={21} />, bg: "var(--surface-accent)", fg: "var(--accent-strong)", value: fmt(totalSales), label: t("filiallar.todaySales") },
  ];

  return (
    <main className="main">
      <Topbar
        title={t("nav.filiallar")}
        sub={`${t("filiallar.sub")} · ${t("filiallar.activeCount", { n: total })}`}
        right={
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <ViewToggle view={view} onChange={setViewMode} t={t} />
            <button className="btn btn-primary" style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 20px" }} onClick={() => setLimitOpen(true)}>
              <Plus size={16} weight="bold" />{t("filiallar.newBranch")}
            </button>
          </div>
        }
      />

      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16, marginBottom: 20 }}>
          {stats.map((s) => (
            <div key={s.label} className="card" style={{ padding: "15px 18px", display: "flex", alignItems: "center", gap: 14 }}>
              <div style={{ width: 42, height: 42, flex: "none", borderRadius: 11, background: s.bg, color: s.fg, display: "flex", alignItems: "center", justifyContent: "center" }}>{s.icon}</div>
              <div>
                <div className="tabular" style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1 }}>{s.value}</div>
                <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4 }}>{s.label}</div>
              </div>
            </div>
          ))}
        </div>

        {view === "list"
          ? <ListView t={t} onSelect={setSelected} />
          : <CardView t={t} onSelect={setSelected} />}
      </div>

      {limitOpen && (
        <Modal onClose={() => setLimitOpen(false)} width={432}>
          <div style={{ textAlign: "center", padding: "4px 2px 2px" }}>
            <div style={{ width: 60, height: 60, margin: "0 auto 16px", borderRadius: 15, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <LockKey size={30} weight="fill" />
            </div>
            <div style={{ fontSize: 19, fontWeight: 800, letterSpacing: "-0.02em" }}>{t("filiallar.limitTitle")}</div>
            <div style={{ fontSize: 14, color: "var(--text3)", marginTop: 10, lineHeight: 1.6 }}>{t("filiallar.limitBody")}</div>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
            <button onClick={() => setLimitOpen(false)} style={{ flex: 1, height: 50, border: "1px solid var(--border-input)", background: "var(--card)", borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14, fontWeight: 600, color: "var(--text3)" }}>{t("common.cancel")}</button>
            <button onClick={() => setLimitOpen(false)} style={{ flex: 1.4, height: 50, border: "none", background: "var(--accent)", borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14, fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
              <CrownSimple size={17} weight="fill" />{t("filiallar.seePlans")}
            </button>
          </div>
        </Modal>
      )}
    </main>
  );
}

/* ─────────────────────────  RO'YXAT / KARTA  ───────────────────────── */

function ViewToggle({ view, onChange, t }: { view: "list" | "card"; onChange: (v: "list" | "card") => void; t: T }) {
  const btn = (mode: "list" | "card", Icon: typeof ListBullets, label: string) => {
    const on = view === mode;
    return (
      <button title={label} aria-label={label} onClick={() => onChange(mode)}
        style={{ width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", border: "none", borderRadius: 9, cursor: "pointer", background: on ? "var(--card)" : "transparent", color: on ? "var(--accent-strong)" : "var(--muted)", boxShadow: on ? "0 1px 3px rgba(0,0,0,0.12)" : "none" }}>
        <Icon size={19} weight={on ? "fill" : "regular"} />
      </button>
    );
  };
  return (
    <div style={{ display: "flex", gap: 3, padding: 3, borderRadius: 12, background: "var(--surface)", border: "1px solid var(--border)" }}>
      {btn("list", ListBullets, t("filiallar.viewList"))}
      {btn("card", SquaresFour, t("filiallar.viewCard"))}
    </div>
  );
}

function StatusPill({ t }: { t: T }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 600, color: "var(--ok)" }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--ok)" }} />{t("filiallar.active")}
    </span>
  );
}

function ListView({ t, onSelect }: { t: T; onSelect: (i: number) => void }) {
  const cell: React.CSSProperties = { padding: "14px 12px", fontSize: 13.5, borderTop: "1px solid var(--border-soft)" };
  const head: React.CSSProperties = { padding: "14px 12px", fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", textAlign: "left" };
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ background: "var(--card-alt)" }}>
            <th style={{ ...head, paddingLeft: 22 }}>{t("filiallar.colBranch")}</th>
            <th style={head}>{t("filiallar.colAddress")}</th>
            <th style={{ ...head, textAlign: "right" }}>{t("filiallar.colCashiers")}</th>
            <th style={{ ...head, textAlign: "right" }}>{t("filiallar.colSales")}</th>
            <th style={{ ...head, paddingRight: 22 }}>{t("filiallar.colStatus")}</th>
          </tr>
        </thead>
        <tbody>
          {BRANCHES.map((b, i) => (
            <tr key={b.name} className="click-row" onClick={() => onSelect(i)}>
              <td style={{ ...cell, paddingLeft: 22 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ width: 36, height: 36, flex: "none", borderRadius: 10, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15, fontWeight: 700 }}>{b.name.charAt(0)}</div>
                  <span style={{ fontWeight: 600 }}>{b.name}</span>
                </div>
              </td>
              <td style={{ ...cell, color: "var(--text3)" }}>{b.address}</td>
              <td className="tabular" style={{ ...cell, textAlign: "right", color: "var(--text3)" }}>{t("filiallar.cashiersN", { n: b.cashiers })}</td>
              <td className="tabular" style={{ ...cell, textAlign: "right", fontWeight: 700 }}>{fmt(b.sales)}</td>
              <td style={{ ...cell, paddingRight: 22 }}><StatusPill t={t} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CardView({ t, onSelect }: { t: T; onSelect: (i: number) => void }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
      {BRANCHES.map((b, i) => (
        <div key={b.name} className="card click-card" onClick={() => onSelect(i)} style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
            <div style={{ width: 46, height: 46, flex: "none", borderRadius: 12, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 19, fontWeight: 700 }}>{b.name.charAt(0)}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em" }}>{b.name}</div>
              <div style={{ marginTop: 4 }}><StatusPill t={t} /></div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, color: "var(--text3)", lineHeight: 1.4 }}>
            <MapPin size={16} style={{ flex: "none", marginTop: 1, color: "var(--muted)" }} />
            <span>{b.address}</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, borderTop: "1px solid var(--border-soft)", paddingTop: 14 }}>
            <div>
              <div style={{ fontSize: 11.5, color: "var(--muted)", fontWeight: 500 }}>{t("filiallar.colCashiers")}</div>
              <div className="tabular" style={{ fontSize: 15, fontWeight: 700, marginTop: 3 }}>{t("filiallar.cashiersN", { n: b.cashiers })}</div>
            </div>
            <div>
              <div style={{ fontSize: 11.5, color: "var(--muted)", fontWeight: 500 }}>{t("filiallar.colSales")}</div>
              <div className="tabular" style={{ fontSize: 15, fontWeight: 800, marginTop: 3, color: "var(--accent-strong)" }}>{fmt(b.sales)}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ─────────────────────────  ANALITIKA (P&L)  ───────────────────────── */

function BranchDetail({ branch, index, onBack, t }: { branch: Branch; index: number; onBack: () => void; t: T }) {
  const [period, setPeriod] = useState<Period>("month");
  const a = useMemo(() => analytics(branch, index, period), [branch, index, period]);

  return (
    <main className="main">
      <div className="topbar">
        <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
          <button onClick={onBack} aria-label={t("branch.back")} title={t("branch.back")}
            style={{ width: 42, height: 42, flex: "none", display: "flex", alignItems: "center", justifyContent: "center", border: "1px solid var(--border)", borderRadius: 11, background: "var(--card)", color: "var(--text2)", cursor: "pointer" }}>
            <ArrowLeft size={19} weight="bold" />
          </button>
          <div style={{ width: 44, height: 44, flex: "none", borderRadius: 12, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 19, fontWeight: 700 }}>{branch.name.charAt(0)}</div>
          <div style={{ minWidth: 0 }}>
            <div className="h1" style={{ display: "flex", alignItems: "center", gap: 10 }}>{branch.name}<StatusPill t={t} /></div>
            <div className="sub" style={{ display: "flex", alignItems: "center", gap: 6 }}><MapPin size={13} />{branch.address}</div>
          </div>
        </div>
        <PeriodSelector value={period} onChange={setPeriod} t={t} />
      </div>

      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {/* KPI */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14, marginBottom: 18 }}>
          <Kpi label={t("branch.kpi.revenue")} value={fmt(a.revenue)} growth={a.growth} t={t} />
          <Kpi label={t("branch.kpi.netProfit")} value={fmt(a.netProfit)} color="var(--ok)" growth={a.growth} t={t} />
          <Kpi label={t("branch.kpi.margin")} value={`${(a.margin * 100).toFixed(1)}%`} color={a.margin < 0.1 ? "var(--warn)" : "var(--text)"} />
          <Kpi label={t("branch.kpi.avgCheck")} value={fmt(a.avgCheck)} />
          <Kpi label={t("branch.kpi.receipts")} value={a.receipts.toLocaleString("ru-RU")} />
          <Kpi label={t("branch.kpi.units")} value={a.units.toLocaleString("ru-RU")} note={`${a.avgItems.toFixed(1)} ${t("branch.perUnit")}`} />
        </div>

        {/* P&L + trend/insights */}
        <div style={{ display: "grid", gridTemplateColumns: "1.05fr 1fr", gap: 16, marginBottom: 16, alignItems: "start" }}>
          <PnLCard a={a} t={t} />
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <TrendCard a={a} t={t} />
            <InsightsCard a={a} index={index} t={t} />
          </div>
        </div>

        {/* Bo'linmalar */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
          <PayCard a={a} t={t} />
          <TopProductsCard a={a} t={t} />
          <CashiersCard a={a} t={t} />
          <PeakHoursCard a={a} t={t} />
        </div>
      </div>
    </main>
  );
}

function PeriodSelector({ value, onChange, t }: { value: Period; onChange: (p: Period) => void; t: T }) {
  const opts: [Period, string][] = [["today", t("branch.period.today")], ["week", t("branch.period.week")], ["month", t("branch.period.month")]];
  return (
    <div style={{ display: "flex", gap: 3, padding: 3, borderRadius: 11, background: "var(--surface)", border: "1px solid var(--border)" }}>
      {opts.map(([k, lab]) => {
        const on = value === k;
        return (
          <button key={k} onClick={() => onChange(k)}
            style={{ padding: "8px 16px", border: "none", borderRadius: 8, cursor: "pointer", font: "inherit", fontSize: 13, fontWeight: 600, background: on ? "var(--card)" : "transparent", color: on ? "var(--accent-strong)" : "var(--muted)", boxShadow: on ? "0 1px 3px rgba(0,0,0,0.12)" : "none" }}>
            {lab}
          </button>
        );
      })}
    </div>
  );
}

function Kpi({ label, value, color, growth, note, t }: { label: string; value: string; color?: string; growth?: number; note?: string; t?: T }) {
  const up = (growth ?? 0) >= 0;
  return (
    <div className="card" style={{ padding: "15px 17px" }}>
      <div style={{ fontSize: 12.5, color: "var(--muted)", fontWeight: 500 }}>{label}</div>
      <div className="tabular" style={{ fontSize: 21, fontWeight: 800, letterSpacing: "-0.02em", marginTop: 7, color: color || "var(--text)" }}>{value}</div>
      {growth !== undefined && t && (
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 6, fontSize: 12, fontWeight: 600, color: up ? "var(--ok)" : "var(--danger)" }}>
          {up ? <TrendUp size={13} weight="bold" /> : <TrendDown size={13} weight="bold" />}
          {Math.abs(growth).toFixed(1)}% <span style={{ color: "var(--faint)", fontWeight: 500 }}>{t("branch.vsPrev")}</span>
        </div>
      )}
      {note && <div style={{ fontSize: 11.5, color: "var(--faint)", marginTop: 6 }}>{note}</div>}
    </div>
  );
}

function CardBox({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="card" style={{ padding: 18 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 15, fontSize: 14, fontWeight: 700, color: "var(--text2)" }}>
        <span style={{ color: "var(--accent-strong)", display: "flex" }}>{icon}</span>{title}
      </div>
      {children}
    </div>
  );
}

function PnLCard({ a, t }: { a: Analytics; t: T }) {
  const row = (label: string, value: number, kind: "in" | "out" | "sub" | "net") => {
    const sign = kind === "out" ? "−" : kind === "in" ? "" : "";
    const color = kind === "out" ? "var(--danger)" : kind === "net" ? "var(--ok)" : "var(--text)";
    const strong = kind === "sub" || kind === "net";
    return (
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: kind === "net" ? "13px 0 2px" : "9px 0", borderTop: kind === "sub" || kind === "net" ? "1px solid var(--border)" : "none" }}>
        <span style={{ fontSize: kind === "net" ? 14.5 : 13.5, color: kind === "out" ? "var(--text3)" : "var(--text2)", fontWeight: strong ? 700 : 500 }}>{label}</span>
        <span className="tabular" style={{ fontSize: kind === "net" ? 18 : 14, fontWeight: strong ? 800 : 600, color }}>{sign}{fmt(value)}</span>
      </div>
    );
  };
  return (
    <CardBox title={t("branch.pnl.title")} icon={<Money size={17} weight="fill" />}>
      {row(t("branch.pnl.grossRevenue"), a.revenue, "in")}
      {row(t("branch.pnl.cogs"), a.cogs, "out")}
      {row(t("branch.pnl.grossProfit"), a.grossProfit, "sub")}
      {row(t("branch.pnl.discounts"), a.discounts, "out")}
      {row(t("branch.pnl.returns"), a.returns, "out")}
      {row(t("branch.pnl.opex"), a.opex, "out")}
      {row(t("branch.pnl.netProfit"), a.netProfit, "net")}
      <div style={{ marginTop: 12, padding: "10px 14px", borderRadius: 11, background: "var(--ok-soft)", color: "var(--ok)", fontSize: 12.5, fontWeight: 700, display: "flex", justifyContent: "space-between" }}>
        <span>{t("branch.kpi.margin")}</span><span className="tabular">{(a.margin * 100).toFixed(1)}%</span>
      </div>
    </CardBox>
  );
}

function TrendCard({ a, t }: { a: Analytics; t: T }) {
  const max = Math.max(...a.trend);
  return (
    <CardBox title={t("branch.trend")} icon={<ChartLineUp size={17} weight="fill" />}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 96 }}>
        {a.trend.map((v, i) => (
          <div key={i} title={fmt(v)} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
            <div style={{ width: "100%", height: `${Math.round((v / max) * 78)}px`, background: i === a.trend.length - 1 ? "var(--accent)" : "var(--accent-soft)", borderRadius: 6, minHeight: 4 }} />
            <span style={{ fontSize: 10, color: "var(--faint)", fontWeight: 600 }}>{fmtShort(v)}</span>
          </div>
        ))}
      </div>
    </CardBox>
  );
}

function PayCard({ a, t }: { a: Analytics; t: T }) {
  const colors: Record<string, string> = { cash: "var(--ok)", card: "#8b7ff0", qr: "#2bc4c4", credit: "var(--warn)" };
  return (
    <CardBox title={t("branch.payMethods")} icon={<CreditCard size={17} weight="fill" />}>
      <div style={{ display: "flex", height: 10, borderRadius: 6, overflow: "hidden", marginBottom: 14 }}>
        {a.pay.map((p) => <div key={p.key} style={{ width: `${p.pct}%`, background: colors[p.key] }} />)}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
        {a.pay.map((p) => (
          <div key={p.key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 13 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text3)" }}>
              <span style={{ width: 9, height: 9, borderRadius: 3, background: colors[p.key] }} />{t("branch.pay." + p.key)}
            </span>
            <span className="tabular" style={{ fontWeight: 600 }}>{fmt(p.amount)} <span style={{ color: "var(--faint)", fontWeight: 500 }}>· {p.pct}%</span></span>
          </div>
        ))}
      </div>
    </CardBox>
  );
}

function TopProductsCard({ a, t }: { a: Analytics; t: T }) {
  const max = Math.max(...a.products.map((p) => p.revenue));
  return (
    <CardBox title={t("branch.topProducts")} icon={<Package size={17} weight="fill" />}>
      <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
        {a.products.map((p, i) => (
          <div key={p.name}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 5 }}>
              <span style={{ fontWeight: 600, color: "var(--text2)" }}><span style={{ color: "var(--faint)", marginRight: 7 }}>{i + 1}</span>{p.name}</span>
              <span className="tabular" style={{ fontWeight: 700 }}>{fmt(p.revenue)}</span>
            </div>
            <div style={{ height: 6, borderRadius: 3, background: "var(--border)", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${Math.round((p.revenue / max) * 100)}%`, background: "var(--accent)", borderRadius: 3 }} />
            </div>
          </div>
        ))}
      </div>
    </CardBox>
  );
}

function CashiersCard({ a, t }: { a: Analytics; t: T }) {
  const max = Math.max(...a.cashiers.map((c) => c.sales));
  return (
    <CardBox title={t("branch.cashiers")} icon={<UsersThree size={17} weight="fill" />}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {a.cashiers.map((c, i) => (
          <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 11 }}>
            <div style={{ width: 32, height: 32, flex: "none", borderRadius: "50%", background: i === 0 ? "var(--accent)" : "var(--accent-soft)", color: i === 0 ? "#fff" : "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700 }}>{c.name.charAt(0)}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                <span style={{ fontWeight: 600 }}>{c.name}{i === 0 && <Medal size={13} weight="fill" color="var(--warn)" style={{ marginLeft: 6, verticalAlign: "-2px" }} />}</span>
                <span className="tabular" style={{ fontWeight: 700, color: "var(--text3)" }}>{fmtShort(c.sales)}</span>
              </div>
              <div style={{ height: 5, borderRadius: 3, background: "var(--border)", overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${Math.round((c.sales / max) * 100)}%`, background: i === 0 ? "var(--accent)" : "var(--accent-border)", borderRadius: 3 }} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </CardBox>
  );
}

function PeakHoursCard({ a, t }: { a: Analytics; t: T }) {
  const max = Math.max(...a.peak.map((p) => p.amount));
  return (
    <CardBox title={t("branch.peakHours")} icon={<Clock size={17} weight="fill" />}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 92 }}>
        {a.peak.map((p) => {
          const isPeak = p.hour === a.peakHour;
          return (
            <div key={p.hour} title={`${p.hour}:00 · ${fmt(p.amount)}`} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
              <div style={{ width: "100%", height: `${Math.round((p.amount / max) * 70)}px`, background: isPeak ? "var(--accent)" : "var(--accent-soft)", borderRadius: 4, minHeight: 3 }} />
              <span style={{ fontSize: 9, color: isPeak ? "var(--accent-strong)" : "var(--faint)", fontWeight: isPeak ? 700 : 500 }}>{p.hour}</span>
            </div>
          );
        })}
      </div>
    </CardBox>
  );
}

function InsightsCard({ a, index, t }: { a: Analytics; index: number; t: T }) {
  const topCashier = a.cashiers[0];
  const topShare = topCashier ? Math.round((topCashier.sales / a.revenue) * 100) : 0;
  type Ins = { icon: React.ReactNode; text: string; color: string };
  const items: Ins[] = [];
  if (a.growth >= 0) items.push({ icon: <TrendUp size={16} weight="bold" />, color: "var(--ok)", text: t("branch.ins.growthUp", { pct: a.growth.toFixed(1) }) });
  else items.push({ icon: <TrendDown size={16} weight="bold" />, color: "var(--danger)", text: t("branch.ins.growthDown", { pct: Math.abs(a.growth).toFixed(1) }) });
  if (topCashier) items.push({ icon: <Medal size={16} weight="fill" />, color: "var(--accent-strong)", text: t("branch.ins.topCashier", { name: topCashier.name, pct: topShare }) });
  if (a.margin < 0.1) items.push({ icon: <Warning size={16} weight="fill" />, color: "var(--warn)", text: t("branch.ins.marginLow", { pct: (a.margin * 100).toFixed(1) }) });
  else items.push({ icon: <Tag size={16} weight="fill" />, color: "var(--warn)", text: t("branch.ins.discount", { sum: fmt(a.discounts) }) });
  items.push({ icon: <Clock size={16} weight="fill" />, color: "var(--text3)", text: t("branch.ins.peak", { hour: `${a.peakHour}:00` }) });

  return (
    <CardBox title={t("branch.insights")} icon={<Lightbulb size={17} weight="fill" />}>
      <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
        {items.slice(0, 4).map((it, i) => (
          <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10, fontSize: 13, lineHeight: 1.4 }}>
            <span style={{ color: it.color, flex: "none", marginTop: 1 }}>{it.icon}</span>
            <span style={{ color: "var(--text2)" }}>{it.text}</span>
          </div>
        ))}
      </div>
    </CardBox>
  );
}
