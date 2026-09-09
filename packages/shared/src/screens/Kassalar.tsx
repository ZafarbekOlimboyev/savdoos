// Kassalar (fizik naqd yashiklari) — YANGI savdogar uchun sozlash ekrani.
//
// MUHIM: bu ekran MIGRATION tushunchalarini KO'RSATMAYDI. Savdogar T0/cutover, backfill,
// historical_till_unknown, shadow comparison yoki migration hash'larini KO'RMAYDI — ular
// operator/ichki vositalar uchun. Bu yerda faqat bitta savol bor:
//     "Bu filialda BUGUN nechta REAL fizik kassa (yashik) bor?"
//
// Kassa soni TAXMIN QILINMAYDI (terminal, kassir, tarix yoki "bitta kassa" fallback'idan EMAS) —
// javobni faqat savdogar biladi. Soxta/placeholder kassa YARATILMAYDI.
import { useEffect, useState } from "react";
import { Topbar, inputStyle, td, th } from "@/components/ui";
import { del, get, patch, post } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { Till } from "@/lib/tills";

interface BranchState {
  branch_id: string;
  code: string;
  name: string;
  active_tills: number;
  active_safes: number;
  state: string;
  can_open_cash_shift: boolean;
  collection_available: boolean;
}
interface SetupState {
  state: string;
  ledger_native: boolean;
  cash_setup_complete: boolean;
  branches: BranchState[];
  question: string;
}

const card: React.CSSProperties = {
  background: "var(--surface)", border: "1px solid var(--border-soft)", borderRadius: 14,
  padding: 18, marginBottom: 16,
};

export function Kassalar() {
  const t = useT();
  const [setup, setSetup] = useState<SetupState | null>(null);
  const [tills, setTills] = useState<Record<string, Till[]>>({});
  const [safes, setSafes] = useState<Record<string, Till[]>>({});
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [newCode, setNewCode] = useState<Record<string, string>>({});

  async function load() {
    setErr("");
    try {
      const s = await get<SetupState>("/cash-setup");
      setSetup(s);
      const tl: Record<string, Till[]> = {};
      const sf: Record<string, Till[]> = {};
      for (const b of s.branches) {
        tl[b.branch_id] = await get<Till[]>(`/tills?branch_id=${b.branch_id}`);
        sf[b.branch_id] = await get<Till[]>(`/safes?branch_id=${b.branch_id}&active_only=false`);
      }
      setTills(tl); setSafes(sf);
    } catch (e: any) {
      setSetup(null);
      setErr(e?.message || t("kassa.loadErr"));
    }
  }
  useEffect(() => { void load(); }, []);

  async function addTill(branchId: string) {
    const code = (newCode[branchId] || "").trim();
    if (!code) { setErr(t("kassa.codeRequired")); return; }
    setBusy(true); setErr("");
    try {
      await post("/tills", { branch_id: branchId, code });
      setNewCode((s) => ({ ...s, [branchId]: "" }));
      await load();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function toggle(till: Till) {
    setBusy(true); setErr("");
    // Arxivlash = kassani ishlatishdan chiqarish. OCHIQ smenasi bor kassa arxivlanmaydi —
    // server 409 qaytaradi va sababni ko'rsatamiz (jimgina bo'sh qolmaydi).
    try { await patch(`/tills/${till.id}`, { active: !till.active }); await load(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function removeTill(till: Till) {
    setBusy(true); setErr("");
    // Faqat HECH QACHON ishlatilmagan kassa o'chiriladi (xato yaratilgan). Ishlatilgani —
    // audit izi uchun saqlanadi, uni arxivlash kerak.
    try { await del(`/tills/${till.id}`); await load(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function addSafe(branchId: string) {
    setBusy(true); setErr("");
    try { await post("/safes", { branch_id: branchId }); await load(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  if (!setup) {
    return (
      <main className="main">
        <Topbar title={t("kassa.title")} sub={t("kassa.sub")} />
        <div className="scroll" style={{ flex: 1, padding: 24 }}>
          <div style={card}>{err || "…"}</div>
        </div>
      </main>
    );
  }

  return (
    <main className="main">
      <Topbar title={t("kassa.title")} sub={t("kassa.sub")} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {/* Sozlash tugallanmagan bo'lsa — ANIQ savol, TAXMIN emas */}
        {!setup.cash_setup_complete && (
          <div data-testid="cash-setup-banner"
               style={{ ...card, borderColor: "var(--warn)", background: "var(--warn-soft, transparent)" }}>
            <div style={{ fontWeight: 700, marginBottom: 6 }}>{t("kassa.setupTitle")}</div>
            <div style={{ fontSize: 13.5, color: "var(--text3)" }}>{setup.question}</div>
          </div>
        )}
        {err && <div style={{ ...card, borderColor: "var(--red)", color: "var(--red)" }}>{err}</div>}

        {setup.branches.map((b) => {
          const bt = (tills[b.branch_id] || []);
          const bs = (safes[b.branch_id] || []);
          return (
            <div key={b.branch_id} style={card} data-testid={`branch-${b.code}`}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <div>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>{b.name} <span style={{ color: "var(--muted)", fontWeight: 500 }}>({b.code})</span></div>
                  <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>
                    {t("kassa.activeCount", { n: b.active_tills })}
                    {b.can_open_cash_shift ? "" : ` · ${t("kassa.cannotOpen")}`}
                  </div>
                </div>
              </div>

              {bt.length > 0 && (
                <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 12 }}>
                  <thead><tr>
                    <th style={th}>{t("kassa.code")}</th>
                    <th style={th}>{t("kassa.currency")}</th>
                    <th style={th}>{t("kassa.status")}</th>
                    <th style={th} />
                  </tr></thead>
                  <tbody>
                    {bt.map((x) => (
                      <tr key={x.id} data-testid={`till-${x.code}`}>
                        <td style={td}><b>{x.code}</b></td>
                        <td style={td}>{x.currency}</td>
                        <td style={{ ...td, color: x.active ? "var(--ok)" : "var(--muted)" }}>
                          {x.active ? t("kassa.active") : t("kassa.archived")}
                        </td>
                        <td style={{ ...td, textAlign: "right" }}>
                          <button className="btn" disabled={busy} onClick={() => toggle(x)}>
                            {x.active ? t("kassa.archive") : t("kassa.reactivate")}
                          </button>
                          {!x.active && (
                            <button className="btn" style={{ marginLeft: 8 }} disabled={busy}
                                    onClick={() => removeTill(x)}>{t("kassa.delete")}</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input data-testid={`new-till-${b.code}`} value={newCode[b.branch_id] || ""}
                       onChange={(e) => setNewCode((s) => ({ ...s, [b.branch_id]: e.target.value }))}
                       placeholder={t("kassa.codePlaceholder")}
                       style={{ ...inputStyle, height: 40, maxWidth: 220 }} />
                <button className="btn btn-primary" disabled={busy}
                        onClick={() => addTill(b.branch_id)}>{t("kassa.add")}</button>
              </div>

              {/* SAFE — IXTIYORIY. Avtomatik YARATILMAYDI; savdogar o'zi qaror qiladi. */}
              <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--border-soft)" }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 4 }}>{t("kassa.safeQ")}</div>
                <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 8 }}>{t("kassa.safeHint")}</div>
                {bs.length === 0 ? (
                  <button className="btn" data-testid={`add-safe-${b.code}`} disabled={busy}
                          onClick={() => addSafe(b.branch_id)}>{t("kassa.safeAdd")}</button>
                ) : (
                  <div style={{ fontSize: 13.5 }} data-testid={`safe-${b.code}`}>
                    {t("kassa.safeReady")} · {bs.map((x) => x.code || "SAFE").join(", ")}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </main>
  );
}
