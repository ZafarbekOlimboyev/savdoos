import { useRef, useState } from "react";
import { X } from "@phosphor-icons/react";
import { fmt, parseServerTime } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { newClientUuid, resolveShortfall, type ShortfallDetail } from "@/lib/lots";
import { inputStyle, useGet } from "@/components/ui";
import { Confirm, CostBadge, ExpiryBadge, KV, State, useModalFocus, useNarrow } from "@/components/lotui";

/**
 * QOLDIQNI HAQIQIY PARTIYAGA BOG'LASH.
 *
 * ⚠️  BIR NECHTA PARTIYA — BITTA AMAL. Ikkita partiyani ikkita so'rov bilan
 *     yuborish yarim bog'langan holat qoldirardi (birinchisi o'tib, ikkinchisi
 *     yiqilsa). Shu bois hamma qator bitta `allocations` ro'yxatida ketadi.
 *
 * ⚠️  IKKI MARTA BOSISH — BITTA YOZUV. `client_uuid` amal boshlanishida bir
 *     marta yasaladi; takror yuborilsa server uni DUBLIKAT deb qaytaradi va
 *     qoldiq ikki marta bog'lanmaydi.
 */
export function QoldiqTafsilot({ id, canWrite, onClose, onChanged }: {
  id: string; canWrite: boolean; onClose: () => void; onChanged: () => void;
}) {
  const t = useT();
  const narrow = useNarrow();
  const boxRef = useRef<HTMLElement>(null);
  const { data: d, err, loading, reload } = useGet<ShortfallDetail>("/lots/shortfalls/" + id);
  useModalFocus(boxRef, onClose, true);
  const [alloc, setAlloc] = useState<Record<string, string>>({});
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [sendErr, setSendErr] = useState("");
  const [cu, setCu] = useState(newClientUuid());

  const lines = (d?.candidate_lots || [])
    .map((c) => ({ c, n: Number(alloc[c.id] || 0) }))
    .filter((x) => x.n > 0);
  const attach = lines.reduce((s, x) => s + x.n, 0);
  const open = d?.open_qty ?? 0;
  const over = attach > open || lines.some((x) => x.n > x.c.remaining_qty);
  const variance = lines.reduce((s, x) => s + x.n * x.c.unit_variance, 0);
  const canSend = canWrite && attach > 0 && !over;

  async function send() {
    setBusy(true); setSendErr("");
    try {
      const res = await resolveShortfall(id, {
        allocations: lines.map((x) => ({ stock_batch_id: x.c.id, qty: x.n })),
        reason: "manager UI", client_uuid: cu,
      });
      setAsk(false);
      // Operator tilida: nechta bog'landi va nechtasi ANIQLANMAGAN qoldi.
      setMsg(t("lot.resolveResult", { a: res.qty_now ?? attach, r: res.open_qty ?? Math.max(open - attach, 0) }));
      setAlloc({});
      setCu(newClientUuid());
      reload();
      onChanged();
      if (res.duplicate) setSendErr(t("lot.alreadyApplied"));
    } catch (e: any) {
      setSendErr(e.message);
      setAsk(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.5)", zIndex: 25, display: "flex", justifyContent: narrow ? "center" : "flex-end" }}>
      <aside ref={boxRef} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" className="scroll"
             aria-label={t("lot.subShortfall")} data-testid="sf-drawer"
             style={{ width: narrow ? "100%" : 600, maxWidth: "100%", height: "100%", background: "var(--card)", borderLeft: "1px solid var(--border)", padding: narrow ? 16 : 24, overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
          <div style={{ fontSize: 18, fontWeight: 800 }}>{d?.product || t("lot.subShortfall")}</div>
          <button onClick={onClose} aria-label={t("common.close")} data-testid="sf-close"
                  style={{ border: "none", background: "var(--surface)", borderRadius: 9, width: 34, height: 34, cursor: "pointer", color: "var(--muted)", flex: "none" }}>
            <X size={16} aria-hidden />
          </button>
        </div>

        {msg && <div role="status" data-testid="sf-result" style={{ padding: "12px 15px", borderRadius: 12, background: "var(--ok-soft)", color: "var(--ok)", fontWeight: 600, fontSize: 13.5, marginBottom: 14 }}>{msg}</div>}
        {sendErr && <div role="alert" data-testid="sf-error" style={{ color: "var(--danger)", marginBottom: 14, fontSize: 13.5 }}>{sendErr}</div>}

        <State loading={loading && !d} err={err} onRetry={reload}>
          {d && (
            <>
              <div className="card" style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 14 }}>
                <KV k={t("lot.openQty")} v={<span className="tabular">{d.open_qty} {d.unit_code || ""}</span>} />
                <KV k={t("lot.attachedQty")} v={<span className="tabular">{d.resolved_qty}</span>} />
                {/* Chek raqami SOTUV HUJJATI: ruxsatsiz null keladi. «Ruxsat yo'q» ni «chek yo'q»
                    («—») dan ajratamiz — PartiyaTafsilot bilan bir xil qoida. */}
                {d.sale && <KV k={t("lot.fromReceipt")} v={<span data-testid="sf-receipt">{`${d.sale.receipt_no || (d.redacted?.sales ? t("lot.restricted") : "—")} · ${parseServerTime(d.sale.sold_at)?.toLocaleString("ru-RU") || "—"}`}</span>} />}
                {d.sale?.cashier && <KV k={t("lot.cashier")} v={d.sale.cashier} />}
                <KV k={t("lot.estimatedCost")} v={<span className="tabular">{fmt(d.unit_cost)}</span>} />
                <KV k={t("lot.profitEffect")} v={<span className="tabular">{fmt(d.cogs_variance)}</span>} />
              </div>

              {/* «Taxminiy» so'zi nimani anglatishini shu yerda tushuntiramiz.
                  Qisman yopilgan qarzda tannarx ARALASH: bir qismi haqiqiy
                  partiyadan, qolgani hali taxminiy. */}
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 14 }}>
                <CostBadge basis="estimated" mixed={d.resolved_qty > 0 && d.open_qty > 0} />
                <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
                  {d.resolved_qty > 0 && d.open_qty > 0 ? t("lot.partlyResolvedNote") : t("lot.provisionalNote")}
                </span>
              </div>

              {d.resolutions.length > 0 && (
                <section style={{ marginBottom: 16 }}>
                  <h2 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", margin: "0 0 9px" }}>{t("lot.historyTitle")}</h2>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {d.resolutions.map((r) => (
                      <div key={r.id} style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 13, padding: "9px 12px", borderRadius: 10, background: "var(--card-alt)" }}>
                        <span>{r.batch_number || t("lot.noBatchNo")} · <span className="tabular">{r.qty}</span></span>
                        <span style={{ color: "var(--muted)" }} className="tabular">{fmt(r.variance)}</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {d.open_qty > 0 && canWrite && (
                <section>
                  <h2 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", margin: "0 0 4px" }}>{t("lot.attachTitle")}</h2>
                  <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 12px" }}>{t("lot.attachHint")}</p>
                  {d.candidate_lots.length === 0 && (
                    <div data-testid="sf-no-candidates" style={{ fontSize: 13, color: "var(--muted)", padding: 14, borderRadius: 11, background: "var(--surface)" }}>
                      {t("lot.noCandidates")}
                    </div>
                  )}
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {d.candidate_lots.map((c) => (
                      <div key={c.id} data-testid={"sf-cand-" + c.id}
                           style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: 12, borderRadius: 12, border: `1px solid ${c.own_unattributed ? "var(--accent-border)" : "var(--border)"}`, background: "var(--card-alt)" }}>
                        <div style={{ flex: "1 1 220px", minWidth: 0 }}>
                          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                            <span style={{ fontWeight: 700 }}>{c.batch_number || t("lot.noBatchNo")}</span>
                            <ExpiryBadge bucket={c.bucket} daysLeft={c.days_left} />
                            <CostBadge basis={c.cost_basis} />
                            {c.own_unattributed && (
                              <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 8px", borderRadius: 7, background: "var(--accent-soft)", color: "var(--accent-strong)" }}>
                                {t("lot.ownReturned")}
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4 }}>
                            {t("lot.remaining")}: <span className="tabular">{c.remaining_qty}</span>
                            {" · "}{t("lot.unitCost")}: <span className="tabular">{fmt(c.unit_cost)}</span>
                            {" · "}{t("lot.ifFull")}: <span className="tabular">{fmt(c.variance_if_full)}</span>
                          </div>
                        </div>
                        <label style={{ flex: "0 0 120px" }}>
                          <span className="sr-only">{t("lot.attachQty")}</span>
                          <input type="number" min={0} step="any" inputMode="decimal"
                                 value={alloc[c.id] || ""} data-testid={"sf-qty-" + c.id}
                                 onChange={(e) => setAlloc({ ...alloc, [c.id]: e.target.value })}
                                 style={{ ...inputStyle, height: 42 }} />
                        </label>
                      </div>
                    ))}
                  </div>

                  {d.candidate_lots.length > 0 && (
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 14, paddingTop: 12, borderTop: "1px dashed var(--border-input)" }}>
                      <div style={{ fontSize: 13.5 }} data-testid="sf-summary">
                        <div>{t("lot.willAttach", { a: attach, r: Math.max(open - attach, 0) })}</div>
                        <div style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 3 }}>
                          {t("lot.profitEffect")}: <span className="tabular">{fmt(variance)}</span>
                        </div>
                      </div>
                      <button className="btn btn-primary" data-testid="sf-submit" disabled={!canSend || busy}
                              onClick={() => setAsk(true)} style={{ height: 46, padding: "0 20px", opacity: canSend && !busy ? 1 : 0.45 }}>
                        {t("lot.attachAction")}
                      </button>
                    </div>
                  )}
                  {over && <div role="alert" style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 10 }}>{t("lot.attachTooMuch")}</div>}
                </section>
              )}
            </>
          )}
        </State>
      </aside>

      {ask && d && (
        <Confirm title={t("lot.confirmAttachTitle")} confirmLabel={t("lot.attachAction")} busy={busy}
                 onCancel={() => setAsk(false)} onConfirm={send}
                 lines={[
                   t("lot.confirmAttachBody"),
                   t("lot.willAttach", { a: attach, r: Math.max(open - attach, 0) }),
                   `${t("lot.profitEffect")}: ${fmt(variance)}`,
                 ]} />
      )}
    </div>
  );
}
