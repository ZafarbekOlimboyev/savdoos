import { fmt } from "@/lib/format";
import { Topbar, td, th, useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";

// Ega/menejer NAZORATI: barcha kassirlar smenаsi (faqat ko'rish). O'z smenasini
// ochish emas — bu POS (kassir) ishi. Bu yerda kassa farqlarini kuzatasiz.
interface ShiftRow {
  id: string; cashier: string; branch: string | null;
  opened_at: string; closed_at: string | null;
  opening_cash: number; sales: number; receipts: number;
  expected: number; counted: number | null; difference: number | null;
  status: string;
}

function tm(s: string | null): string {
  if (!s) return "—";
  // SQLite (dev) tz belgisisiz UTC string berishi mumkin — 'Z' qo'shamiz (prod'da '+00:00' keladi)
  const d = new Date(/[Z+]|[+-]\d\d:\d\d$/.test(s.slice(10)) ? s : s + "Z");
  return isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function ShiftOversight() {
  const { data, err } = useGet<{ shifts: ShiftRow[]; open_count: number }>("/shifts/overview");
  const t = useT();
  const shifts = data?.shifts || [];
  const openCount = data?.open_count || 0;
  const diffCount = shifts.filter((s) => s.status !== "open" && (s.difference || 0) !== 0).length;

  const kpi = [
    { label: t("shift.openShifts"), value: openCount, color: "var(--ok)" },
    { label: t("shift.totalShifts"), value: shifts.length, color: "var(--text)" },
    { label: t("shift.withDiff"), value: diffCount, color: diffCount ? "var(--danger)" : "var(--text)" },
  ];

  return (
    <main className="main">
      <Topbar title={t("nav.smena")} sub={t("shift.oversightSub")} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {err && <div style={{ color: "var(--red)", marginBottom: 12 }}>{err}</div>}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16, marginBottom: 18 }}>
          {kpi.map((k) => (
            <div key={k.label} className="card" style={{ padding: "15px 18px" }}>
              <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{k.label}</div>
              <div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 6, color: k.color }}>{k.value}</div>
            </div>
          ))}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--card-alt)" }}>
                <th style={th}>{t("shift.thCashier")}</th>
                <th style={th}>{t("emp.thBranch")}</th>
                <th style={th}>{t("shift.thOpened")}</th>
                <th style={th}>{t("shift.thClosed")}</th>
                <th style={{ ...th, textAlign: "right" }}>{t("shift.thSales")}</th>
                <th style={{ ...th, textAlign: "right" }}>{t("shift.expectedCash")}</th>
                <th style={{ ...th, textAlign: "right" }}>{t("shift.thCounted")}</th>
                <th style={{ ...th, textAlign: "right" }}>{t("shift.thDiff")}</th>
                <th style={th}>{t("emp.thStatus")}</th>
              </tr>
            </thead>
            <tbody>
              {shifts.length === 0 && (
                <tr><td style={{ ...td, color: "var(--muted)" }} colSpan={9}>{t("shift.noShifts")}</td></tr>
              )}
              {shifts.map((s) => {
                const isOpen = s.status === "open";
                const diff = s.difference || 0;
                const diffColor = isOpen ? "var(--muted)" : diff < 0 ? "var(--danger)" : "var(--ok)";
                return (
                  <tr key={s.id}>
                    <td style={{ ...td, fontWeight: 600 }}>{s.cashier}</td>
                    <td style={{ ...td, color: "var(--text3)" }}>{s.branch || "—"}</td>
                    <td style={{ ...td, color: "var(--text3)" }} className="tabular">{tm(s.opened_at)}</td>
                    <td style={{ ...td, color: "var(--text3)" }} className="tabular">{tm(s.closed_at)}</td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 600 }} className="tabular">{fmt(s.sales)}</td>
                    <td style={{ ...td, textAlign: "right" }} className="tabular">{fmt(s.expected)}</td>
                    <td style={{ ...td, textAlign: "right" }} className="tabular">{isOpen ? "—" : fmt(s.counted || 0)}</td>
                    <td style={{ ...td, textAlign: "right", fontWeight: 700, color: diffColor }} className="tabular">{isOpen ? "—" : (diff > 0 ? "+" : diff < 0 ? "−" : "") + fmt(Math.abs(diff))}</td>
                    <td style={td}>
                      <span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 11px", borderRadius: 9, background: isOpen ? "var(--ok-soft)" : "var(--border)", color: isOpen ? "var(--ok)" : "var(--text3)" }}>
                        {isOpen ? t("shift.open") : t("shift.statusClosed")}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
