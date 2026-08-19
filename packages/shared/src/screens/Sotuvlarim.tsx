import { useEffect, useMemo, useState } from "react";
import { get } from "@/lib/api";
import { fmt } from "@/lib/format";
import { printReceipt } from "@/lib/receipt";
import { useAuth } from "@/store/auth";
import { readPrefs } from "@/lib/prefs";
import { useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";

interface Row { id: string; receipt_no: string; sold_at: string; method: string; item_count: number; total: number }
interface Detail { id: string; receipt_no: string; uid: string | null; total: number; sold_at: string; items: { name_snapshot: string; qty: number; unit_price: number; line_total: number }[] }

const M: Record<string, [string, string, string]> = {
  cash: ["Naqd", "var(--ok-soft)", "var(--ok)"], card: ["Karta", "var(--accent-soft)", "var(--accent-strong)"], qr: ["QR", "var(--info-soft)", "#3b82f6"], credit: ["Qarz", "var(--warn-soft)", "var(--warn)"],
};

function bars(uid: string) {
  const d = (uid || "").replace(/\D/g, "");
  const out: { w: string; bg: string }[] = [{ w: "2px", bg: "var(--text)" }, { w: "2px", bg: "transparent" }];
  for (let i = 0; i < d.length; i++) {
    const n = +d[i];
    out.push({ w: 1 + (n % 3) + "px", bg: "var(--text)" }, { w: 1 + ((n + i) % 3) + "px", bg: "transparent" }, { w: 1 + ((n * 3 + i) % 2) + "px", bg: "var(--text)" }, { w: "1px", bg: "transparent" });
  }
  out.push({ w: "2px", bg: "var(--text)" });
  return out;
}

export function Sotuvlarim() {
  const employee = useAuth((s) => s.employee);
  const t = useT();
  const { data } = useGet<Row[]>(`/sales?limit=100&current_shift=true&cashier=${encodeURIComponent(employee?.full_name || "")}`);
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");
  const [selId, setSelId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const prefs = readPrefs();

  const rows = useMemo(() => {
    const list = data || [];
    // Nasiya o'chirilgan bo'lsa — qarz cheklarini yashiramiz (dizayn)
    return list.filter((r) =>
      (prefs.qarz || r.method !== "credit") &&
      (filter === "all" || r.method === filter) &&
      (!q || r.receipt_no.includes(q))
    );
  }, [data, filter, q, prefs.qarz]);

  const activeId = (selId && rows.some((r) => r.id === selId) ? selId : rows[0]?.id) || null;
  useEffect(() => {
    if (!activeId) { setDetail(null); return; }
    let alive = true;
    get<Detail>(`/sales/${activeId}`).then((d) => { if (alive) setDetail(d); }).catch(() => {});
    return () => { alive = false; };
  }, [activeId]);

  // KPI jami server tomondan (100 qatorlik cap emas) — Smena ekrani bilan mos
  const summary = useGet<{ count: number; total: number; by_method: Record<string, number> }>(`/sales/summary?current_shift=true&cashier=${encodeURIComponent(employee?.full_name || "")}`);
  const totals = {
    all: summary.data?.total || 0,
    count: summary.data?.count || 0,
    cash: summary.data?.by_method?.cash || 0,
    card: summary.data?.by_method?.card || 0,
  };

  // To'lov chiplari sozlamadan (dizayn: yoqilgan usullar)
  const chips = ["all", "cash", ...(prefs.karta ? ["card"] : []), ...(prefs.qr ? ["qr"] : []), ...(prefs.qarz ? ["credit"] : [])];

  return (
    <main className="main">
      <div className="topbar"><div><div className="h1">{t("nav.sotuvlarim")}</div><div className="sub">{employee?.full_name} · {t("sales.subCurrentShift")}</div></div></div>
      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        {/* LEFT */}
        <div className="scroll" style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "22px 28px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14, marginBottom: 20 }}>
            <div className="card" style={{ padding: 16 }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("sales.shiftSales")}</div><div style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }} className="tabular">{fmt(totals.all)}</div></div>
            <div className="card" style={{ padding: 16 }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("sales.receipts")}</div><div style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }}>{totals.count}</div><div style={{ fontSize: 11, color: "var(--muted)" }}>{t("sales.saleCount")}</div></div>
            <div className="card" style={{ padding: 16 }}><div style={{ fontSize: 12, color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--ok)" }} />{t("pay.cash")}</div><div style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }} className="tabular">{fmt(totals.cash)}</div></div>
            <div className="card" style={{ padding: 16 }}><div style={{ fontSize: 12, color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: "#6d5dd3" }} />{t("pay.card")}</div><div style={{ fontSize: 24, fontWeight: 800, marginTop: 6 }} className="tabular">{fmt(totals.card)}</div></div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
            <div style={{ display: "flex", gap: 7 }}>
              {chips.map((k) => {
                const on = filter === k;
                return <button key={k} onClick={() => setFilter(k)} style={{ height: 38, padding: "0 15px", borderRadius: 10, fontSize: 13, fontWeight: 600, cursor: "pointer", border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`, background: on ? "var(--accent)" : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>{k === "all" ? t("pos.all") : t("pay." + k)}</button>;
              })}
            </div>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("sales.searchReceipt")} style={{ flex: 1, height: 38, padding: "0 14px", border: "1px solid var(--border-input)", borderRadius: 10, fontSize: 13, outline: "none", background: "var(--card)", color: "var(--text)" }} />
          </div>

          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ background: "var(--card-alt)", textAlign: "left", color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                <th style={{ padding: "12px 18px", fontWeight: 600 }}>{t("sales.receipt")}</th><th style={{ padding: "12px 8px", fontWeight: 600 }}>{t("sales.thTime")}</th><th style={{ padding: "12px 8px", fontWeight: 600 }}>{t("sales.thProduct")}</th><th style={{ padding: "12px 8px", fontWeight: 600 }}>{t("sales.thPay")}</th><th style={{ padding: "12px 18px", fontWeight: 600, textAlign: "right" }}>{t("sales.thSum")}</th>
              </tr></thead>
              <tbody>
                {rows.map((r) => {
                  const on = activeId === r.id;
                  const m = M[r.method] || [r.method, "var(--surface)", "var(--muted)"];
                  return (
                    <tr key={r.id} onClick={() => setSelId(r.id)} style={{ borderTop: "1px solid var(--border-soft)", fontSize: 13.5, cursor: "pointer", background: on ? "var(--surface-accent)" : "transparent" }}>
                      <td style={{ padding: "13px 18px", fontWeight: 700 }}>{r.receipt_no}</td>
                      <td style={{ padding: "13px 8px", color: "var(--muted)" }}>{new Date(r.sold_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</td>
                      <td style={{ padding: "13px 8px", color: "var(--text3)" }}>{t("sales.pcs", { n: r.item_count })}</td>
                      <td style={{ padding: "13px 8px" }}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: m[1], color: m[2] }}>{M[r.method] ? t("pay." + r.method) : r.method}</span></td>
                      <td style={{ padding: "13px 18px", textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(r.total)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {rows.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>{t("sales.noSales")}</div>}
          </div>
        </div>

        {/* RIGHT — receipt preview */}
        <div style={{ width: 340, flex: "none", background: "var(--card)", borderLeft: "1px solid var(--line)", display: "flex", flexDirection: "column", padding: 22 }}>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 16 }}>{t("sales.receipt")}</div>
          <div style={{ flex: 1, border: "1px dashed var(--border-input)", borderRadius: 14, padding: 20, display: "flex", flexDirection: "column" }}>
            {detail ? (
              <>
                <div style={{ textAlign: "center", paddingBottom: 14, borderBottom: "1px dashed var(--border-input)" }}>
                  <div style={{ fontSize: 16, fontWeight: 800 }}>{prefs.storeName}</div>
                  <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 2 }}>{prefs.branchName} · {employee?.full_name}</div>
                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{detail.receipt_no} · {new Date(detail.sold_at).toLocaleString("ru-RU")}</div>
                </div>
                <div style={{ flex: 1, padding: "14px 0", display: "flex", flexDirection: "column", gap: 10 }}>
                  {detail.items.map((it, i) => (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", fontSize: 13 }}>
                      <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 600 }}>{it.name_snapshot}</div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{it.qty} × {fmt(it.unit_price)}</div></div>
                      <div style={{ fontWeight: 700 }} className="tabular">{fmt(it.line_total)}</div>
                    </div>
                  ))}
                </div>
                <div style={{ paddingTop: 14, borderTop: "1px dashed var(--border-input)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}><span style={{ fontSize: 14, fontWeight: 700 }}>{t("pos.total")}</span><span style={{ fontSize: 26, fontWeight: 800 }} className="tabular">{fmt(detail.total)}</span></div>
                  {detail.uid && (
                    <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px dashed var(--border-input)" }}>
                      <div style={{ display: "flex", alignItems: "stretch", height: 40, justifyContent: "center" }}>
                        {bars(detail.uid).map((b, i) => <div key={i} style={{ width: b.w, background: b.bg }} />)}
                      </div>
                      <div style={{ textAlign: "center", fontSize: 11, letterSpacing: 3, color: "var(--text3)", marginTop: 6 }} className="tabular">{detail.uid}</div>
                    </div>
                  )}
                </div>
              </>
            ) : <div style={{ margin: "auto", color: "var(--muted)", fontSize: 13 }}>{t("sales.pickReceipt")}</div>}
          </div>
          {detail && (
            <button className="btn btn-ghost" style={{ marginTop: 16, height: 46 }} onClick={() => detail && printReceipt({
              receipt_no: detail.receipt_no, offline: false, store: prefs.storeName, branch: prefs.branchName, cashier: employee?.full_name || "",
              items: detail.items.map((it) => ({ name: it.name_snapshot, qty: it.qty, price: it.unit_price, line: it.line_total })),
              total: detail.total, method: rows.find((r) => r.id === detail.id)?.method || (data || []).find((r) => r.id === detail.id)?.method || "cash", given: 0, change: 0, date: new Date(detail.sold_at).toLocaleString("ru-RU"),
            })}>{`🖨 ${t("pos.printReceipt")}`}</button>
          )}
        </div>
      </div>
    </main>
  );
}
