import { useState } from "react";
import {
  Buildings,
  ChartLineUp,
  CrownSimple,
  ListBullets,
  LockKey,
  MapPin,
  Plus,
  SquaresFour,
  UsersThree,
} from "@phosphor-icons/react";
import { fmt } from "@/lib/format";
import { Topbar, Modal } from "@/components/ui";
import { useT } from "@/lib/i18n";

// Do'kon tarmog'i — dizayn prototipi (Filiallar.dc.html) asosida.
// Ro'yxat (jadval) va karta ko'rinishi o'rtasida almashtirish mumkin (o'ng yuqori burchakdagi ikonka).
type Branch = { name: string; address: string; cashiers: number; sales: number };

const BRANCHES: Branch[] = [
  { name: "Chilonzor", address: "Chilonzor t., Bunyodkor ko'chasi 12", cashiers: 5, sales: 4250000 },
  { name: "Yunusobod", address: "Yunusobod t., Amir Temur 88", cashiers: 4, sales: 3100000 },
  { name: "Sergeli", address: "Sergeli t., Yangi yo'l 5", cashiers: 3, sales: 2340000 },
];

const VIEW_KEY = "savdoos_filiallar_view";

export function Filiallar() {
  const t = useT();
  const [view, setView] = useState<"list" | "card">(() => {
    try { return localStorage.getItem(VIEW_KEY) === "card" ? "card" : "list"; } catch { return "list"; }
  });
  const [limitOpen, setLimitOpen] = useState(false);

  const setViewMode = (v: "list" | "card") => {
    setView(v);
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* ignore */ }
  };

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
        {/* Summary */}
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

        {view === "list" ? <ListView t={t} /> : <CardView t={t} />}
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

function ViewToggle({ view, onChange, t }: { view: "list" | "card"; onChange: (v: "list" | "card") => void; t: (k: string, vars?: Record<string, string | number>) => string }) {
  const btn = (mode: "list" | "card", Icon: typeof ListBullets, label: string) => {
    const on = view === mode;
    return (
      <button
        title={label}
        aria-label={label}
        onClick={() => onChange(mode)}
        style={{
          width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center",
          border: "none", borderRadius: 9, cursor: "pointer",
          background: on ? "var(--card)" : "transparent",
          color: on ? "var(--accent-strong)" : "var(--muted)",
          boxShadow: on ? "0 1px 3px rgba(0,0,0,0.12)" : "none",
        }}
      >
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

function StatusPill({ t }: { t: (k: string, vars?: Record<string, string | number>) => string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 600, color: "var(--ok)" }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--ok)" }} />{t("filiallar.active")}
    </span>
  );
}

function ListView({ t }: { t: (k: string, vars?: Record<string, string | number>) => string }) {
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
          {BRANCHES.map((b) => (
            <tr key={b.name}>
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

function CardView({ t }: { t: (k: string, vars?: Record<string, string | number>) => string }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
      {BRANCHES.map((b) => (
        <div key={b.name} className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
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
