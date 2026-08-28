import { useMemo, useRef, useState } from "react";
import { get, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";

interface RecentSale { id: string; receipt_no: string; sold_at: string; method: string; total: number }
interface FoundItem { product_id: string; name: string; qty: number; unit_price: number; barcode: string; barcodes?: string[] }
interface Found { id: string; receipt_no: string; uid: string; method: string; sold_at: string; cashier: string; total: number; items: FoundItem[] }

const REASONS = [["customer", "Mijoz qaytardi"], ["defective", "Nuqsonli"], ["wrong_item", "Noto'g'ri mahsulot"], ["other", "Boshqa"]];
const M: Record<string, string> = { cash: "Naqd", card: "Karta", qr: "QR", credit: "Qarz" };

function barcodeBars(uid: string) {
  const d = (uid || "").replace(/\D/g, "");
  const out: { w: string; bg: string }[] = [{ w: "2px", bg: "var(--text)" }, { w: "2px", bg: "transparent" }];
  for (let i = 0; i < d.length; i++) {
    const n = +d[i];
    out.push({ w: 1 + (n % 3) + "px", bg: "var(--text)" }, { w: 1 + ((n + i) % 3) + "px", bg: "transparent" }, { w: 1 + ((n * 3 + i) % 2) + "px", bg: "var(--text)" }, { w: "1px", bg: "transparent" });
  }
  out.push({ w: "2px", bg: "var(--text)" });
  return out;
}

export function Returns() {
  const recent = useGet<RecentSale[]>("/sales?limit=8");
  const t = useT();
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Found | null>(null);
  const [qty, setQty] = useState<Record<number, number>>({});
  const [confirmed, setConfirmed] = useState<Record<number, boolean>>({});
  const [scanVal, setScanVal] = useState("");
  const [scanErr, setScanErr] = useState("");
  const [reason, setReason] = useState("customer");
  const [toStock, setToStock] = useState(true);
  const [done, setDone] = useState<{ amount: number; label: string; summary: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const lastQ = useRef("");
  async function select(q: string) {
    lastQ.current = q;
    try {
      const f = await get<Found>(`/sales/find?q=${encodeURIComponent(q)}`);
      if (lastQ.current !== q) return;
      setFound(f); setQty({}); setConfirmed({}); setScanVal(""); setScanErr(""); setDone(null); setQuery("");
    } catch { if (lastQ.current === q) setScanErr(t("returns.receiptNotFound")); }
  }
  function onSearchKey(e: React.KeyboardEvent) {
    if (e.key === "Enter" && query.trim()) select(query.trim());
  }
  function scanCode(code: string) {
    if (!found) return;
    const c = code.replace(/\D/g, "");
    if (!c) return;
    // Mahsulotning BARCHA barcode'lari bilan solishtiramiz (birinchisi bilan emas)
    const idx = found.items.findIndex((it) => {
      const list = (it.barcodes && it.barcodes.length ? it.barcodes : [it.barcode]).filter(Boolean) as string[];
      return list.some((b) => b.replace(/\D/g, "") === c);
    });
    if (idx < 0) { setScanErr(t("returns.notInReceipt")); setScanVal(""); return; }
    setQty((p) => ({ ...p, [idx]: Math.min(found.items[idx].qty, (p[idx] || 0) + 1) }));
    setConfirmed((p) => ({ ...p, [idx]: true }));
    setScanErr(""); setScanVal("");
  }
  function bump(i: number, d: number, max: number) {
    setQty((p) => ({ ...p, [i]: Math.max(0, Math.min(max, (p[i] || 0) + d)) }));
  }

  const refund = useMemo(() => (found ? found.items.reduce((t, it, i) => t + (qty[i] || 0) * it.unit_price, 0) : 0), [found, qty]);
  const isCredit = found?.method === "credit";

  async function confirm() {
    if (!found || refund <= 0) return;
    setBusy(true);
    try {
      const items = found.items.map((it, i) => ({ product_id: it.product_id, qty: qty[i] || 0, unit_price: it.unit_price })).filter((x) => x.qty > 0);
      try {
        await post("/returns", { original_sale_id: found.id, reason, restock: toStock, refund_method: found.method, items });
      } catch (e: any) { setScanErr(e?.message || t("common.error")); return; }
      const rLabel = t("returns.reason_" + reason);
      setDone({
        amount: refund,
        label: isCredit ? t("returns.deductedFromCredit") : t("returns.refundedToCustomer"),
        summary: `${found.receipt_no} · ${isCredit ? t("returns.creditRefunded") : t("returns.viaMethod", { m: M[found.method] ? t("pay." + found.method) : found.method })} · ${rLabel} · ${toStock ? t("returns.toStockDone") : t("returns.writtenOff")}`,
      });
      setFound(null); recent.reload();
    } finally { setBusy(false); }
  }
  function reset() {
    setFound(null); setDone(null); setQty({}); setConfirmed({}); setQuery(""); setReason("customer"); setToStock(true);
  }

  return (
    <main className="main">
      <div className="topbar"><div><div className="h1">{t("nav.qaytarishlar")}</div><div className="sub">{t("returns.sub")}</div></div></div>
      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        {/* LEFT — find */}
        <div className="scroll" style={{ width: 390, flex: "none", overflowY: "auto", padding: "22px 24px", borderRight: "1px solid var(--line)" }}>
          <div className="card" style={{ padding: 18 }}>
            <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 10 }}>{t("returns.findReceipt")}</div>
            <div style={{ position: "relative" }}>
              <span style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", fontSize: 18 }}>▮▮</span>
              <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onSearchKey} placeholder={t("returns.findPlaceholder")} autoFocus
                style={{ width: "100%", height: 52, padding: "0 14px 0 48px", border: "1.5px solid var(--accent-border)", borderRadius: 12, background: "var(--card)", color: "var(--text)", fontSize: 14, fontWeight: 500, outline: "none", boxSizing: "border-box" }} />
            </div>
            <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}>{t("returns.findHint")}</div>
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", margin: "20px 4px 10px" }}>{t("returns.recentSales")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {(recent.data || []).map((r) => {
              const on = found?.id === r.id;
              return (
                <button key={r.id} onClick={() => select(r.receipt_no)} style={{ textAlign: "left", cursor: "pointer", display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", borderRadius: 12, border: `1.5px solid ${on ? "var(--accent)" : "var(--border)"}`, background: on ? "var(--surface-accent)" : "var(--card)" }}>
                  <div style={{ width: 38, height: 38, borderRadius: 10, background: "var(--surface)", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>🧾</div>
                  <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontSize: 13.5, fontWeight: 700 }}>{r.receipt_no}</div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{new Date(r.sold_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })} · {M[r.method] ? t("pay." + r.method) : r.method}</div></div>
                  <div style={{ fontSize: 14, fontWeight: 700 }} className="tabular">{fmt(r.total)}</div>
                </button>
              );
            })}
          </div>
        </div>

        {/* RIGHT — detail / empty / done */}
        <div className="scroll" style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "24px 28px" }}>
          {done ? (
            <div style={{ maxWidth: 460, margin: "40px auto 0", textAlign: "center" }}>
              <div style={{ width: 82, height: 82, margin: "0 auto 18px", borderRadius: "50%", background: "var(--ok-soft)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 44 }}>✅</div>
              <div style={{ fontSize: 22, fontWeight: 700 }}>{t("returns.done")}</div>
              <div style={{ fontSize: 14, color: "var(--muted)", marginTop: 6 }}>{done.summary}</div>
              <div className="card" style={{ marginTop: 20, textAlign: "left", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 20px" }}>
                <span style={{ fontSize: 13, color: "var(--muted)" }}>{done.label}</span>
                <span style={{ fontSize: 22, fontWeight: 800, color: "var(--danger)" }} className="tabular">{fmt(done.amount)}</span>
              </div>
              <button className="btn btn-primary" style={{ width: "100%", height: 52, marginTop: 20 }} onClick={reset}>{`↺ ${t("returns.newReturn")}`}</button>
            </div>
          ) : !found ? (
            <div style={{ height: "100%", minHeight: 420, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", color: "var(--faint)" }}>
              <div style={{ fontSize: 40 }}>▮▮▮</div>
              <div style={{ fontSize: 15, fontWeight: 600, color: "var(--muted)", marginTop: 12 }}>{t("returns.scanReceipt")}</div>
              <div style={{ fontSize: 13, marginTop: 5, maxWidth: 280 }}>{t("returns.emptyHint")}</div>
              {scanErr && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 12 }}>{scanErr}</div>}
            </div>
          ) : (
            <div style={{ maxWidth: 620 }}>
              <div className="card" style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div><div style={{ fontSize: 18, fontWeight: 800 }}>{found.receipt_no}</div><div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>{new Date(found.sold_at).toLocaleString("ru-RU")} · {M[found.method] ? t("pay." + found.method) : found.method} · {found.cashier}</div></div>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text3)" }}>{t("pos.total")} {fmt(found.total)}</span>
                </div>
                <div style={{ marginTop: 16, padding: 14, border: "1px dashed var(--border-input)", borderRadius: 12 }}>
                  <div style={{ display: "flex", alignItems: "stretch", height: 48, justifyContent: "center" }}>
                    {barcodeBars(found.uid).map((b, i) => <div key={i} style={{ width: b.w, background: b.bg }} />)}
                  </div>
                  <div style={{ textAlign: "center", fontSize: 12, letterSpacing: 4, color: "var(--text3)", marginTop: 8 }} className="tabular">{found.uid}</div>
                </div>
              </div>

              {isCredit && (
                <div style={{ display: "flex", gap: 11, padding: "14px 16px", marginBottom: 16, borderRadius: 14, background: "var(--warn-soft)", color: "var(--warn)" }}>
                  <span>📒</span><div style={{ fontSize: 12.5, lineHeight: 1.55 }}><b>{t("returns.creditWarnBold")}</b> {t("returns.creditWarnText")}</div>
                </div>
              )}

              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{ padding: "18px 20px 14px" }}>
                  <div style={{ fontSize: 14.5, fontWeight: 700, marginBottom: 4 }}>{t("returns.returnableItems")}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>{t("returns.rescanHint")}</div>
                  <div style={{ position: "relative", marginTop: 12 }}>
                    <span style={{ position: "absolute", left: 13, top: "50%", transform: "translateY(-50%)", fontSize: 16 }}>▮▮</span>
                    <input value={scanVal} onChange={(e) => setScanVal(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") scanCode(scanVal); }} placeholder={t("returns.itemScanPlaceholder")}
                      style={{ width: "100%", height: 44, padding: "0 14px 0 40px", border: "1.5px solid var(--accent-border)", borderRadius: 11, background: "var(--card)", color: "var(--text)", fontSize: 13.5, outline: "none", boxSizing: "border-box" }} />
                  </div>
                  {scanErr && <div style={{ display: "flex", gap: 9, marginTop: 10, padding: "11px 13px", borderRadius: 11, background: "var(--danger-soft)", color: "var(--danger)", fontSize: 12.5, lineHeight: 1.45 }}>⚠️ <span>{scanErr}</span></div>}
                </div>
                {found.items.map((it, i) => {
                  const hasBc = !!it.barcode, conf = !!confirmed[i], q = qty[i] || 0;
                  const tag = !hasBc ? [t("returns.tagNoScale"), "var(--border)", "var(--text3)"] : conf ? [t("returns.tagScanned"), "var(--ok-soft)", "var(--ok)"] : [t("returns.tagScanNeeded"), "var(--warn-soft)", "var(--warn)"];
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 20px", borderTop: "1px solid var(--surface)" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13.5, fontWeight: 600 }}>{it.name}</div>
                        <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 1 }}>{fmt(it.unit_price)} · {t("returns.sold")}: {it.qty}</div>
                        <div style={{ display: "inline-flex", alignItems: "center", gap: 5, marginTop: 6, fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 7, background: tag[1], color: tag[2] }}>{tag[0]}</div>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 2, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 9, padding: 2 }}>
                        <button onClick={() => bump(i, -1, it.qty)} style={{ width: 28, height: 28, border: "none", background: "none", cursor: "pointer", color: "var(--text3)", borderRadius: 7, fontSize: 16 }}>−</button>
                        <span style={{ minWidth: 28, textAlign: "center", fontSize: 14, fontWeight: 700, color: q > 0 ? "var(--danger)" : "var(--faint)" }}>{q}</span>
                        <button onClick={() => (hasBc ? scanCode(it.barcode) : bump(i, 1, it.qty))} style={{ height: 28, padding: hasBc ? "0 10px" : 0, width: hasBc ? "auto" : 28, border: "none", background: "var(--accent-soft)", cursor: "pointer", color: "var(--accent-strong)", borderRadius: 7, fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 5 }}>{hasBc ? t("returns.scanBtn") : "+"}</button>
                      </div>
                      <div style={{ width: 96, textAlign: "right", fontSize: 14, fontWeight: 700, color: q > 0 ? "var(--danger)" : "var(--faint)" }} className="tabular">{q > 0 ? "−" + fmt(q * it.unit_price) : "0"}</div>
                    </div>
                  );
                })}
                <div style={{ padding: "16px 20px", borderTop: "1px solid var(--surface)" }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text3)", marginBottom: 9 }}>{t("returns.reason")}</div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
                    {REASONS.map(([k, l]) => (
                      <button key={k} onClick={() => setReason(k)} style={{ height: 38, padding: "0 14px", borderRadius: 10, cursor: "pointer", fontSize: 12.5, fontWeight: 600, border: `1px solid ${reason === k ? "var(--accent)" : "var(--border)"}`, background: reason === k ? "var(--accent-soft)" : "var(--card)", color: reason === k ? "var(--accent-ink)" : "var(--muted)" }}>{t("returns.reason_" + k)}</button>
                    ))}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{ flex: 1 }}><div style={{ fontSize: 13, color: "var(--text2)", fontWeight: 600 }}>{t("returns.restockLabel")}</div><div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 1 }}>{t("returns.restockHint")}</div></div>
                    <button onClick={() => setToStock((v) => !v)} style={{ width: 48, height: 28, border: "none", borderRadius: 15, cursor: "pointer", background: toStock ? "var(--accent)" : "var(--faint)", position: "relative" }}><span style={{ position: "absolute", top: 3, left: toStock ? 23 : 3, width: 22, height: 22, borderRadius: "50%", background: "var(--card)" }} /></button>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 20px", background: "var(--surface)", borderTop: "1px solid var(--border-soft)" }}>
                  <div><div style={{ fontSize: 12.5, color: "var(--muted)" }}>{isCredit ? t("returns.deductFromCredit") : t("returns.refundSum") + " · " + (M[found.method] ? t("pay." + found.method) : found.method)}</div><div style={{ fontSize: 28, fontWeight: 800, color: "var(--danger)", marginTop: 2 }} className="tabular">−{fmt(refund)}</div></div>
                  <button onClick={confirm} disabled={busy || refund <= 0} style={{ height: 54, padding: "0 26px", border: "none", borderRadius: 13, cursor: "pointer", fontSize: 15, fontWeight: 700, color: "#fff", background: refund > 0 ? "var(--danger)" : "#d6b3b4" }}>{`↩ ${t("returns.confirmBtn")}`}</button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
