import { fmt, fmtShort } from "@/lib/format";
import { useAuth } from "@/store/auth";
import { Stat, Topbar, useGet } from "@/components/ui";

interface Dash {
  today_sales: number;
  today_profit: number;
  debt: { total: number; debtors: number; paid_today: number };
  low_stock: { name: string; qty: number; min: number }[];
  weekly: { day: string; sales: number }[];
  payments: { method: string; amount: number }[];
}

const METHOD: Record<string, [string, string]> = {
  cash: ["Naqd", "#17b26a"], card: ["Karta", "#6d5dd3"], qr: ["QR", "#2b6cb0"], credit: ["Qarz", "#e08a12"],
};
const DOW = ["Yak", "Du", "Se", "Cho", "Pay", "Jum", "Sha"];

export function Dashboard() {
  const { data, err } = useGet<Dash>("/reports/dashboard");
  const employee = useAuth((s) => s.employee);

  const wk = data?.weekly || [];
  const maxWk = Math.max(1, ...wk.map((w) => w.sales));
  const totalPay = Math.max(1, (data?.payments || []).reduce((t, p) => t + p.amount, 0));

  return (
    <main className="main">
      <Topbar title="Boshqaruv paneli" sub={`Xush kelibsiz, ${employee?.full_name || ""}`} />
      <div className="scroll" style={{ flex: 1, padding: 28 }}>
        {err && <div style={{ color: "var(--red)", marginBottom: 16 }}>Server bilan aloqa yo'q: {err}</div>}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 18, marginBottom: 18 }}>
          <Stat label="Bugungi savdo" value={data ? fmt(data.today_sales) : "—"} color="var(--accent)" />
          <Stat label="Bugungi foyda" value={data ? fmt(data.today_profit) : "—"} color="var(--green)" />
          <Stat label="Qarzdor mijozlar" value={data ? String(data.debt.debtors) : "—"} color="#b8730c" note="nasiya hisobi" />
          <Stat label="Bugun to'landi" value={data ? fmt(data.debt.paid_today) : "—"} color="var(--green)" note="qaytarilgan qarz" />
        </div>

        {/* qarz bloki */}
        <div className="card" style={{ marginBottom: 18, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", gap: 36 }}>
            <div><div style={{ fontSize: 13, color: "var(--muted)" }}>Umumiy qarz</div><div style={{ fontSize: 22, fontWeight: 800, color: "var(--red)" }} className="tabular">{data ? fmt(data.debt.total) : "—"}</div></div>
            <div><div style={{ fontSize: 13, color: "var(--muted)" }}>Qarzdorlar</div><div style={{ fontSize: 22, fontWeight: 800 }}>{data?.debt.debtors ?? "—"}</div></div>
          </div>
          <a href="#/mijozlar" style={{ color: "var(--accent)", fontWeight: 600, fontSize: 13, textDecoration: "none" }}>Mijozlar →</a>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 18 }}>
          {/* haftalik grafik */}
          <div className="card">
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 18 }}>Savdo — so'nggi 7 kun</div>
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 10, height: 180 }}>
              {wk.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13, margin: "auto" }}>Hali savdo yo'q — Kassada sinab ko'ring</div>}
              {wk.map((w, i) => {
                const h = Math.round((w.sales / maxWk) * 150);
                const d = new Date(w.day);
                return (
                  <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 8, height: "100%", justifyContent: "flex-end" }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#5b6072", whiteSpace: "nowrap" }}>{fmtShort(w.sales)}</div>
                    <div title={fmt(w.sales)} style={{ width: "70%", maxWidth: 30, borderRadius: "6px 6px 3px 3px", background: "var(--accent)", height: Math.max(4, h) }} />
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>{DOW[d.getDay()] || ""}</div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* to'lov usullari */}
          <div className="card">
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>To'lov usullari (bugun)</div>
            {(data?.payments || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>Bugun to'lov yo'q</div>}
            {(data?.payments || []).map((p) => {
              const m = METHOD[p.method] || [p.method, "#888"];
              const pct = Math.round((p.amount / totalPay) * 100);
              return (
                <div key={p.method} style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 5 }}>
                    <span style={{ fontWeight: 600 }}>{m[0]}</span>
                    <span className="tabular" style={{ fontWeight: 700 }}>{fmt(p.amount)}</span>
                  </div>
                  <div style={{ height: 8, borderRadius: 4, background: "#f1f2f7", overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${pct}%`, background: m[1], borderRadius: 4 }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* kam qolgan */}
        <div className="card" style={{ marginTop: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>Kam qolgan mahsulotlar</div>
            <a href="#/mahsulotlar" style={{ color: "var(--accent)", fontWeight: 600, fontSize: 13, textDecoration: "none" }}>Ombor →</a>
          </div>
          {(data?.low_stock || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>Hammasi yetarli 👍</div>}
          {(data?.low_stock || []).map((l, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "9px 0", borderTop: i ? "1px solid #f4f5f9" : "none" }}>
              <span style={{ fontWeight: 600, fontSize: 13.5 }}>{l.name}</span>
              <span style={{ fontWeight: 700, fontSize: 13.5, color: l.qty <= 5 ? "var(--red)" : "#b8730c" }} className="tabular">{l.qty} / {l.min} dona</span>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}
