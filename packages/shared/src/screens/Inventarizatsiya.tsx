import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { CheckCircle, Plus, Trash } from "@phosphor-icons/react";
import { fmt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { countStock, lotQuery, newClientUuid, type CountNewLotIn, type LotList } from "@/lib/lots";
import { Topbar, inputStyle, useGet } from "@/components/ui";
import {
  Confirm, CostBadge, DormantNotice, ExpiryBadge, ProductPicker, State, WriteClosed,
  useAvailability, useNarrow, type PickedProduct,
} from "@/components/lotui";

interface NewLotDraft extends CountNewLotIn { key: string }

/**
 * PARTIYA DARAJASIDAGI INVENTARIZATSIYA.
 *
 * ⚠️  SANALMAGAN PARTIYA — «NOL» EMAS. Operator javonning bir qismini sanagan
 *     bo'lsa, ko'rmagan partiyalari TEGILMAYDI. Shu bois maydon bo'sh qolsa
 *     serverga UMUMAN yuborilmaydi (nol deb emas).
 *
 * ⚠️  ORTIQCHA TOVAR MAVJUD PARTIYAGA QO'SHILMAYDI. Agar javonda boshqa
 *     muddatli/narxli qadoq topilsa, operator uni ALOHIDA partiya qilib e'lon
 *     qiladi — aks holda o'sha kogortaning muddati va tannarxi yolg'on bo'lardi.
 */
export function Inventarizatsiya() {
  const t = useT();
  const narrow = useNarrow();
  const av = useAvailability();
  const loc = useLocation();
  const preProduct = new URLSearchParams(loc.search || loc.pathname.split("?")[1] || "").get("product");

  const [prod, setProd] = useState<PickedProduct | null>(null);
  const [counted, setCounted] = useState<Record<string, string>>({});
  const [news, setNews] = useState<NewLotDraft[]>([]);
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [cu, setCu] = useState(newClientUuid());

  const path = useMemo(() => prod
    ? "/lots/batches" + lotQuery({ product_id: prod.id, status: "open", sort: "expiry", limit: 200 })
    : "", [prod]);
  const lots = useGet<LotList>(path);

  const pre = useGet<LotList>(preProduct && !prod
    ? "/lots/batches" + lotQuery({ product_id: preProduct, status: "any", limit: 1 }) : "");
  useEffect(() => {
    const row = pre.data?.lots?.[0];
    if (!preProduct || prod || !row) return;
    setProd({ id: row.product_id, name: row.product || "", unit_code: row.unit_code, stock: 0 });
  }, [preProduct, prod, pre.data]);

  const rows = prod ? (lots.data?.lots || []) : [];
  const touched = rows.filter((r) => (counted[r.id] ?? "") !== "");
  const untouchedQty = rows
    .filter((r) => (counted[r.id] ?? "") === "")
    .reduce((s, r) => s + r.remaining_qty, 0);
  const countedQty = touched.reduce((s, r) => s + Number(counted[r.id] || 0), 0);
  const newQty = news.reduce((s, n) => s + (Number(n.qty) || 0), 0);
  const total = untouchedQty + countedQty + newQty;
  const negative = touched.some((r) => Number(counted[r.id]) < 0);
  const expiryMissing = news.some((n) => !n.expiry_date);
  // Mahsulotning O'Z bayrog'i birinchi; partiyalar faqat zaxira taxmin.
  const needExpiry = prod?.track_expiry ?? rows.some((r) => r.expiry_date);
  const badNew = news.some((n) => !(Number(n.qty) > 0) || Number(n.unit_cost) < 0);
  const canSend = !!prod && !negative && !badNew && (touched.length > 0 || news.length > 0) && !!av.data?.can_write;

  function addNew() {
    setNews([...news, { key: newClientUuid(), qty: 0, unit_cost: 0, batch_no: "", expiry_date: "", reason: "" }]);
  }
  function setNew(key: string, patch: Partial<NewLotDraft>) {
    setNews(news.map((n) => (n.key === key ? { ...n, ...patch } : n)));
  }

  async function send() {
    setBusy(true); setErr("");
    try {
      const res = await countStock({
        items: [{
          product_id: prod!.id, counted: total,
          lots: touched.map((r) => ({ stock_batch_id: r.id, counted: Number(counted[r.id]) })),
          new_lots: news.map((n) => ({
            qty: Number(n.qty), unit_cost: Number(n.unit_cost) || 0,
            batch_no: n.batch_no || undefined,
            expiry_date: n.expiry_date || undefined,
            reason: n.reason || undefined,
          })),
        }],
        client_uuid: cu,
      });
      setAsk(false);
      const made = res.results?.[0]?.lots?.created?.length || 0;
      setDone(t("lot.countDone", { n: total, k: made }));
      setCounted({}); setNews([]);
      setCu(newClientUuid());
      lots.reload();
      if (res.duplicate) setErr(t("lot.alreadyApplied"));
    } catch (e: any) {
      setErr(e.message);
      setAsk(false);
    } finally {
      setBusy(false);
    }
  }

  if (av.data && av.data.tracked_products === 0) {
    return (
      <main className="main">
        <Topbar title={t("nav.inventarizatsiya")} sub={t("lot.subCount")} />
        <div className="scroll" style={{ flex: 1 }}><DormantNotice av={av.data} /></div>
      </main>
    );
  }

  return (
    <main className="main">
      <Topbar title={t("nav.inventarizatsiya")} sub={t("lot.subCount")} />
      <div className="scroll" style={{ flex: 1, padding: narrow ? 14 : 24, maxWidth: 900 }}>
        {av.data && !av.data.can_write && <div style={{ marginBottom: 14 }}><WriteClosed av={av.data} /></div>}
        {done && (
          <div role="status" data-testid="count-done"
               style={{ display: "flex", gap: 9, alignItems: "center", padding: "12px 15px", borderRadius: 12, background: "var(--ok-soft)", color: "var(--ok)", fontWeight: 600, fontSize: 13.5, marginBottom: 14 }}>
            <CheckCircle size={18} weight="fill" aria-hidden />{done}
          </div>
        )}
        {err && <div role="alert" data-testid="count-error" style={{ color: "var(--danger)", marginBottom: 14, fontSize: 13.5 }}>{err}</div>}

        <section className="card" style={{ marginBottom: 14 }}>
          <h2 style={{ fontSize: 14, margin: "0 0 10px" }}>{t("lot.step1")}</h2>
          <ProductPicker value={prod} onPick={(p) => { setProd(p); setCounted({}); setNews([]); setDone(null); }} testid="cnt-product" />
        </section>

        {prod && (
          <section className="card" style={{ marginBottom: 14 }}>
            <h2 style={{ fontSize: 14, margin: "0 0 4px" }}>{t("lot.step2Count")}</h2>
            <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 12px" }}>{t("lot.countHint")}</p>
            <State loading={lots.loading && !lots.data} err={lots.err} onRetry={lots.reload}
                   empty={!lots.loading && rows.length === 0} emptyText={t("lot.noOpenLots")}>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {rows.map((r) => {
                  const raw = counted[r.id] ?? "";
                  const diff = raw === "" ? null : Number(raw) - r.remaining_qty;
                  return (
                    <div key={r.id} data-testid={"cnt-lot-" + r.id}
                         style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: 12, borderRadius: 12, border: "1px solid var(--border)", background: "var(--card-alt)" }}>
                      <div style={{ flex: "1 1 220px", minWidth: 0 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                          <span style={{ fontWeight: 700 }}>{r.batch_number || t("lot.noBatchNo")}</span>
                          <ExpiryBadge bucket={r.bucket} daysLeft={r.days_left} />
                          <CostBadge basis={r.cost_basis} />
                        </div>
                        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4 }}>
                          {t("lot.systemQty")}: <span className="tabular">{r.remaining_qty} {r.unit_code || ""}</span>
                          {" · "}{t("lot.expiry")}: {r.expiry_date || "—"}
                        </div>
                      </div>
                      <label style={{ flex: "0 0 130px" }}>
                        <span className="sr-only">{t("lot.countedQty")}</span>
                        <input type="number" min={0} step="any" inputMode="decimal"
                               value={raw} data-testid={"cnt-qty-" + r.id}
                               placeholder={t("lot.notCounted")}
                               onChange={(e) => setCounted({ ...counted, [r.id]: e.target.value })}
                               style={{ ...inputStyle, height: 42 }} />
                      </label>
                      <div style={{ flex: "0 0 92px", textAlign: "right", fontSize: 13, fontWeight: 700 }}
                           data-testid={"cnt-diff-" + r.id}
                           className="tabular">
                        {diff === null ? <span style={{ color: "var(--faint)", fontWeight: 500 }}>{t("lot.untouched")}</span>
                          : diff === 0 ? <span style={{ color: "var(--muted)" }}>0</span>
                            : <span style={{ color: diff > 0 ? "var(--ok)" : "var(--danger)" }}>{diff > 0 ? "+" : ""}{diff}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </State>
          </section>
        )}

        {prod && (
          <section className="card" style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <div>
                <h2 style={{ fontSize: 14, margin: "0 0 4px" }}>{t("lot.step3Count")}</h2>
                <p style={{ fontSize: 12.5, color: "var(--muted)", margin: 0, maxWidth: 560 }}>{t("lot.newLotHint")}</p>
              </div>
              <button className="btn btn-ghost" onClick={addNew} data-testid="cnt-add-new"
                      style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <Plus size={16} aria-hidden />{t("lot.addNewLot")}
              </button>
            </div>

            {news.map((n) => (
              <div key={n.key} data-testid="cnt-new-row"
                   style={{ marginTop: 12, padding: 12, borderRadius: 12, border: "1px dashed var(--accent-border)", display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
                <label style={{ flex: "1 1 120px" }}>
                  <span style={{ fontSize: 12, color: "var(--muted)", display: "block", marginBottom: 5 }}>{t("lot.qtyFound")}</span>
                  <input type="number" min={0} step="any" inputMode="decimal" data-testid="cnt-new-qty"
                         value={n.qty || ""} onChange={(e) => setNew(n.key, { qty: Number(e.target.value) })}
                         style={{ ...inputStyle, height: 42 }} />
                </label>
                <label style={{ flex: "1 1 130px" }}>
                  <span style={{ fontSize: 12, color: "var(--muted)", display: "block", marginBottom: 5 }}>{t("lot.batchNo")}</span>
                  <input value={n.batch_no || ""} maxLength={64} data-testid="cnt-new-batch"
                         onChange={(e) => setNew(n.key, { batch_no: e.target.value })}
                         style={{ ...inputStyle, height: 42 }} />
                </label>
                <label style={{ flex: "1 1 150px" }}>
                  <span style={{ fontSize: 12, color: "var(--muted)", display: "block", marginBottom: 5 }}>
                    {t("lot.expiry")}{needExpiry ? " *" : ""}
                  </span>
                  <input type="date" value={n.expiry_date || ""} data-testid="cnt-new-expiry"
                         onChange={(e) => setNew(n.key, { expiry_date: e.target.value })}
                         style={{ ...inputStyle, height: 42 }} />
                </label>
                <label style={{ flex: "1 1 130px" }}>
                  <span style={{ fontSize: 12, color: "var(--muted)", display: "block", marginBottom: 5 }}>{t("lot.unitCost")}</span>
                  <input type="number" min={0} step="any" inputMode="decimal" data-testid="cnt-new-cost"
                         value={n.unit_cost || ""} onChange={(e) => setNew(n.key, { unit_cost: Number(e.target.value) })}
                         style={{ ...inputStyle, height: 42 }} />
                </label>
                <label style={{ flex: "2 1 180px" }}>
                  <span style={{ fontSize: 12, color: "var(--muted)", display: "block", marginBottom: 5 }}>{t("lot.reason")}</span>
                  <input value={n.reason || ""} maxLength={150} data-testid="cnt-new-reason"
                         placeholder={t("lot.newLotReasonPlaceholder")}
                         onChange={(e) => setNew(n.key, { reason: e.target.value })}
                         style={{ ...inputStyle, height: 42 }} />
                </label>
                <button className="btn btn-ghost" aria-label={t("common.delete")} data-testid="cnt-new-remove"
                        onClick={() => setNews(news.filter((x) => x.key !== n.key))}
                        style={{ height: 42, color: "var(--danger)" }}>
                  <Trash size={16} aria-hidden />
                </button>
              </div>
            ))}
            {news.length > 0 && needExpiry && expiryMissing && (
              <div role="alert" style={{ color: "var(--warn)", fontSize: 12.5, marginTop: 10 }}>{t("lot.newLotExpiryRequired")}</div>
            )}
            {/* Tannarxni operator aytadi — u HUJJAT narxi emas, shuning uchun partiya
                «tuzatish» sifatida yoziladi va hisobotda shunday ko'rinadi. */}
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 10 }}>{t("lot.newLotCostNote")}</div>
          </section>
        )}

        {prod && (
          <section className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <div style={{ fontSize: 13.5 }} data-testid="cnt-summary">
                <div>{t("lot.countTotal")}: <b className="tabular">{total} {prod.unit_code || ""}</b></div>
                <div style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 3 }}>
                  {t("lot.countBreakdown", { u: untouchedQty, c: countedQty, n: newQty })}
                </div>
              </div>
              <button className="btn btn-primary" data-testid="cnt-submit" disabled={!canSend}
                      onClick={() => setAsk(true)} style={{ height: 46, padding: "0 22px" }}>
                {t("lot.countSubmit")}
              </button>
            </div>
          </section>
        )}
      </div>

      {ask && prod && (
        <Confirm title={t("lot.confirmCountTitle")} confirmLabel={t("lot.countSubmit")} busy={busy}
                 onCancel={() => setAsk(false)} onConfirm={send}
                 lines={[
                   t("lot.confirmIrreversible"),
                   `${prod.name} — ${t("lot.countTotal")}: ${total} ${prod.unit_code || ""}`,
                   ...touched.map((r) => `${r.batch_number || t("lot.noBatchNo")}: ${r.remaining_qty} → ${counted[r.id]}`),
                   ...(news.length ? [t("lot.confirmNewLots", { n: news.length, q: newQty })] : []),
                 ]} />
      )}
    </main>
  );
}
