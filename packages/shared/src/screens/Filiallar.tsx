import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Buildings, ChartLineUp, CreditCard, CrownSimple, Lightbulb, ListBullets, PencilSimple,
  LockKey, MapPin, Medal, Money, Package, Plus, SquaresFour, TrendDown, TrendUp, UsersThree,
} from "@phosphor-icons/react";
import { fmt, fmtShort } from "@/lib/format";
import { Topbar, Modal, useGet, inputStyle } from "@/components/ui";
import { post, del, patch } from "@/lib/api";
import { useT } from "@/lib/i18n";

type T = (k: string, vars?: Record<string, string | number>) => string;
interface Branch { id: string; name: string; address: string | null; phone: string | null; timezone?: string | null; cashiers: number; sales_today: number; is_active: boolean; visible?: boolean }

// Backend _TZ_OFFSETS bilan mos ro'yxat (QA SB-004: timezone endi tanlanadi/tahrirlanadi)
const TZ_LIST = ["Asia/Tashkent", "Asia/Bishkek", "Asia/Almaty", "Asia/Samarkand", "Asia/Dushanbe",
  "Asia/Ashgabat", "Asia/Qyzylorda", "Asia/Yekaterinburg", "Asia/Novosibirsk", "Europe/Moscow",
  "Asia/Baku", "Asia/Tbilisi", "Asia/Yerevan"];
interface BranchesResp { branches: Branch[]; plan: string; max_branches: number; count: number; can_add: boolean }

type Pays = { cash: number; card: number; qr: number; credit: number };
interface SeriesPoint { label: string; subtotal: number; discount: number; returns: number; sales: number; cost: number; profit: number; tx: number; pays: Pays }
interface Overview {
  kpi: { sales: number; profit: number; tx: number; avg_check: number };
  delta: { sales: number | null; profit: number | null; tx: number | null; avg: number | null };
  series: SeriesPoint[];
  payments: { method: string; amount: number }[];
  credit_total: number;
  top_products: { name: string; revenue: number; qty: number }[];
  cashiers: { name: string; sales: number; tx: number; avg: number }[];
  vat_on: boolean; vat_rate: number;
}
type Period = "day" | "week" | "month";
const VIEW_KEY = "savdoos_filiallar_view";
const METHOD_COLOR: Record<string, string> = { cash: "#2ec77e", card: "#8b7ff0", qr: "#2bc4c4", credit: "var(--warn)" };

export function Filiallar() {
  const t = useT();
  const { data, reload } = useGet<BranchesResp>("/branches");
  const [view, setView] = useState<"list" | "card">(() => { try { return localStorage.getItem(VIEW_KEY) === "card" ? "card" : "list"; } catch { return "list"; } });
  const [selected, setSelected] = useState<Branch | null>(null);
  const [limitOpen, setLimitOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [editB, setEditB] = useState<Branch | null>(null);

  const setViewMode = (v: "list" | "card") => { setView(v); try { localStorage.setItem(VIEW_KEY, v); } catch { /* ignore */ } };

  if (selected) return <BranchDetail branch={selected} onBack={() => setSelected(null)} t={t} />;

  const branches = data?.branches || [];
  const total = branches.length;
  const totalCashiers = branches.reduce((s, b) => s + b.cashiers, 0);
  const totalSales = branches.reduce((s, b) => s + b.sales_today, 0);
  const canAdd = data?.can_add ?? false;

  const stats = [
    { icon: <Buildings size={21} />, bg: "var(--accent-soft)", fg: "var(--accent-strong)", value: total, label: t("filiallar.totalBranches") },
    { icon: <UsersThree size={21} />, bg: "var(--ok-soft)", fg: "var(--ok)", value: totalCashiers, label: t("filiallar.totalCashiers") },
    { icon: <ChartLineUp size={21} />, bg: "var(--surface-accent)", fg: "var(--accent-strong)", value: fmt(totalSales), label: t("filiallar.todaySales") },
  ];

  const onAdd = () => { if (canAdd) setAddOpen(true); else setLimitOpen(true); };

  return (
    <main className="main">
      <Topbar
        title={t("nav.filiallar")}
        sub={`${t("filiallar.sub")} · ${t("filiallar.activeCount", { n: total })}`}
        right={
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <ViewToggle view={view} onChange={setViewMode} t={t} />
            <button className="btn btn-primary" style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 20px" }} onClick={onAdd}>
              <Plus size={16} weight="bold" />{t("filiallar.newBranch")}
            </button>
          </div>
        }
      />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16, marginBottom: 20 }}>
          {stats.map((s) => (
            <div key={s.label} className="card" style={{ padding: "15px 18px", display: "flex", alignItems: "center", gap: 14 }}>
              <div style={{ width: 42, height: 42, flex: "none", borderRadius: 11, background: s.bg, color: s.fg, display: "flex", alignItems: "center", justifyContent: "center" }}>{s.icon}</div>
              <div><div className="tabular" style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1 }}>{s.value}</div><div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4 }}>{s.label}</div></div>
            </div>
          ))}
        </div>
        {branches.length === 0
          ? <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>—</div>
          : view === "list" ? <ListView branches={branches} t={t} onSelect={setSelected} onEdit={setEditB} /> : <CardView branches={branches} t={t} onSelect={setSelected} onEdit={setEditB} />}
      </div>

      {limitOpen && <TarifModal plan={data?.plan || "start"} onClose={() => setLimitOpen(false)} t={t} />}
      {addOpen && <AddBranchModal onClose={() => setAddOpen(false)} onSaved={() => { setAddOpen(false); reload(); }} t={t} />}
      {editB && <EditBranchModal branch={editB} onClose={() => setEditB(null)} onSaved={() => { setEditB(null); reload(); }} t={t} />}
    </main>
  );
}

function ViewToggle({ view, onChange, t }: { view: "list" | "card"; onChange: (v: "list" | "card") => void; t: T }) {
  const btn = (mode: "list" | "card", Icon: typeof ListBullets, label: string) => {
    const on = view === mode;
    return <button title={label} aria-label={label} onClick={() => onChange(mode)} style={{ width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", border: "none", borderRadius: 9, cursor: "pointer", background: on ? "var(--card)" : "transparent", color: on ? "var(--accent-strong)" : "var(--muted)", boxShadow: on ? "0 1px 3px rgba(0,0,0,0.12)" : "none" }}><Icon size={19} weight={on ? "fill" : "regular"} /></button>;
  };
  return <div style={{ display: "flex", gap: 3, padding: 3, borderRadius: 12, background: "var(--surface)", border: "1px solid var(--border)" }}>{btn("list", ListBullets, t("filiallar.viewList"))}{btn("card", SquaresFour, t("filiallar.viewCard"))}</div>;
}

function StatusPill({ t, active }: { t: T; active: boolean }) {
  const c = active ? "var(--ok)" : "var(--faint)";
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 600, color: c }}><span style={{ width: 8, height: 8, borderRadius: "50%", background: c }} />{active ? t("filiallar.active") : "—"}</span>;
}

function ListView({ branches, t, onSelect, onEdit }: { branches: Branch[]; t: T; onSelect: (b: Branch) => void; onEdit: (b: Branch) => void }) {
  const cell: React.CSSProperties = { padding: "14px 12px", fontSize: 13.5, borderTop: "1px solid var(--border-soft)" };
  const head: React.CSSProperties = { padding: "14px 12px", fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", textAlign: "left" };
  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr style={{ background: "var(--card-alt)" }}>
          <th style={{ ...head, paddingLeft: 22 }}>{t("filiallar.colBranch")}</th><th style={head}>{t("filiallar.colAddress")}</th>
          <th style={{ ...head, textAlign: "right" }}>{t("filiallar.colCashiers")}</th><th style={{ ...head, textAlign: "right" }}>{t("filiallar.colSales")}</th>
          <th style={{ ...head, paddingRight: 22 }}>{t("filiallar.colStatus")}</th>
        </tr></thead>
        <tbody>
          {branches.map((b) => (
            <tr key={b.id} className={b.visible === false ? undefined : "click-row"} onClick={() => b.visible !== false && onSelect(b)} style={b.visible === false ? { opacity: 0.65 } : undefined}>
              <td style={{ ...cell, paddingLeft: 22 }}><div style={{ display: "flex", alignItems: "center", gap: 12 }}><div style={{ width: 36, height: 36, flex: "none", borderRadius: 10, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15, fontWeight: 700 }}>{b.name.charAt(0)}</div><span style={{ fontWeight: 600 }}>{b.name}</span></div></td>
              <td style={{ ...cell, color: "var(--text3)" }}>{b.address || "—"}</td>
              <td className="tabular" style={{ ...cell, textAlign: "right", color: "var(--text3)" }}>{b.visible === false ? "—" : t("filiallar.cashiersN", { n: b.cashiers })}</td>
              <td className="tabular" style={{ ...cell, textAlign: "right", fontWeight: 700 }}>{b.visible === false ? "—" : fmt(b.sales_today)}</td>
              <td style={{ ...cell, paddingRight: 22 }}><div style={{ display: "flex", alignItems: "center", gap: 10 }}><StatusPill t={t} active={b.is_active} /><button title={t("filiallar.editBranch")} onClick={(e) => { e.stopPropagation(); onEdit(b); }} style={{ border: "1px solid var(--border)", background: "var(--card)", borderRadius: 8, width: 30, height: 30, display: "inline-flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: "var(--text3)" }}><PencilSimple size={15} /></button></div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CardView({ branches, t, onSelect, onEdit }: { branches: Branch[]; t: T; onSelect: (b: Branch) => void; onEdit: (b: Branch) => void }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 16 }}>
      {branches.map((b) => (
        <div key={b.id} className={b.visible === false ? "card" : "card click-card"} onClick={() => b.visible !== false && onSelect(b)} style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14, opacity: b.visible === false ? 0.65 : 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 13 }}>
            <div style={{ width: 46, height: 46, flex: "none", borderRadius: 12, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 19, fontWeight: 700 }}>{b.name.charAt(0)}</div>
            <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em" }}>{b.name}</div><div style={{ marginTop: 4 }}><StatusPill t={t} active={b.is_active} /></div></div>
            <button title={t("filiallar.editBranch")} onClick={(e) => { e.stopPropagation(); onEdit(b); }} style={{ border: "1px solid var(--border)", background: "var(--card)", borderRadius: 9, width: 34, height: 34, flex: "none", display: "inline-flex", alignItems: "center", justifyContent: "center", cursor: "pointer", color: "var(--text3)" }}><PencilSimple size={16} /></button>
          </div>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, color: "var(--text3)", lineHeight: 1.4 }}><MapPin size={16} style={{ flex: "none", marginTop: 1, color: "var(--muted)" }} /><span>{b.address || "—"}</span></div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, borderTop: "1px solid var(--border-soft)", paddingTop: 14 }}>
            <div><div style={{ fontSize: 11.5, color: "var(--muted)", fontWeight: 500 }}>{t("filiallar.colCashiers")}</div><div className="tabular" style={{ fontSize: 15, fontWeight: 700, marginTop: 3 }}>{b.visible === false ? "—" : t("filiallar.cashiersN", { n: b.cashiers })}</div></div>
            <div><div style={{ fontSize: 11.5, color: "var(--muted)", fontWeight: 500 }}>{t("filiallar.colSales")}</div><div className="tabular" style={{ fontSize: 15, fontWeight: 800, marginTop: 3, color: "var(--accent-strong)" }}>{b.visible === false ? "—" : fmt(b.sales_today)}</div></div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TarifModal({ plan, onClose, t }: { plan: string; onClose: () => void; t: T }) {
  const nav = useNavigate();
  return (
    <Modal onClose={onClose} width={432}>
      <div style={{ textAlign: "center", padding: "4px 2px 2px" }}>
        <div style={{ width: 60, height: 60, margin: "0 auto 16px", borderRadius: 15, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center" }}><LockKey size={30} weight="fill" /></div>
        <div style={{ fontSize: 19, fontWeight: 800, letterSpacing: "-0.02em" }}>{t("filiallar.limitTitle")}</div>
        <div style={{ fontSize: 14, color: "var(--text3)", marginTop: 10, lineHeight: 1.6 }}>{t("filiallar.limitBody", { plan })}</div>
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
        <button onClick={onClose} style={{ flex: 1, height: 50, border: "1px solid var(--border-input)", background: "var(--card)", borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14, fontWeight: 600, color: "var(--text3)" }}>{t("common.cancel")}</button>
        <button onClick={() => { onClose(); nav("/sozlamalar"); }} style={{ flex: 1.4, height: 50, border: "none", background: "var(--accent)", borderRadius: 12, cursor: "pointer", font: "inherit", fontSize: 14, fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}><CrownSimple size={17} weight="fill" />{t("filiallar.seePlans")}</button>
      </div>
    </Modal>
  );
}

function AddBranchModal({ onClose, onSaved, t }: { onClose: () => void; onSaved: () => void; t: T }) {
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [tz, setTz] = useState("Asia/Tashkent");
  const save = async () => {
    if (!name.trim()) { setErr(t("filiallar.fNameReq")); return; }
    setBusy(true); setErr("");
    try { await post("/branches", { name, address, phone, timezone: tz }); onSaved(); }
    catch (e: any) {
      const m = String(e?.message || "");
      setErr(m.includes("tarif_limit") ? t("filiallar.limitTitle") : m || "?");
    } finally { setBusy(false); }
  };
  return (
    <Modal onClose={onClose} width={440}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 4 }}>{t("filiallar.newBranch")}</div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 18 }}>{t("filiallar.sub")}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{t("filiallar.fName")}<input value={name} onChange={(e) => setName(e.target.value)} style={{ ...inputStyle, marginTop: 6 }} autoFocus /></label>
        <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{t("filiallar.fAddress")}<input value={address} onChange={(e) => setAddress(e.target.value)} style={{ ...inputStyle, marginTop: 6 }} /></label>
        <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{t("filiallar.fPhone")}<input value={phone} onChange={(e) => setPhone(e.target.value)} style={{ ...inputStyle, marginTop: 6 }} /></label>
        <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{t("filiallar.fTimezone")}
          <select value={tz} onChange={(e) => setTz(e.target.value)} style={{ ...inputStyle, marginTop: 6 }}>
            {TZ_LIST.map((z) => <option key={z} value={z}>{z}</option>)}
          </select></label>
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy || !name.trim()} onClick={save}>{busy ? "..." : t("common.save")}</button>
      </div>
    </Modal>
  );
}

function EditBranchModal({ branch, onClose, onSaved, t }: { branch: Branch; onClose: () => void; onSaved: () => void; t: T }) {
  const [name, setName] = useState(branch.name);
  const [address, setAddress] = useState(branch.address || "");
  const [phone, setPhone] = useState(branch.phone || "");
  const [tz, setTz] = useState(branch.timezone || "Asia/Tashkent");
  const [active, setActive] = useState(branch.is_active);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    if (!name.trim()) { setErr(t("filiallar.fNameReq")); return; }
    setBusy(true); setErr("");
    try {
      await patch("/branches/" + branch.id, { name, address, phone, timezone: tz, is_active: active });
      onSaved();
    } catch (e: any) { setErr(e?.message || "?"); } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!window.confirm(t("filiallar.deleteConfirm"))) return;
    setBusy(true); setErr("");
    try { await del("/branches/" + branch.id); onSaved(); }
    catch (e: any) { setErr(e?.message || "?"); } finally { setBusy(false); }
  };
  return (
    <Modal onClose={onClose} width={440}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 14 }}>{t("filiallar.editBranch")}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{t("filiallar.fName")}<input value={name} onChange={(e) => setName(e.target.value)} style={{ ...inputStyle, marginTop: 6 }} autoFocus /></label>
        <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{t("filiallar.fAddress")}<input value={address} onChange={(e) => setAddress(e.target.value)} style={{ ...inputStyle, marginTop: 6 }} /></label>
        <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{t("filiallar.fPhone")}<input value={phone} onChange={(e) => setPhone(e.target.value)} style={{ ...inputStyle, marginTop: 6 }} /></label>
        <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{t("filiallar.fTimezone")}
          <select value={tz} onChange={(e) => setTz(e.target.value)} style={{ ...inputStyle, marginTop: 6 }}>
            {TZ_LIST.map((z) => <option key={z} value={z}>{z}</option>)}
          </select></label>
        <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 14, fontWeight: 500 }}>
          <span>{t("filiallar.activeLabel")}</span>
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} style={{ width: 18, height: 18 }} />
        </label>
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
        <button className="btn btn-ghost" style={{ flex: 1, color: "var(--red)" }} disabled={busy} onClick={remove}>{t("filiallar.deleteBranch")}</button>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy || !name.trim()} onClick={save}>{busy ? "..." : t("common.save")}</button>
      </div>
    </Modal>
  );
}

/* ─────────────────────  ANALITIKA (REAL, per-filial)  ───────────────────── */

function BranchDetail({ branch, onBack, t }: { branch: Branch; onBack: () => void; t: T }) {
  const [period, setPeriod] = useState<Period>("month");
  const { data: ov } = useGet<Overview>(`/reports/overview?period=${period}&branch_id=${branch.id}`);

  const tot = useMemo(() => {
    const s = ov?.series || [];
    const sum = (f: (p: SeriesPoint) => number) => s.reduce((a, p) => a + f(p), 0);
    return { subtotal: sum((p) => p.subtotal), discount: sum((p) => p.discount), returns: sum((p) => p.returns), cost: sum((p) => p.cost) };
  }, [ov]);

  const kpi = ov?.kpi;
  const margin = kpi && kpi.sales ? (kpi.profit / kpi.sales) * 100 : 0;

  return (
    <main className="main">
      <div className="topbar">
        <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
          <button onClick={onBack} aria-label={t("branch.back")} title={t("branch.back")} style={{ width: 42, height: 42, flex: "none", display: "flex", alignItems: "center", justifyContent: "center", border: "1px solid var(--border)", borderRadius: 11, background: "var(--card)", color: "var(--text2)", cursor: "pointer" }}><ArrowLeft size={19} weight="bold" /></button>
          <div style={{ width: 44, height: 44, flex: "none", borderRadius: 12, background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 19, fontWeight: 700 }}>{branch.name.charAt(0)}</div>
          <div style={{ minWidth: 0 }}>
            <div className="h1" style={{ display: "flex", alignItems: "center", gap: 10 }}>{branch.name}<StatusPill t={t} active={branch.is_active} /></div>
            <div className="sub" style={{ display: "flex", alignItems: "center", gap: 6 }}><MapPin size={13} />{branch.address || "—"}</div>
          </div>
        </div>
        <PeriodSelector value={period} onChange={setPeriod} t={t} />
      </div>

      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14, marginBottom: 18 }}>
          <Kpi label={t("branch.kpi.revenue")} value={kpi ? fmt(kpi.sales) : "—"} growth={ov?.delta.sales} t={t} />
          <Kpi label={t("dash.grossProfit")} value={kpi ? fmt(kpi.profit) : "—"} color="var(--ok)" growth={ov?.delta.profit} t={t} />
          <Kpi label={t("branch.kpi.margin")} value={kpi ? `${margin.toFixed(1)}%` : "—"} color={margin < 10 ? "var(--warn)" : "var(--text)"} />
          <Kpi label={t("branch.kpi.avgCheck")} value={kpi ? fmt(kpi.avg_check) : "—"} />
          <Kpi label={t("branch.kpi.receipts")} value={kpi ? kpi.tx.toLocaleString("ru-RU") : "—"} />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.05fr 1fr", gap: 16, marginBottom: 16, alignItems: "start" }}>
          <PnLCard tot={tot} profit={kpi?.profit || 0} margin={margin} t={t} />
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <TrendCard series={ov?.series} t={t} />
            <InsightsCard ov={ov} t={t} />
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16 }}>
          <PayCard ov={ov} t={t} />
          <TopProductsCard ov={ov} t={t} />
          <CashiersCard ov={ov} t={t} />
        </div>
      </div>
    </main>
  );
}

function PeriodSelector({ value, onChange, t }: { value: Period; onChange: (p: Period) => void; t: T }) {
  const opts: [Period, string][] = [["day", t("branch.period.today")], ["week", t("branch.period.week")], ["month", t("branch.period.month")]];
  return <div style={{ display: "flex", gap: 3, padding: 3, borderRadius: 11, background: "var(--surface)", border: "1px solid var(--border)" }}>{opts.map(([k, lab]) => { const on = value === k; return <button key={k} onClick={() => onChange(k)} style={{ padding: "8px 16px", border: "none", borderRadius: 8, cursor: "pointer", font: "inherit", fontSize: 13, fontWeight: 600, background: on ? "var(--card)" : "transparent", color: on ? "var(--accent-strong)" : "var(--muted)", boxShadow: on ? "0 1px 3px rgba(0,0,0,0.12)" : "none" }}>{lab}</button>; })}</div>;
}

function Kpi({ label, value, color, growth, t }: { label: string; value: string; color?: string; growth?: number | null; t?: T }) {
  return (
    <div className="card" style={{ padding: "15px 17px" }}>
      <div style={{ fontSize: 12.5, color: "var(--muted)", fontWeight: 500 }}>{label}</div>
      <div className="tabular" style={{ fontSize: 21, fontWeight: 800, letterSpacing: "-0.02em", marginTop: 7, color: color || "var(--text)" }}>{value}</div>
      {growth !== undefined && t && (growth === null
        ? <div style={{ marginTop: 6, fontSize: 12, fontWeight: 600, color: "var(--faint)" }}>{t("dash.newBadge")}</div>
        : <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 6, fontSize: 12, fontWeight: 600, color: growth >= 0 ? "var(--ok)" : "var(--danger)" }}>{growth >= 0 ? <TrendUp size={13} weight="bold" /> : <TrendDown size={13} weight="bold" />}{Math.abs(growth).toFixed(1)}% <span style={{ color: "var(--faint)", fontWeight: 500 }}>{t("branch.vsPrev")}</span></div>)}
    </div>
  );
}

function CardBox({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return <div className="card" style={{ padding: 18 }}><div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 15, fontSize: 14, fontWeight: 700, color: "var(--text2)" }}><span style={{ color: "var(--accent-strong)", display: "flex" }}>{icon}</span>{title}</div>{children}</div>;
}

function PnLCard({ tot, profit, margin, t }: { tot: { subtotal: number; discount: number; returns: number; cost: number }; profit: number; margin: number; t: T }) {
  const netRev = tot.subtotal - tot.discount - tot.returns;
  const row = (label: string, value: number, kind: "in" | "out" | "sub" | "net") => {
    const color = kind === "out" ? "var(--danger)" : kind === "net" ? "var(--ok)" : "var(--text)";
    const strong = kind === "sub" || kind === "net";
    return (
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: kind === "net" ? "13px 0 2px" : "9px 0", borderTop: strong ? "1px solid var(--border)" : "none" }}>
        <span style={{ fontSize: kind === "net" ? 14.5 : 13.5, color: kind === "out" ? "var(--text3)" : "var(--text2)", fontWeight: strong ? 700 : 500 }}>{label}</span>
        <span className="tabular" style={{ fontSize: kind === "net" ? 18 : 14, fontWeight: strong ? 800 : 600, color }}>{kind === "out" ? "−" : ""}{fmt(value)}</span>
      </div>
    );
  };
  return (
    <CardBox title={t("branch.pnl.title")} icon={<Money size={17} weight="fill" />}>
      {row(t("branch.pnl.grossRevenue"), tot.subtotal, "in")}
      {tot.discount ? row(t("branch.pnl.discounts"), tot.discount, "out") : null}
      {tot.returns ? row(t("branch.pnl.returns"), tot.returns, "out") : null}
      {row(t("dash.finNetRev"), netRev, "sub")}
      {row(t("branch.pnl.cogs"), tot.cost, "out")}
      {row(t("dash.grossProfit"), profit, "net")}
      <div style={{ marginTop: 12, padding: "10px 14px", borderRadius: 11, background: "var(--ok-soft)", color: "var(--ok)", fontSize: 12.5, fontWeight: 700, display: "flex", justifyContent: "space-between" }}><span>{t("branch.kpi.margin")}</span><span className="tabular">{margin.toFixed(1)}%</span></div>
    </CardBox>
  );
}

function TrendCard({ series, t }: { series?: SeriesPoint[]; t: T }) {
  const pts = series || [];
  const max = Math.max(1, ...pts.map((p) => p.sales));
  return (
    <CardBox title={t("branch.trend")} icon={<ChartLineUp size={17} weight="fill" />}>
      {pts.length === 0 ? <div style={{ color: "var(--muted)", fontSize: 13 }}>—</div> : (
        <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 96 }}>
          {pts.map((p, i) => (
            <div key={i} title={fmt(p.sales)} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
              <div style={{ width: "100%", height: `${Math.round((p.sales / max) * 78)}px`, background: i === pts.length - 1 ? "var(--accent)" : "var(--accent-soft)", borderRadius: 6, minHeight: 4 }} />
              <span style={{ fontSize: 10, color: "var(--faint)", fontWeight: 600 }}>{fmtShort(p.sales)}</span>
            </div>
          ))}
        </div>
      )}
    </CardBox>
  );
}

function PayCard({ ov, t }: { ov?: Overview | null; t: T }) {
  // Qaytarishlar netlanganda summa manfiy bo'lishi mumkin — progress-bar buzilmasin (0 deb olamiz)
  const rows = [...(ov?.payments || [])].map((p) => ({ ...p, amount: Math.max(0, p.amount) }));
  if (ov?.credit_total) rows.push({ method: "credit", amount: Math.max(0, ov.credit_total) });
  const totp = Math.max(1, rows.reduce((a, p) => a + p.amount, 0));
  return (
    <CardBox title={t("branch.payMethods")} icon={<CreditCard size={17} weight="fill" />}>
      <div style={{ display: "flex", height: 10, borderRadius: 6, overflow: "hidden", marginBottom: 14 }}>{rows.map((p) => <div key={p.method} style={{ width: `${(p.amount / totp) * 100}%`, background: METHOD_COLOR[p.method] }} />)}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
        {rows.map((p) => (
          <div key={p.method} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 13 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text3)" }}><span style={{ width: 9, height: 9, borderRadius: 3, background: METHOD_COLOR[p.method] }} />{p.method === "credit" ? t("dash.creditUnpaid") : t("branch.pay." + p.method)}</span>
            <span className="tabular" style={{ fontWeight: 600 }}>{fmt(p.amount)} <span style={{ color: "var(--faint)", fontWeight: 500 }}>· {Math.round((p.amount / totp) * 100)}%</span></span>
          </div>
        ))}
        {rows.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>—</div>}
      </div>
    </CardBox>
  );
}

function TopProductsCard({ ov, t }: { ov?: Overview | null; t: T }) {
  const tp = ov?.top_products || [];
  const max = Math.max(1, ...tp.map((p) => p.revenue));
  return (
    <CardBox title={t("branch.topProducts")} icon={<Package size={17} weight="fill" />}>
      <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
        {tp.map((p, i) => (
          <div key={p.name}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 5 }}><span style={{ fontWeight: 600, color: "var(--text2)" }}><span style={{ color: "var(--faint)", marginRight: 7 }}>{i + 1}</span>{p.name}</span><span className="tabular" style={{ fontWeight: 700 }}>{fmt(p.revenue)}</span></div>
            <div style={{ height: 6, borderRadius: 3, background: "var(--border)", overflow: "hidden" }}><div style={{ height: "100%", width: `${Math.round((p.revenue / max) * 100)}%`, background: "var(--accent)", borderRadius: 3 }} /></div>
          </div>
        ))}
        {tp.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>—</div>}
      </div>
    </CardBox>
  );
}

function CashiersCard({ ov, t }: { ov?: Overview | null; t: T }) {
  const cs = ov?.cashiers || [];
  const max = Math.max(1, ...cs.map((c) => c.sales));
  return (
    <CardBox title={t("branch.cashiers")} icon={<UsersThree size={17} weight="fill" />}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {cs.map((c, i) => (
          <div key={c.name + i} style={{ display: "flex", alignItems: "center", gap: 11 }}>
            <div style={{ width: 32, height: 32, flex: "none", borderRadius: "50%", background: i === 0 ? "var(--accent)" : "var(--accent-soft)", color: i === 0 ? "#fff" : "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700 }}>{c.name.charAt(0)}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}><span style={{ fontWeight: 600 }}>{c.name}{i === 0 && <Medal size={13} weight="fill" color="var(--warn)" style={{ marginLeft: 6, verticalAlign: "-2px" }} />}</span><span className="tabular" style={{ fontWeight: 700, color: "var(--text3)" }}>{fmtShort(c.sales)}</span></div>
              <div style={{ height: 5, borderRadius: 3, background: "var(--border)", overflow: "hidden" }}><div style={{ height: "100%", width: `${Math.round((c.sales / max) * 100)}%`, background: i === 0 ? "var(--accent)" : "var(--accent-border)", borderRadius: 3 }} /></div>
            </div>
          </div>
        ))}
        {cs.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>—</div>}
      </div>
    </CardBox>
  );
}

function InsightsCard({ ov, t }: { ov?: Overview | null; t: T }) {
  type Ins = { icon: React.ReactNode; text: string; color: string };
  const items: Ins[] = [];
  if (ov) {
    const g = ov.delta.sales;
    if (g !== null && g !== undefined) {
      if (g >= 0) items.push({ icon: <TrendUp size={16} weight="bold" />, color: "var(--ok)", text: t("branch.ins.growthUp", { pct: g.toFixed(1) }) });
      else items.push({ icon: <TrendDown size={16} weight="bold" />, color: "var(--danger)", text: t("branch.ins.growthDown", { pct: Math.abs(g).toFixed(1) }) });
    }
    const top = ov.cashiers[0];
    if (top && ov.kpi.sales) items.push({ icon: <Medal size={16} weight="fill" />, color: "var(--accent-strong)", text: t("branch.ins.topCashier", { name: top.name, pct: Math.round((top.sales / ov.kpi.sales) * 100) }) });
    const disc = (ov.series || []).reduce((a, p) => a + p.discount, 0);
    if (disc > 0) items.push({ icon: <Lightbulb size={16} weight="fill" />, color: "var(--warn)", text: t("branch.ins.discount", { sum: fmt(disc) }) });
  }
  return (
    <CardBox title={t("branch.insights")} icon={<Lightbulb size={17} weight="fill" />}>
      {items.length === 0 ? <div style={{ color: "var(--muted)", fontSize: 13 }}>—</div> : (
        <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
          {items.slice(0, 4).map((it, i) => (
            <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 10, fontSize: 13, lineHeight: 1.4 }}><span style={{ color: it.color, flex: "none", marginTop: 1 }}>{it.icon}</span><span style={{ color: "var(--text2)" }}>{it.text}</span></div>
          ))}
        </div>
      )}
    </CardBox>
  );
}
