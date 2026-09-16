import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { fmt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { lotQuery, type LotList } from "@/lib/lots";
import { Topbar, inputStyle, td, th, useGet } from "@/components/ui";
import {
  CostBadge, DormantNotice, ExpiryBadge, KV, Pager, Segmented, State,
  useAvailability, useDebounced, useNarrow,
} from "@/components/lotui";
import { LotDrawer } from "@/screens/PartiyaTafsilot";

const PAGE = 50;

export function Partiyalar() {
  const t = useT();
  const nav = useNavigate();
  const narrow = useNarrow();
  const av = useAvailability();
  const [q, setQ] = useState("");
  const [expiry, setExpiry] = useState("any");
  const [status, setStatus] = useState("open");
  const [branch, setBranch] = useState("");
  const [sort, setSort] = useState("expiry");
  const [order, setOrder] = useState("asc");
  const [offset, setOffset] = useState(0);
  const [sel, setSel] = useState<string | null>(null);
  const dq = useDebounced(q);

  // ⚠️  FILTR SERVERGA BERILADI. Qatorlar brauzerda saralanmaydi: sahifada
  //     50 ta qator bor, jami esa minglab — mahalliy saralash YOLG'ON tartib
  //     ko'rsatardi ("eng yaqin muddat" faqat shu sahifada eng yaqin bo'lardi).
  const path = useMemo(() => "/lots/batches" + lotQuery({
    q: dq || undefined, expiry, status, branch_id: branch || undefined,
    sort, order, limit: PAGE, offset,
  }), [dq, expiry, status, branch, sort, order, offset]);
  const { data, err, loading, reload } = useGet<LotList>(path);

  function change(fn: () => void) { fn(); setOffset(0); }   // filtr o'zgarsa 1-sahifaga

  const rows = data?.lots || [];
  const multiBranch = (av.data?.branches.length || 0) > 1;

  if (av.data && av.data.tracked_products === 0) {
    return (
      <main className="main">
        <Topbar title={t("nav.partiyalar")} sub={t("lot.subBatches")} />
        <div className="scroll" style={{ flex: 1 }}><DormantNotice av={av.data} /></div>
      </main>
    );
  }

  return (
    <main className="main">
      <Topbar title={t("nav.partiyalar")} sub={t("lot.subBatches")} />
      <div className="scroll" style={{ flex: 1, padding: narrow ? 14 : 24 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
          <label style={{ position: "relative", flex: narrow ? "1 1 100%" : "0 0 280px" }}>
            <span className="sr-only">{t("lot.search")}</span>
            <MagnifyingGlass size={16} color="var(--faint)" aria-hidden
                             style={{ position: "absolute", left: 12, top: 14 }} />
            <input value={q} onChange={(e) => change(() => setQ(e.target.value))}
                   placeholder={t("lot.search")} data-testid="lot-search"
                   style={{ ...inputStyle, height: 42, paddingLeft: 34 }} />
          </label>
          <Segmented testid="f-expiry" label={t("lot.expiry")} value={expiry} onChange={(v) => change(() => setExpiry(v))}
                     options={[["any", t("pos.all")], ["expired", t("lot.bucket.expired")],
                               ["expires_today", t("lot.bucket.expires_today")],
                               ["within_7_days", t("lot.f7")], ["within_30_days", t("lot.f30")],
                               ["no_expiry", t("lot.bucket.no_expiry")]]} />
          <select value={status} onChange={(e) => change(() => setStatus(e.target.value))}
                  aria-label={t("lot.status")} data-testid="f-status"
                  style={{ ...inputStyle, width: 160, height: 42 }}>
            <option value="open">{t("lot.st.open")}</option>
            <option value="depleted">{t("lot.st.depleted")}</option>
            <option value="any">{t("lot.st.any")}</option>
          </select>
          {multiBranch && (
            <select value={branch} onChange={(e) => change(() => setBranch(e.target.value))}
                    aria-label={t("lot.branch")} data-testid="f-branch"
                    style={{ ...inputStyle, width: 190, height: 42 }}>
              <option value="">{t("lot.allBranches")}</option>
              {av.data?.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          )}
          <select value={sort + ":" + order} data-testid="f-sort" aria-label={t("lot.sort")}
                  onChange={(e) => change(() => { const [s, o] = e.target.value.split(":"); setSort(s); setOrder(o); })}
                  style={{ ...inputStyle, width: 200, height: 42 }}>
            <option value="expiry:asc">{t("lot.sortExpiry")}</option>
            <option value="received:desc">{t("lot.sortReceived")}</option>
            <option value="remaining:desc">{t("lot.sortRemaining")}</option>
            <option value="value:desc">{t("lot.sortValue")}</option>
            <option value="product:asc">{t("lot.sortProduct")}</option>
          </select>
        </div>

        <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }} data-testid="lot-total">
          {t("lot.foundN", { n: data?.total ?? 0 })}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <State loading={loading && !data} err={err} onRetry={reload}
                 empty={!loading && rows.length === 0} emptyText={t("lot.emptyBatches")}>
            {narrow ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 12 }}>
                {rows.map((r) => (
                  <button key={r.id} onClick={() => setSel(r.id)} data-testid={"lot-card-" + r.id}
                          style={{ textAlign: "left", font: "inherit", cursor: "pointer", background: "var(--card-alt)", border: "1px solid var(--border)", borderRadius: 14, padding: 14, display: "flex", flexDirection: "column", gap: 7 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                      <span style={{ fontWeight: 700, fontSize: 14 }}>{r.product}</span>
                      <ExpiryBadge bucket={r.bucket} daysLeft={r.days_left} />
                    </div>
                    <KV k={t("lot.batchNo")} v={r.batch_number || "—"} />
                    <KV k={t("lot.expiry")} v={r.expiry_date || t("lot.bucket.no_expiry")} />
                    <KV k={t("lot.remaining")} v={`${r.remaining_qty} ${r.unit_code || ""}`} />
                    <KV k={t("lot.value")} v={<span className="tabular">{fmt(r.value)} <CostBadge basis={r.cost_basis} /></span>} />
                  </button>
                ))}
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <caption className="sr-only">{t("lot.tableCaption")}</caption>
                  <thead><tr style={{ background: "var(--card-alt)" }}>
                    <th style={th} scope="col">{t("lot.product")}</th>
                    <th style={th} scope="col">{t("lot.batchNo")}</th>
                    <th style={th} scope="col">{t("lot.expiry")}</th>
                    <th style={{ ...th, textAlign: "right" }} scope="col">{t("lot.remaining")}</th>
                    <th style={{ ...th, textAlign: "right" }} scope="col">{t("lot.unitCost")}</th>
                    <th style={{ ...th, textAlign: "right" }} scope="col">{t("lot.value")}</th>
                    <th style={th} scope="col">{t("lot.source")}</th>
                    {multiBranch && <th style={th} scope="col">{t("lot.branch")}</th>}
                  </tr></thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="click-row" data-testid={"lot-row-" + r.id}
                          tabIndex={0} role="button" aria-label={`${r.product} ${r.batch_number || ""}`}
                          onClick={() => setSel(r.id)}
                          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(r.id); } }}>
                        <td style={{ ...td, fontWeight: 600 }}>{r.product}</td>
                        <td style={{ ...td, color: "var(--text3)" }}>{r.batch_number || "—"}</td>
                        <td style={td}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                            <span className="tabular">{r.expiry_date || "—"}</span>
                            <ExpiryBadge bucket={r.bucket} daysLeft={r.days_left} />
                          </div>
                        </td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">{r.remaining_qty} {r.unit_code || ""}</td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">{fmt(r.unit_cost)}</td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">
                          <div style={{ display: "flex", gap: 7, justifyContent: "flex-end", alignItems: "center" }}>
                            {fmt(r.value)}<CostBadge basis={r.cost_basis} />
                          </div>
                        </td>
                        <td style={{ ...td, color: "var(--text3)" }}>
                          {t("lot.src." + (r.source_type || "unknown"))}
                          {r.supplier ? ` · ${r.supplier}` : ""}
                        </td>
                        {multiBranch && <td style={{ ...td, color: "var(--text3)" }}>{r.branch}</td>}
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
