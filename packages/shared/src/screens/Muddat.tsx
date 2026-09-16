import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Info } from "@phosphor-icons/react";
import { fmt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { lotQuery, type LotAlerts, type LotList } from "@/lib/lots";
import { Topbar, inputStyle, td, th, useGet } from "@/components/ui";
import {
  CostBadge, DormantNotice, ExpiryBadge, KV, Pager, Segmented, State,
  useAvailability, useNarrow,
} from "@/components/lotui";
import { LotDrawer } from "@/screens/PartiyaTafsilot";

const PAGE = 50;
const TABS = ["expired", "expires_today", "within_7_days", "within_30_days", "any"];

/**
 * YAROQLILIK MUDDATI.
 *
 * ⚠️  MUDDATI O'TGAN TOVAR QOLDIQDAN O'ZI YO'QOLMAYDI. Tizim uni hisobdan
 *     avtomatik chiqarsa, qoldiq jismoniy javondan farq qilib ketardi va
 *     operator nima tashlaganini bilmasdi. «Muddati o'tgan» — HOLAT; tovarni
 *     qo'lda hisobdan chiqarish operatorning ONGLI amali.
 */
export function Muddat() {
  const t = useT();
  const nav = useNavigate();
  const narrow = useNarrow();
  const av = useAvailability();
  const [tab, setTab] = useState("expired");
  const [branch, setBranch] = useState("");
  const [offset, setOffset] = useState(0);
  const [sel, setSel] = useState<string | null>(null);

  const alerts = useGet<LotAlerts>("/lots/alerts" + (branch ? "?branch_id=" + branch : ""));
  const path = useMemo(() => "/lots/batches" + lotQuery({
    expiry: tab === "any" ? "valid" : tab, status: "open", branch_id: branch || undefined,
    sort: "expiry", order: "asc", limit: PAGE, offset,
  }), [tab, branch, offset]);
  const { data, err, loading, reload } = useGet<LotList>(path);

  const rows = data?.lots || [];
  const multiBranch = (av.data?.branches.length || 0) > 1;
  const a = alerts.data;
  const cards: [string, number, number][] = a ? [
    ["expired", a.expiry.expired.lots, a.expiry.expired.value_at_risk],
    ["expires_today", a.expiry.expires_today.lots, a.expiry.expires_today.value_at_risk],
    ["within_7_days", a.expiry.within_7_days.lots, a.expiry.within_7_days.value_at_risk],
    ["within_30_days", a.expiry.within_30_days.lots, a.expiry.within_30_days.value_at_risk],
  ] : [];

  if (av.data && av.data.tracked_products === 0) {
    return (
      <main className="main">
        <Topbar title={t("nav.muddat")} sub={t("lot.subExpiry")} />
        <div className="scroll" style={{ flex: 1 }}><DormantNotice av={av.data} /></div>
      </main>
    );
  }

  return (
    <main className="main">
      <Topbar title={t("nav.muddat")} sub={t("lot.subExpiry")} />
      <div className="scroll" style={{ flex: 1, padding: narrow ? 14 : 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: narrow ? "1fr 1fr" : "repeat(4, 1fr)", gap: 12, marginBottom: 16 }}>
          {cards.map(([key, n, val]) => (
            <button key={key} onClick={() => { setTab(key); setOffset(0); }} data-testid={"exp-card-" + key}
                    aria-pressed={tab === key}
                    className="card click-card" style={{ textAlign: "left", font: "inherit", cursor: "pointer", borderColor: tab === key ? "var(--accent-border)" : "var(--border)" }}>
              <div style={{ fontSize: 12.5, color: "var(--muted)", fontWeight: 500 }}>{t("lot.bucket." + key)}</div>
              <div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 8 }}>{n}</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
                {t("lot.valueAtRisk")}: <span className="tabular">{fmt(val)}</span>
              </div>
            </button>
          ))}
        </div>

        {/* Operator xulosasi: bu ro'yxat HISOBOT emas, ISH RO'YXATI. */}
        <div role="note" data-testid="expiry-notice"
             style={{ display: "flex", gap: 9, alignItems: "flex-start", padding: "11px 14px", borderRadius: 11, background: "var(--info-soft)", color: "var(--text3)", fontSize: 12.5, marginBottom: 14 }}>
          <Info size={16} aria-hidden style={{ flex: "none", marginTop: 1 }} />
          <span>{t("lot.expiryNotice")}</span>
        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
          <Segmented testid="exp-tab" label={t("lot.expiry")} value={tab} onChange={(v) => { setTab(v); setOffset(0); }}
                     options={TABS.map((k) => [k, k === "any" ? t("lot.tabValid") : t("lot.bucket." + k)]) as [string, string][]} />
          {multiBranch && (
            <select value={branch} onChange={(e) => { setBranch(e.target.value); setOffset(0); }}
                    aria-label={t("lot.branch")} data-testid="exp-branch"
                    style={{ ...inputStyle, width: 190, height: 42 }}>
              <option value="">{t("lot.allBranches")}</option>
              {av.data?.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          )}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <State loading={loading && !data} err={err} onRetry={reload}
                 empty={!loading && rows.length === 0}
                 emptyText={tab === "expired" ? t("lot.emptyExpired") : t("lot.emptyBatches")}>
            {narrow ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 12 }}>
                {rows.map((r) => (
                  <div key={r.id} data-testid={"exp-card-row-" + r.id}
                       style={{ background: "var(--card-alt)", border: "1px solid var(--border)", borderRadius: 14, padding: 14, display: "flex", flexDirection: "column", gap: 7 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                      <span style={{ fontWeight: 700, fontSize: 14 }}>{r.product}</span>
                      <ExpiryBadge bucket={r.bucket} daysLeft={r.days_left} />
                    </div>
                    <KV k={t("lot.expiry")} v={r.expiry_date || "—"} />
                    <KV k={t("lot.remaining")} v={`${r.remaining_qty} ${r.unit_code || ""}`} />
                    <KV k={t("lot.value")} v={<span className="tabular">{fmt(r.value)}</span>} />
                    <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                      <button className="btn btn-ghost" style={{ flex: 1 }} onClick={() => setSel(r.id)}>{t("lot.details")}</button>
                      {av.data?.can_write && (
                        <button className="btn" data-testid={"exp-writeoff-" + r.id}
                                onClick={() => nav(`/hisobdan-chiqarish?product=${r.product_id}&lot=${r.id}`)}
                                style={{ flex: 1, border: "1.5px solid var(--danger-border)", background: "var(--card)", color: "var(--danger)" }}>
                          {t("lot.writeoffAction")}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <caption className="sr-only">{t("lot.subExpiry")}</caption>
                  <thead><tr style={{ background: "var(--card-alt)" }}>
                    <th style={th} scope="col">{t("lot.product")}</th>
                    <th style={th} scope="col">{t("lot.batchNo")}</th>
                    <th style={th} scope="col">{t("lot.expiry")}</th>
                    <th style={{ ...th, textAlign: "right" }} scope="col">{t("lot.remaining")}</th>
                    <th style={{ ...th, textAlign: "right" }} scope="col">{t("lot.value")}</th>
                    {multiBranch && <th style={th} scope="col">{t("lot.branch")}</th>}
                    <th style={{ ...th, textAlign: "right" }} scope="col">{t("lot.actions")}</th>
                  </tr></thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} data-testid={"exp-row-" + r.id}>
                        <td style={{ ...td, fontWeight: 600 }}>{r.product}</td>
                        <td style={{ ...td, color: "var(--text3)" }}>{r.batch_number || "—"}</td>
                        <td style={td}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                            <span className="tabular">{r.expiry_date || "—"}</span>
                            <ExpiryBadge bucket={r.bucket} daysLeft={r.days_left} />
                          </div>
                        </td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">{r.remaining_qty} {r.unit_code || ""}</td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">
                          <div style={{ display: "flex", gap: 7, justifyContent: "flex-end", alignItems: "center" }}>
                            {fmt(r.value)}<CostBadge basis={r.cost_basis} />
                          </div>
                        </td>
                        {multiBranch && <td style={{ ...td, color: "var(--text3)" }}>{r.branch}</td>}
                        <td style={{ ...td, textAlign: "right" }}>
                          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                            <button className="btn btn-ghost" style={{ padding: "7px 12px" }}
                                    data-testid={"exp-details-" + r.id} onClick={() => setSel(r.id)}>
                              {t("lot.details")}
                            </button>
                            {av.data?.can_write && (
                              <button className="btn" data-testid={"exp-writeoff-" + r.id}
                                      onClick={() => nav(`/hisobdan-chiqarish?product=${r.product_id}&lot=${r.id}`)}
                                      style={{ padding: "7px 12px", border: "1.5px solid var(--danger-border)", background: "var(--card)", color: "var(--danger)" }}>
                                {t("lot.writeoffAction")}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <Pager total={data?.total || 0} limit={PAGE} offset={offset} onOffset={setOffset} />
          </State>
        </div>
      </div>

      {sel && (
        <LotDrawer id={sel} onClose={() => setSel(null)} canWrite={!!av.data?.can_write}
                   onWriteoff={(pid, lid) => nav(`/hisobdan-chiqarish?product=${pid}&lot=${lid}`)}
                   onCount={(pid) => nav(`/inventarizatsiya?product=${pid}`)} />
      )}
    </main>
  );
}
