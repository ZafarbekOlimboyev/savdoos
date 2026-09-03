import { useEffect, useRef, useState } from "react";
import { get, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { useAuth } from "@/store/auth";
import { inputStyle } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { useLang } from "@/store/lang";

interface Current { id: string; opened_at: string; opening_cash: number }
interface Summary {
  opening: number; total_sales: number; receipts: number; by_method: Record<string, number>;
  naqd_sales: number; payin: number; payout: number; expected: number; opened_at: string;
  ops: { title: string; at: string; amount: number; in: boolean }[];
}
const M: Record<string, [string, string]> = { cash: ["Naqd", "var(--ok)"], card: ["Karta", "#6d5dd3"], qr: ["QR", "#12a3a3"], credit: ["Qarz", "var(--warn)"] };

function dur(from: string): string {
  // Backend UTC yuboradi; SQLite (dev) tz belgisisiz string berishi mumkin — 'Z' qo'shamiz,
  // aks holda lokal deb o'qilib "hozirgina ochilgan smena 6 soat" bo'lib ko'rinardi.
  const iso = /[Z+]|[+-]\d\d:\d\d$/.test(from.slice(10)) ? from : from + "Z";
  const ms = Date.now() - new Date(iso).getTime();
  const h = Math.floor(ms / 3.6e6), m = Math.floor((ms % 3.6e6) / 6e4);
  const lang = useLang.getState().lang;
  const uh = lang === "ru" ? "ч" : lang === "ky" ? "с" : lang === "uzc" ? "с" : "s";
  const um = lang === "ru" ? "мин" : lang === "ky" ? "мүн" : lang === "uzc" ? "мин" : "min";
  return `${h}${uh} ${m}${um}`;
}

export function Shift() {
  const employee = useAuth((s) => s.employee);
  const t = useT();
  const [cur, setCur] = useState<Current | null | undefined>(undefined);
  const [sum, setSum] = useState<Summary | null>(null);
  const [openCash, setOpenCash] = useState("");
  const [modal, setModal] = useState(false);
  const [counted, setCounted] = useState("");
  const [closed, setClosed] = useState<{ expected: number; counted: number; diff: number } | null>(null);
  const [cashType, setCashType] = useState("payin");
  const [cashAmt, setCashAmt] = useState("");
  const [cashReason, setCashReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const [loadErr, setLoadErr] = useState(false);
  // Barqaror idempotentlik kaliti — qayta bosilса kassa harakати ikki marta yozilмасин
  // (ux_cashmov_client_uuid). Muvaffaqiyatли qo'shishдан keyin yangilanadi.
  const cashUuid = useRef(crypto.randomUUID());
  async function load() {
    // MUHIM: tarmoq xatosi "smena yopiq" degani EMAS — aks holda kassir aldanib
    // qayta smena ochishga urinardi. Xato holatini alohida ko'rsatamiz.
    try {
      const c = await get<Current | null>("/shifts/current");
      setLoadErr(false);
      setCur(c);
      if (c) setSum(await get<Summary>(`/shifts/${c.id}/summary`).catch(() => null));
      else setSum(null);
    } catch {
      setLoadErr(true);
    }
  }
  useEffect(() => { load(); }, []);
  const [, setTick] = useState(0);
  // QA SHIFT-5: interval faqat davomiylik (dur) matnini emas, summary'ni ham yangilaydi — aks holda
  // boshqa terminal/POS savdosi (naqd)dan keyin "kutilgan naqd"/smena savdosi ekranda ESKIRIB qolardi.
  useEffect(() => { const tm = setInterval(() => { setTick((x) => x + 1); void load(); }, 60000); return () => clearInterval(tm); /* eslint-disable-next-line */ }, []);

  async function openShift() {
    setBusy(true); setErr("");
    try { await post("/shifts/open", { opening_cash: +openCash.replace(/\D/g, "") || 0 }); setOpenCash(""); await load(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function addCash() {
    if (!cur || !(+cashAmt.replace(/\D/g, ""))) return;
    setBusy(true); setErr("");
    try {
      await post(`/shifts/${cur.id}/cash`, { type: cashType, amount: +cashAmt.replace(/\D/g, ""), reason: cashReason, client_uuid: cashUuid.current });
      cashUuid.current = crypto.randomUUID();  // muvaffaqiyatдан keyin yangi kalit
      setCashAmt(""); setCashReason(""); await load();
    }
    catch (e: any) { setErr(e.message); await load(); } finally { setBusy(false); }
  }
  async function confirmClose() {
    if (!cur) return;
    setBusy(true); setErr("");
    try {
      const r = await post<{ expected_cash: number; counted_cash: number; difference: number }>(`/shifts/${cur.id}/close`, { counted_cash: +counted.replace(/\D/g, "") || 0 });
      setClosed({ expected: r.expected_cash, counted: r.counted_cash, diff: r.difference });
    } catch (e: any) { setErr(e.message); await load(); } finally { setBusy(false); }
  }
  function newShift() { setModal(false); setClosed(null); setCounted(""); load(); }

  const countedN = parseInt(counted.replace(/\D/g, ""), 10) || 0;
  const diff = sum ? countedN - sum.expected : 0;
  const hasCount = counted.replace(/\D/g, "").length > 0;

  // ── Smena yopiq — ochish formasi ───────────────────────────────
  if (cur === null) {
    return (
      <main className="main">
        <div className="topbar"><div><div className="h1">{t("nav.smena")}</div><div className="sub">{t("shift.sub")}</div></div></div>
        <div className="scroll" style={{ flex: 1, padding: 24, display: "flex", justifyContent: "center" }}>
          <div style={{ width: 440 }} className="card">
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>{t("shift.closed")}</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 16 }}>{t("shift.openHint")}</div>
            <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{t("shift.openingCash")}</label>
            <input value={openCash} onChange={(e) => setOpenCash(e.target.value.replace(/\D/g, ""))} placeholder="0" style={{ ...inputStyle, height: 52, fontSize: 20, fontWeight: 700, marginTop: 6 }} />
            {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
            <button className="btn btn-primary" style={{ width: "100%", height: 52, marginTop: 16 }} disabled={busy} onClick={openShift}>{busy ? "..." : t("shift.openBtn")}</button>
          </div>
        </div>
      </main>
    );
  }
  if (cur === undefined) {
    return <main className="main"><div className="topbar"><div className="h1">{t("nav.smena")}</div></div>
      <div style={{ padding: 24, color: loadErr ? "var(--danger)" : "var(--muted)" }}>
        {loadErr ? (
          <div>
            <div style={{ marginBottom: 12 }}>{t("common.error")} — {t("common.offline")}</div>
            <button className="btn btn-primary" onClick={load}>↻</button>
          </div>
        ) : t("shift.loading")}
      </div></main>;
  }

  const methodCards = Object.entries(sum?.by_method || {}).filter(([k]) => k in M);

  return (
    <main className="main">
      <div className="topbar">
        <div><div className="h1">{t("nav.smena")}</div><div className="sub">{t("shift.sub2")}</div></div>
        <button onClick={() => { setModal(true); setClosed(null); setCounted(""); }} className="btn" style={{ background: "var(--danger)", color: "#fff", padding: "12px 22px" }}>{`🔒 ${t("shift.closeBtn")}`}</button>
      </div>

      <div className="scroll" style={{ flex: 1, padding: "24px 28px 32px" }}>
        {/* Ochiq rejimdagi xatolar (kassa harakati/yopish) — ilgari umuman ko'rinmasdi */}
        {err && <div style={{ marginBottom: 14, padding: "11px 14px", borderRadius: 11, background: "var(--danger-soft)", color: "var(--danger)", fontSize: 13, fontWeight: 600 }}>{err}</div>}
        {/* status */}
        <div className="card" style={{ display: "flex", alignItems: "center", gap: 18, marginBottom: 20 }}>
          <div style={{ width: 52, height: 52, borderRadius: 14, background: "var(--accent)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 17, fontWeight: 700 }}>{(employee?.full_name || "?").charAt(0)}</div>
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 17, fontWeight: 700 }}>{employee?.full_name}</span>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5, fontWeight: 600, padding: "3px 10px", borderRadius: 20, background: "var(--ok-soft)", color: "var(--ok)" }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--ok)" }} />{t("shift.open")}</span>
            </div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 3 }}>{t("shift.startedFrom", { time: new Date(cur.opened_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) })}</div>
          </div>
          <div style={{ textAlign: "right" }}><div style={{ fontSize: 12, color: "var(--muted)" }}>{t("shift.duration")}</div><div style={{ fontSize: 20, fontWeight: 800 }}>{dur(cur.opened_at)}</div></div>
        </div>

        {/* stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 20 }}>
          <div className="card" style={{ padding: 18 }}><div style={{ fontSize: 12.5, color: "var(--muted)", fontWeight: 500 }}>{t("sales.shiftSales")}</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 6 }} className="tabular">{fmt(sum?.total_sales || 0)}</div></div>
          <div className="card" style={{ padding: 18 }}><div style={{ fontSize: 12.5, color: "var(--muted)", fontWeight: 500 }}>{t("sales.receipts")}</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 6 }}>{sum?.receipts ?? 0}</div><div style={{ fontSize: 11, color: "var(--muted)" }}>{t("sales.saleCount")}</div></div>
          {methodCards.slice(0, 2).map(([k, v]) => (
            <div key={k} className="card" style={{ padding: 18 }}><div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--muted)", fontWeight: 500 }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: M[k][1] }} />{t("pay." + k)}</div><div style={{ fontSize: 26, fontWeight: 800, marginTop: 6 }} className="tabular">{fmt(v)}</div></div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 18 }}>
          {/* cash drawer */}
          <div className="card">
            <div style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 15, fontWeight: 700, marginBottom: 16 }}>{`💰 ${t("shift.cashDrawer")}`}</div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {[
                [t("shift.openingBalance"), sum?.opening || 0, "var(--text2)", ""],
                [t("shift.cashSales"), sum?.naqd_sales || 0, "var(--ok)", "+"],
                [t("shift.cashIn"), sum?.payin || 0, "var(--ok)", "+"],
                [t("shift.cashOut"), sum?.payout || 0, "var(--danger)", "−"],
              ].map(([l, v, c, sign], i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "11px 0", borderTop: i ? "1px solid var(--surface)" : "none", fontSize: 13.5, color: "var(--text3)" }}>
                  <span>{l as string}</span><span style={{ fontWeight: 600, color: c as string }} className="tabular">{sign as string}{fmt(v as number)}</span>
                </div>
              ))}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: 16, marginTop: 12, borderRadius: 13, background: "var(--surface-accent)" }}>
                <span style={{ fontSize: 14, fontWeight: 700, color: "var(--text3)" }}>{t("shift.expectedCash")}</span><span style={{ fontSize: 26, fontWeight: 800 }} className="tabular">{fmt(sum?.expected || 0)}</span>
              </div>
            </div>
            {/* add cash */}
            <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
              {[["payin"], ["payout"], ["expense"]].map(([k]) => (
                <button key={k} onClick={() => setCashType(k)} style={{ flex: 1, height: 38, borderRadius: 10, cursor: "pointer", fontSize: 12.5, fontWeight: 600, border: `1.5px solid ${cashType === k ? "var(--accent)" : "var(--border)"}`, background: cashType === k ? "var(--accent-soft)" : "var(--card)", color: cashType === k ? "var(--accent-ink)" : "var(--muted)" }}>{t("shift.type_" + k)}</button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <input value={cashAmt} onChange={(e) => setCashAmt(e.target.value.replace(/\D/g, ""))} placeholder={t("shift.amount")} style={{ ...inputStyle, width: 130, height: 42 }} />
              <input value={cashReason} onChange={(e) => setCashReason(e.target.value)} placeholder={t("shift.note")} style={{ ...inputStyle, height: 42 }} />
              <button className="btn btn-primary" style={{ padding: "0 16px", height: 42 }} disabled={busy} onClick={addCash}>＋</button>
            </div>
          </div>

          {/* operations */}
          <div className="card">
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 16 }}>{t("shift.cashOps")}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {(sum?.ops || []).length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>{t("shift.noOps")}</div>}
              {(sum?.ops || []).map((o, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ width: 36, height: 36, borderRadius: 10, background: o.in ? "var(--ok-soft)" : "var(--danger-soft)", color: o.in ? "var(--ok)" : "var(--danger)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>{o.in ? "↓" : "↑"}</div>
                  <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontSize: 13, fontWeight: 600 }}>{o.title}</div><div style={{ fontSize: 11.5, color: "var(--muted)" }}>{new Date(o.at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}</div></div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: o.in ? "var(--ok)" : "var(--danger)" }} className="tabular">{o.in ? "+" : "−"}{fmt(o.amount)}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* CLOSE MODAL */}
      {modal && (
        <div onClick={() => { if (busy) return; if (closed) newShift(); else setModal(false); }} style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ width: 440, background: "var(--card)", borderRadius: 20, padding: 26 }}>
            {!closed ? (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
                  <div style={{ fontSize: 21, fontWeight: 700 }}>{t("shift.closeTitle")}</div>
                  <button onClick={() => setModal(false)} style={{ width: 34, height: 34, border: "none", background: "var(--surface)", borderRadius: 9, cursor: "pointer" }}>✕</button>
                </div>
                <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 18, lineHeight: 1.5 }}>{t("shift.closeHint")}</div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 16px", borderRadius: 12, background: "var(--surface-accent)", marginBottom: 12 }}><span style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text3)" }}>{t("shift.expectedCash")}</span><span style={{ fontSize: 20, fontWeight: 800 }} className="tabular">{fmt(sum?.expected || 0)}</span></div>
                <label style={{ display: "block", fontSize: 12.5, color: "var(--text3)", fontWeight: 600, marginBottom: 6 }}>{t("shift.countedCash")}</label>
                <input value={counted} onChange={(e) => setCounted(e.target.value.replace(/\D/g, ""))} placeholder="0" style={{ ...inputStyle, height: 52, fontSize: 22, fontWeight: 700, marginBottom: 14 }} />
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 16px", borderRadius: 12, background: !hasCount ? "var(--surface)" : diff === 0 ? "var(--ok-soft)" : diff > 0 ? "var(--ok-soft)" : "var(--danger-soft)", marginBottom: 22 }}>
                  <span style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text3)" }}>{!hasCount ? t("shift.diff") : diff === 0 ? t("shift.correct") : diff > 0 ? t("shift.surplus") : t("shift.shortage")}</span>
                  <span style={{ fontSize: 20, fontWeight: 800, color: !hasCount ? "var(--muted)" : diff < 0 ? "var(--danger)" : "var(--ok)" }} className="tabular">{!hasCount ? "—" : (diff > 0 ? "+" : diff < 0 ? "−" : "") + fmt(Math.abs(diff))}</span>
                </div>
                <button onClick={confirmClose} disabled={busy} className="btn" style={{ width: "100%", height: 54, background: "var(--danger)", color: "#fff", fontSize: 15.5 }}>{`🔒 ${t("shift.closeZ")}`}</button>
              </>
            ) : (
              <div style={{ textAlign: "center", padding: "8px 4px" }}>
                <div style={{ width: 80, height: 80, margin: "0 auto 16px", borderRadius: "50%", background: "var(--ok-soft)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 42 }}>✅</div>
                <div style={{ fontSize: 21, fontWeight: 700 }}>{t("shift.shiftClosed")}</div>
                <div style={{ fontSize: 13.5, color: "var(--muted)", marginTop: 5 }}>{t("shift.zReady")}</div>
                <div style={{ textAlign: "left", marginTop: 20, border: "1px solid var(--border)", borderRadius: 14, overflow: "hidden" }}>
                  <Row l={t("sales.shiftSales")} v={fmt(sum?.total_sales || 0)} />
                  <Row l={t("shift.expectedCash")} v={fmt(closed.expected)} />
                  <Row l={t("shift.countedShort")} v={fmt(closed.counted)} />
                  <Row l={t("shift.diff")} v={(closed.diff > 0 ? "+" : closed.diff < 0 ? "−" : "") + fmt(Math.abs(closed.diff))} c={closed.diff === 0 ? "var(--ok)" : closed.diff < 0 ? "var(--danger)" : "var(--ok)"} last />
                </div>
                <button className="btn btn-primary" style={{ width: "100%", height: 50, marginTop: 20 }} onClick={newShift}>{`▶ ${t("shift.newShift")}`}</button>
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}

function Row({ l, v, c, last }: { l: string; v: string; c?: string; last?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "13px 16px", fontSize: 13, borderBottom: last ? "none" : "1px solid var(--surface)" }}>
      <span style={{ color: "var(--muted)" }}>{l}</span><span style={{ fontWeight: 700, color: c || "var(--ink)" }} className="tabular">{v}</span>
    </div>
  );
}
