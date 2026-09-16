import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { CheckCircle } from "@phosphor-icons/react";
import { fmt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { lotQuery, newClientUuid, writeoff, type LotList } from "@/lib/lots";
import { Topbar, inputStyle, useGet } from "@/components/ui";
import {
  Confirm, CostBadge, DormantNotice, ExpiryBadge, ProductPicker, State, WriteClosed,
  useAvailability, useNarrow, type PickedProduct,
} from "@/components/lotui";

const REASONS = ["expired", "damaged", "lost", "other"];

/**
 * HISOBDAN CHIQARISH — partiya darajasida.
 *
 * ⚠️  TIZIM TAXMIN QILMAYDI. Qaysi jismoniy partiya tashlanayotganini faqat
 *     operator biladi; shu bois umumiy miqdor emas, HAR PARTIYA alohida
 *     kiritiladi (server ham shuni talab qiladi).
 *
 * ⚠️  KASSAGA TEGMAYDI. Tashlangan tovar — zaxira yo'qotishi, pul amali EMAS.
 *     Shu bois bu ekranda kassa/smena bilan bog'liq hech narsa YO'Q.
 */
export function Hisobdan() {
  const t = useT();
  const narrow = useNarrow();
  const av = useAvailability();
  const loc = useLocation();
  const params = new URLSearchParams(loc.search || loc.pathname.split("?")[1] || "");
  const preProduct = params.get("product");
  const preLot = params.get("lot");

  const [prod, setProd] = useState<PickedProduct | null>(null);
  const [qty, setQty] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("expired");
  const [note, setNote] = useState("");
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState<{ qty: number } | null>(null);
  // ⚠️  BITTA amal — BITTA kalit. Ikki marta bosilsa server IKKINCHISINI rad etadi
  //     (dublikat), qoldiq ikki marta kamaymaydi.
  const [cu, setCu] = useState(newClientUuid());

  const path = useMemo(() => prod
    ? "/lots/batches" + lotQuery({ product_id: prod.id, status: "open", sort: "expiry", limit: 200 })
    : "", [prod]);
  const lots = useGet<LotList>(path);

  // Partiya ekranidan «hisobdan chiqarish» bosilgan bo'lsa — mahsulot oldindan tanlanadi.
  // ⚠️  Butun katalog YUKLANMAYDI: shu mahsulotning BITTA partiyasi so'raladi va
  //     nomi o'sha javobdan olinadi.
  const pre = useGet<LotList>(preProduct && !prod
    ? "/lots/batches" + lotQuery({ product_id: preProduct, status: "any", limit: 1 }) : "");
  useEffect(() => {
    const row = pre.data?.lots?.[0];
    if (!preProduct || prod || !row) return;
    setProd({ id: row.product_id, name: row.product || "", unit_code: row.unit_code, stock: 0 });
  }, [preProduct, prod, pre.data]);

  const rows = prod ? (lots.data?.lots || []) : [];
  const picked = rows
    .map((r) => ({ r, n: Number(qty[r.id] || 0) }))
    .filter((x) => x.n > 0);
  const total = picked.reduce((s, x) => s + x.n, 0);
  const cost = picked.reduce((s, x) => s + x.n * x.r.unit_cost, 0);
  const tooMuch = picked.some((x) => x.n > x.r.remaining_qty);
  const canSend = !!prod && total > 0 && !tooMuch && !!av.data?.can_write;

  async function send() {
    setBusy(true); setErr("");
    try {
      const res = await writeoff({
        product_id: prod!.id, qty: total,
        reason: [reason, note.trim()].filter(Boolean).join(": ").slice(0, 200),
        lots: picked.map((x) => ({ stock_batch_id: x.r.id, qty: x.n })),
        client_uuid: cu,
      });
      setAsk(false);
      setDone({ qty: total });
      setQty({}); setNote("");
      setCu(newClientUuid());          // keyingi amal — YANGI kalit
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
        <Topbar title={t("nav.hisobdan")} sub={t("lot.subWriteoff")} />
        <div className="scroll" style={{ flex: 1 }}><DormantNotice av={av.data} /></div>
      </main>
    );
  }

  return (
    <main className="main">
      <Topbar title={t("nav.hisobdan")} sub={t("lot.subWriteoff")} />
      <div className="scroll" style={{ flex: 1, padding: narrow ? 14 : 24, maxWidth: 860 }}>
        {av.data && !av.data.can_write && <div style={{ marginBottom: 14 }}><WriteClosed av={av.data} /></div>}

        {done && (
          <div role="status" data-testid="writeoff-done"
               style={{ display: "flex", gap: 9, alignItems: "center", padding: "12px 15px", borderRadius: 12, background: "var(--ok-soft)", color: "var(--ok)", fontWeight: 600, fontSize: 13.5, marginBottom: 14 }}>
            <CheckCircle size={18} weight="fill" aria-hidden />{t("lot.writeoffDone", { n: done.qty })}
          </div>
        )}
        {err && <div role="alert" data-testid="writeoff-error" style={{ color: "var(--danger)", marginBottom: 14, fontSize: 13.5 }}>{err}</div>}

        <section className="card" style={{ marginBottom: 14 }}>
          <h2 style={{ fontSize: 14, margin: "0 0 10px" }}>{t("lot.step1")}</h2>
          <ProductPicker value={prod} onPick={(p) => { setProd(p); setQty({}); setDone(null); }} testid="wo-product" />
        </section>

        {prod && (
          <section className="card" style={{ marginBottom: 14 }}>
            <h2 style={{ fontSize: 14, margin: "0 0 4px" }}>{t("lot.step2")}</h2>
            <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 12px" }}>{t("lot.pickLotsHint")}</p>
            <State loading={lots.loading && !lots.data} err={lots.err} onRetry={lots.reload}
                   empty={!lots.loading && rows.length === 0} emptyText={t("lot.noOpenLots")}>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {rows.map((r) => {
                  const n = Number(qty[r.id] || 0);
                  const over = n > r.remaining_qty;
                  const highlight = preLot === r.id;
                  return (
                    <div key={r.id} data-testid={"wo-lot-" + r.id}
                         style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: 12, borderRadius: 12, border: `1px solid ${highlight ? "var(--accent-border)" : "var(--border)"}`, background: "var(--card-alt)" }}>
                      <div style={{ flex: "1 1 220px", minWidth: 0 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                          <span style={{ fontWeight: 700 }}>{r.batch_number || t("lot.noBatchNo")}</span>
                          <ExpiryBadge bucket={r.bucket} daysLeft={r.days_left} />
                          <CostBadge basis={r.cost_basis} />
                        </div>
                        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4 }}>
                          {t("lot.expiry")}: {r.expiry_date || "—"} · {t("lot.remaining")}: <span className="tabular">{r.remaining_qty} {r.unit_code || ""}</span>
                          {" · "}{t("lot.unitCost")}: <span className="tabular">{fmt(r.unit_cost)}</span>
                        </div>
                      </div>
                      <label style={{ flex: "0 0 130px" }}>
                        <span className="sr-only">{t("lot.writeoffQty")}</span>
                        <input type="number" min={0} max={r.remaining_qty} step="any" inputMode="decimal"
                               value={qty[r.id] || ""} data-testid={"wo-qty-" + r.id}
                               aria-invalid={over || undefined}
                               onChange={(e) => setQty({ ...qty, [r.id]: e.target.value })}
                               style={{ ...inputStyle, height: 42, borderColor: over ? "var(--danger)" : "var(--border-input)" }} />
                      </label>
                    </div>
                  );
                })}
              </div>
              {tooMuch && <div role="alert" style={{ color: "var(--danger)", fontSize: 12.5, marginTop: 10 }}>{t("lot.overRemaining")}</div>}
            </State>
          </section>
        )}

        {prod && (
          <section className="card">
            <h2 style={{ fontSize: 14, margin: "0 0 10px" }}>{t("lot.step3")}</h2>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
              <label style={{ flex: "1 1 200px" }}>
                <span style={{ fontSize: 12.5, color: "var(--muted)", display: "block", marginBottom: 5 }}>{t("lot.reason")}</span>
                <select value={reason} onChange={(e) => setReason(e.target.value)} data-testid="wo-reason"
                        style={{ ...inputStyle, height: 44 }}>
                  {REASONS.map((r) => <option key={r} value={r}>{t("lot.reason." + r)}</option>)}
                </select>
              </label>
              <label style={{ flex: "2 1 260px" }}>
                <span style={{ fontSize: 12.5, color: "var(--muted)", display: "block", marginBottom: 5 }}>{t("lot.note")}</span>
                <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={150}
                       data-testid="wo-note" placeholder={t("lot.notePlaceholder")}
                       style={{ ...inputStyle, height: 44 }} />
              </label>
            </div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", paddingTop: 12, borderTop: "1px dashed var(--border-input)" }}>
              <div style={{ fontSize: 13.5 }} data-testid="wo-summary">
                {t("lot.writeoffTotal")}: <b className="tabular">{total} {prod.unit_code || ""}</b>
                <span style={{ color: "var(--muted)" }}> · {t("lot.costTotal")}: <span className="tabular">{fmt(cost)}</span></span>
              </div>
              <button className="btn" data-testid="wo-submit" disabled={!canSend}
                      onClick={() => setAsk(true)}
                      style={{ height: 46, padding: "0 22px", background: "var(--danger)", color: "#fff", opacity: canSend ? 1 : 0.45, cursor: canSend ? "pointer" : "not-allowed" }}>
                {t("lot.writeoffAction")}
              </button>
            </div>
            {/* Kassa bilan bog'liq emasligi ATAYLAB aytiladi — operator «pul qayerda?» deb qidirmasin. */}
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 10 }}>{t("lot.noCashEffect")}</div>
          </section>
        )}
      </div>

      {ask && prod && (
        <Confirm title={t("lot.confirmWriteoffTitle")}
                 confirmLabel={t("lot.writeoffAction")} busy={busy}
                 onCancel={() => setAsk(false)} onConfirm={send}
                 lines={[
                   t("lot.confirmIrreversible"),
                   `${prod.name} — ${total} ${prod.unit_code || ""} (${picked.length} ${t("lot.lotsWord")})`,
                   ...picked.map((x) => `${x.r.batch_number || t("lot.noBatchNo")}: ${x.n}`),
                 ]} />
      )}
    </main>
  );
}
