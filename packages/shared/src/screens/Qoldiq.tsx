import { useState } from "react";
import { Question } from "@phosphor-icons/react";
import { fmt, parseServerTime } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { ShortfallRow } from "@/lib/lots";
import { Topbar, inputStyle, td, th, useGet } from "@/components/ui";
import { CostBadge, DormantNotice, KV, State, useAvailability, useNarrow } from "@/components/lotui";
import { QoldiqTafsilot } from "@/screens/QoldiqTafsilot";

interface SfList { count: number; shortfalls: ShortfallRow[]; total_cogs_variance: number }

/**
 * ANIQLANMAGAN QOLDIQ.
 *
 * ⚠️  ATAMA ATAYLAB SODDA. Serverda bu «shortfall» — offline chekda tovar
 *     ketgan, lekin qaysi partiyadan ketgani noma'lum qolgan miqdor. Operator
 *     «shortfall» so'zini bilmasligi kerak: unga «qaysi partiyadan ketgani
 *     aniqlanmagan qoldiq» degan tushuncha kerak.
 */
export function Qoldiq() {
  const t = useT();
  const narrow = useNarrow();
  const av = useAvailability();
  const [branch, setBranch] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [sel, setSel] = useState<string | null>(null);

  const path = "/lots/shortfalls?include_resolved=" + (showClosed ? "true" : "false")
    + (branch ? "&branch_id=" + branch : "");
  const { data, err, loading, reload } = useGet<SfList>(path);
  const rows = data?.shortfalls || [];
  const multiBranch = (av.data?.branches.length || 0) > 1;

  // ⚠️  Kuzatuv o'chgan, lekin OCHIQ QARZ yoki partiya qolgan bo'lishi mumkin —
  //     u holda ekran OCHIQ qoladi (aks holda pul ekrandan g'oyib bo'lardi).
  if (av.data && av.data.tracked_products === 0 && !av.data.has_lot_data) {
    return (
      <main className="main" id="main" tabIndex={-1}>
        <Topbar title={t("nav.qoldiq")} sub={t("lot.subShortfall")} />
        <div className="scroll" style={{ flex: 1 }}><DormantNotice av={av.data} /></div>
      </main>
    );
  }

  return (
    <main className="main" id="main" tabIndex={-1}>
      <Topbar title={t("nav.qoldiq")} sub={t("lot.subShortfall")} />
      <div className="scroll" style={{ flex: 1, padding: narrow ? 14 : 24 }}>
        <div role="note" style={{ display: "flex", gap: 9, alignItems: "flex-start", padding: "11px 14px", borderRadius: 11, background: "var(--info-soft)", color: "var(--text3)", fontSize: 12.5, marginBottom: 14 }}>
          <Question size={16} aria-hidden style={{ flex: "none", marginTop: 1 }} />
          <span data-testid="sf-explain">{t("lot.shortfallExplain")}</span>
        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
          {multiBranch && (
            <select value={branch} onChange={(e) => setBranch(e.target.value)} data-testid="sf-branch"
                    aria-label={t("lot.branch")} style={{ ...inputStyle, width: 190, height: 42 }}>
              <option value="">{t("lot.allBranches")}</option>
              {av.data?.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          )}
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            <input type="checkbox" checked={showClosed} data-testid="sf-show-closed"
                   onChange={(e) => setShowClosed(e.target.checked)} />
            {t("lot.showClosed")}
          </label>
          <span style={{ fontSize: 13, color: "var(--muted)" }} data-testid="sf-total">
            {t("lot.foundN", { n: data?.count ?? 0 })}
          </span>
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <State loading={loading && !data} err={err} onRetry={reload}
                 empty={!loading && rows.length === 0} emptyText={t("lot.emptyShortfalls")}>
            {narrow ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 12 }}>
                {rows.map((r) => (
                  <button key={r.id} onClick={() => setSel(r.id)} data-testid={"sf-card-" + r.id}
                          style={{ textAlign: "left", font: "inherit", cursor: "pointer", background: "var(--card-alt)", border: "1px solid var(--border)", borderRadius: 14, padding: 14, display: "flex", flexDirection: "column", gap: 7 }}>
                    <span style={{ fontWeight: 700, fontSize: 14 }}>{r.product}</span>
                    <KV k={t("lot.openQty")} v={<span className="tabular">{r.open_qty}</span>} />
                    <KV k={t("lot.estimatedCost")} v={<span className="tabular">{fmt(r.unit_cost)}</span>} />
                    <KV k={t("lot.costQuality")} v={<CostBadge basis="estimated" mixed={r.resolved_qty > 0 && r.open_qty > 0} />} />
                    <KV k={t("lot.profitEffect")} v={<span className="tabular">{fmt(r.cogs_variance)}</span>} />
                  </button>
                ))}
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <caption className="sr-only">{t("lot.subShortfall")}</caption>
                  <thead><tr style={{ background: "var(--card-alt)" }}>
                    <th style={th} scope="col">{t("lot.product")}</th>
                    <th style={{ ...th, textAlign: "right" }} scope="col">{t("lot.openQty")}</th>
                    <th style={{ ...th, textAlign: "right" }} scope="col">{t("lot.estimatedCost")}</th>
                    <th style={th} scope="col">{t("lot.costQuality")}</th>
                    <th style={{ ...th, textAlign: "right" }} scope="col">{t("lot.profitEffect")}</th>
                    <th style={th} scope="col">{t("lot.when")}</th>
                  </tr></thead>
                  {/* Ochish nishoni — katakdagi HAQIQIY tugma: jadval semantikasi
                      ekran o'quvchida saqlanadi. */}
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="click-row" data-testid={"sf-row-" + r.id}
                          onClick={() => setSel(r.id)}>
                        <td style={{ ...td, fontWeight: 600 }} className="lot-wrap">
                          <button className="row-open" data-testid={"sf-open-" + r.id}
                                  onClick={(e) => { e.stopPropagation(); setSel(r.id); }}>
                            {r.product}
                          </button>
                        </td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">{r.open_qty}</td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">{fmt(r.unit_cost)}</td>
                        <td style={td}>
                          <CostBadge basis="estimated" mixed={r.resolved_qty > 0 && r.open_qty > 0} />
                        </td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">{fmt(r.cogs_variance)}</td>
                        <td style={{ ...td, color: "var(--muted)" }}>
                          {parseServerTime(r.created_at)?.toLocaleDateString("ru-RU") || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </State>
        </div>
      </div>

      {sel && (
        <QoldiqTafsilot id={sel} canWrite={!!av.data?.can_write}
                        onClose={() => setSel(null)} onChanged={reload} />
      )}
    </main>
  );
}
