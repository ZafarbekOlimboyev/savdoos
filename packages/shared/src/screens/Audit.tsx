import { useState } from "react";
import { Topbar, td, th, useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { parseServerTime } from "@/lib/format";

interface Entry { actor: string; action: string; action_label: string; entity: string; entity_label: string; name: string | null; at: string }

const FILTERS = [["", "Barchasi"], ["product", "Mahsulot"], ["employee", "Xodim"], ["customer", "Mijoz"], ["supplier", "Beruvchi"], ["category", "Kategoriya"]];
const ACT_COLOR: Record<string, [string, string]> = { create: ["var(--ok-soft)", "var(--ok)"], update: ["var(--border)", "var(--text3)"], delete: ["var(--danger-soft)", "var(--danger)"] };

export function Audit() {
  const t = useT();
  const [entity, setEntity] = useState("");
  const { data, err } = useGet<Entry[]>(`/audit?limit=200${entity ? `&entity=${entity}` : ""}`);
  const rows = data || [];

  return (
    <main className="main">
      <Topbar title={t("nav.audit")} sub={t("audit.sub")} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
          {FILTERS.map(([k, l]) => {
            const on = entity === k;
            return <button key={k} onClick={() => setEntity(k)} style={{ height: 38, padding: "0 15px", borderRadius: 10, fontSize: 13, fontWeight: 600, cursor: "pointer", border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`, background: on ? "var(--accent)" : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>{k === "" ? t("pos.all") : t("audit.f_" + k)}</button>;
          })}
        </div>
        {err && <div style={{ color: "var(--red)", marginBottom: 12 }}>{err}</div>}
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "var(--card-alt)" }}>
              <th style={th}>{t("audit.thActor")}</th><th style={th}>{t("audit.thAction")}</th><th style={th}>{t("audit.thObject")}</th><th style={th}>{t("audit.thName")}</th><th style={{ ...th, textAlign: "right" }}>{t("sales.thTime")}</th>
            </tr></thead>
            <tbody>
              {rows.map((r, i) => {
                const c = ACT_COLOR[r.action] || ["var(--border)", "var(--text3)"];
                return (
                  <tr key={i}>
                    <td style={{ ...td, fontWeight: 600 }}>{r.actor}</td>
                    <td style={td}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 10px", borderRadius: 8, background: c[0], color: c[1] }}>{["create", "update", "delete"].includes(r.action) ? t("audit.act_" + r.action) : r.action_label}</span></td>
                    <td style={{ ...td, color: "var(--text3)" }}>{["product", "employee", "customer", "supplier", "category"].includes(r.entity) ? t("audit.f_" + r.entity) : r.entity_label}</td>
                    <td style={{ ...td, fontWeight: 600 }}>{r.name || "—"}</td>
                    <td style={{ ...td, textAlign: "right", color: "var(--muted)" }}>{parseServerTime(r.at)?.toLocaleString("ru-RU") ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>{t("audit.noRecords")}</div>}
        </div>
      </div>
    </main>
  );
}
