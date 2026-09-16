import { useRef } from "react";
import { ClipboardText, Trash, X } from "@phosphor-icons/react";
import { fmt, parseServerTime } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { LotDetail } from "@/lib/lots";
import { td, th, useGet } from "@/components/ui";
import { CostBadge, ExpiryBadge, KV, State, useModalFocus, useNarrow } from "@/components/lotui";

function when(s: string | null): string {
  const d = parseServerTime(s);
  return d ? d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
}

/**
 * Partiya tafsiloti — «bu partiya QAYERDAN keldi va QAYERGA ketdi».
 *
 * ⚠️  TARIX SERVERDAN KELADI. UI sotuv/qaytarish/harakatlarni o'zi yig'sa,
 *     allokatsiyalarni bilmagani uchun «qancha sotilgan» raqami partiya
 *     qoldig'iga MOS KELMASDI va operator qaysi biriga ishonishni bilmasdi.
 */
export function LotDrawer({ id, onClose, canWrite, onWriteoff, onCount }: {
  id: string; onClose: () => void; canWrite: boolean;
  onWriteoff: (productId: string, lotId: string) => void;
  onCount: (productId: string) => void;
}) {
  const t = useT();
  const narrow = useNarrow();
  const boxRef = useRef<HTMLElement>(null);
  const { data: d, err, loading, reload } = useGet<LotDetail>("/lots/batches/" + id);
  // Fokus oyna ichiga kiradi, Tab tuzoqda qoladi, Escape yopadi, yopilgach
  // fokus qaysi qatordan kelgan bo'lsa o'sha yerga qaytadi.
  useModalFocus(boxRef, onClose, true);

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.5)", zIndex: 25, display: "flex", justifyContent: narrow ? "center" : "flex-end" }}>
      <aside ref={boxRef} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true"
             aria-label={t("lot.detailTitle")} data-testid="lot-drawer" className="scroll"
             style={{ width: narrow ? "100%" : 560, maxWidth: "100%", height: "100%", background: "var(--card)", borderLeft: "1px solid var(--border)", padding: narrow ? 16 : 24, overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 18, fontWeight: 800 }}>{d?.product || t("lot.detailTitle")}</div>
            <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 3 }}>
              {t("lot.batchNo")}: {d?.batch_number || "—"}
            </div>
          </div>
          <button onClick={onClose} aria-label={t("common.close")} data-testid="drawer-close"
                  style={{ border: "none", background: "var(--surface)", borderRadius: 9, width: 34, height: 34, cursor: "pointer", color: "var(--muted)", flex: "none" }}>
            <X size={16} aria-hidden />
          </button>
        </div>

        <State loading={loading && !d} err={err} onRetry={reload}>
          {d && (
            <>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
                <ExpiryBadge bucket={d.bucket} daysLeft={d.days_left} />
                <CostBadge basis={d.cost_basis} />
                <span style={{ fontSize: 11.5, fontWeight: 700, padding: "3px 9px", borderRadius: 7, background: "var(--surface)", color: "var(--text3)" }}>
                  {t("lot.src." + (d.source_type || "unknown"))}
                </span>
              </div>

              <div className="card" style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 14 }}>
                <KV k={t("lot.expiry")} v={d.expiry_date || t("lot.bucket.no_expiry")} />
                <KV k={t("lot.businessDate")} v={d.business_date} />
                <KV k={t("lot.received")} v={`${d.received_qty} ${d.unit_code || ""} · ${when(d.received_at)}`} />
                <KV k={t("lot.remaining")} v={`${d.remaining_qty} ${d.unit_code || ""}`} />
                <KV k={t("lot.unitCost")} v={fmt(d.unit_cost)} />
                <KV k={t("lot.value")} v={fmt(d.value)} />
                {d.branch && <KV k={t("lot.branch")} v={d.branch} />}
                {d.supplier && <KV k={t("lot.supplier")} v={d.supplier} />}
              </div>

              {/* MANBA — hujjatga bog'lanish. «Qayerdan» savoliga aniq javob. */}
              <Section title={t("lot.sourceTitle")}>
                <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                  <KV k={t("lot.sourceType")} v={t("lot.src." + (d.source.type || "unknown"))} />
                  {d.source.receiving && <KV k={t("lot.receivingDoc")} v={when(d.source.receiving.committed_at || d.source.receiving.created_at)} />}
                  {d.source.purchase && (
                    <>
                      <KV k={t("lot.purchaseDoc")} v={d.source.purchase.doc_no || "—"} />
                      <KV k={t("lot.purchaseDate")} v={d.source.purchase.purchase_date || "—"} />
                    </>
                  )}
                  {d.source.external_lot_id && <KV k={t("lot.externalId")} v={d.source.external_lot_id} />}
                  {!d.source.receiving && !d.source.purchase && !d.source.external_lot_id && (
                    <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{t("lot.noSourceDoc")}</div>
                  )}
                </div>
              </Section>

              {/* TARIX — chiqim hujjatlari. Har qator o'z hujjatini nomlaydi. */}
              <Section title={t("lot.historyTitle")}>
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 13, marginBottom: 10 }}>
                  <span>{t("lot.soldQty")}: <b className="tabular">{d.totals.sold_qty}</b></span>
                  <span>{t("lot.returnedQty")}: <b className="tabular">{d.totals.returned_qty}</b></span>
                  <span>{t("lot.movedQty")}: <b className="tabular">{d.totals.movement_qty}</b></span>
                  <span>{t("lot.attachedQty")}: <b className="tabular">{d.totals.resolved_qty}</b></span>
                </div>
                {/* ⚠️  Jadval O'Z konteyneri ichida suriladi — sahifa emas. 390px
                    da ustunlar sig'maydi va butun drawer'ni surish operatorni
                    adashtirardi. */}
                <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 360 }} data-testid="lot-history">
                  <caption className="sr-only">{t("lot.historyTitle")}</caption>
                  <thead><tr style={{ background: "var(--card-alt)" }}>
                    <th style={th} scope="col">{t("lot.event")}</th>
                    <th style={th} scope="col">{t("lot.doc")}</th>
                    <th style={{ ...th, textAlign: "right" }} scope="col">{t("lot.qty")}</th>
                    <th style={th} scope="col">{t("lot.when")}</th>
                  </tr></thead>
                  <tbody>
                    {d.sales.map((s) => (
                      <tr key={"s" + s.sale_id}>
                        <td style={td}>{t("lot.ev.sale")}</td>
                        <td style={{ ...td, color: "var(--text3)" }}>{s.receipt_no || "—"}</td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">−{s.qty}</td>
                        <td style={{ ...td, color: "var(--muted)" }}>{when(s.sold_at)}</td>
                      </tr>
                    ))}
                    {d.returns.map((r) => (
                      <tr key={"r" + r.return_id}>
                        <td style={td}>{t("lot.ev.return")}</td>
                        <td style={{ ...td, color: "var(--text3)" }}>{r.return_no || "—"}</td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">+{r.qty}</td>
                        <td style={{ ...td, color: "var(--muted)" }}>{when(r.created_at)}</td>
                      </tr>
                    ))}
                    {d.movements.map((m) => (
                      <tr key={"m" + m.movement_id}>
                        <td style={td}>{t("lot.ev." + m.type)}</td>
                        <td style={{ ...td, color: "var(--text3)" }}>{m.employee || m.reason || "—"}</td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">{m.qty}</td>
                        <td style={{ ...td, color: "var(--muted)" }}>{when(m.created_at)}</td>
                      </tr>
                    ))}
                    {d.resolutions.map((r) => (
                      <tr key={"x" + r.id}>
                        <td style={td}>{t("lot.ev.attach")}</td>
                        <td style={{ ...td, color: "var(--text3)" }}>
                          {t("lot.varianceShort")}: <span className="tabular">{fmt(r.variance)}</span>
                        </td>
                        <td style={{ ...td, textAlign: "right" }} className="tabular">{r.qty}</td>
                        <td style={{ ...td, color: "var(--muted)" }}>{when(r.resolved_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
                {!d.sales.length && !d.returns.length && !d.movements.length && !d.resolutions.length && (
                  <div style={{ padding: 18, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
                    {t("lot.noHistory")}
                  </div>
                )}
              </Section>

              {canWrite && (
                <div style={{ display: "flex", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
                  <button className="btn" data-testid="drawer-writeoff"
                          onClick={() => onWriteoff(d.product_id, d.id)}
                          style={{ flex: 1, minWidth: 180, height: 46, border: "1.5px solid var(--danger-border)", background: "var(--card)", color: "var(--danger)", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                    <Trash size={17} aria-hidden />{t("lot.writeoffAction")}
                  </button>
                  <button className="btn btn-ghost" data-testid="drawer-count"
                          onClick={() => onCount(d.product_id)}
                          style={{ flex: 1, minWidth: 180, height: 46, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
                    <ClipboardText size={17} aria-hidden />{t("lot.countAction")}
                  </button>
                </div>
              )}
            </>
          )}
        </State>
      </aside>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 16 }}>
      <h2 style={{ fontSize: 13, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", margin: "0 0 9px" }}>{title}</h2>
      {children}
    </section>
  );
}
