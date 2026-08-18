import { useState } from "react";
import { Topbar, td, th, useGet } from "@/components/ui";

interface Entry { actor: string; action: string; action_label: string; entity: string; entity_label: string; name: string | null; at: string }

const FILTERS = [["", "Barchasi"], ["product", "Mahsulot"], ["employee", "Xodim"], ["customer", "Mijoz"], ["supplier", "Beruvchi"], ["category", "Kategoriya"]];
const ACT_COLOR: Record<string, [string, string]> = { create: ["var(--ok-soft)", "var(--ok)"], update: ["var(--border)", "var(--text3)"], delete: ["var(--danger-soft)", "var(--danger)"] };

export function Audit() {
  const [entity, setEntity] = useState("");
  const { data, err } = useGet<Entry[]>(`/audit?limit=200${entity ? `&entity=${entity}` : ""}`);
  const rows = data || [];

  return (
    <main className="main">
      <Topbar title="Audit jurnali" sub="Kim nima yaratdi, o'zgartirdi yoki o'chirdi" />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
          {FILTERS.map(([k, l]) => {
            const on = entity === k;
            return <button key={k} onClick={() => setEntity(k)} style={{ height: 38, padding: "0 15px", borderRadius: 10, fontSize: 13, fontWeight: 600, cursor: "pointer", border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`, background: on ? "var(--accent)" : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>{l}</button>;
          })}
        </div>
        {err && <div style={{ color: "var(--red)", marginBottom: 12 }}>{err}</div>}
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "var(--card-alt)" }}>
              <th style={th}>Xodim</th><th style={th}>Amal</th><th style={th}>Obyekt</th><th style={th}>Nomi</th><th style={{ ...th, textAlign: "right" }}>Vaqt</th>
            </tr></thead>
            <tbody>
              {rows.map((r, i) => {
                const c = ACT_COLOR[r.action] || ["var(--border)", "var(--text3)"];
                return (
                  <tr key={i}>
                    <td style={{ ...td, fontWeight: 600 }}>{r.actor}</td>
                    <td style={td}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: c[0], color: c[1] }}>{r.action_label}</span></td>
                    <td style={{ ...td, color: "var(--text3)" }}>{r.entity_label}</td>
                    <td style={{ ...td, fontWeight: 600 }}>{r.name || "—"}</td>
                    <td style={{ ...td, textAlign: "right", color: "var(--muted)" }}>{new Date(r.at).toLocaleString("ru-RU")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>Yozuvlar yo'q</div>}
        </div>
      </div>
    </main>
  );
}
