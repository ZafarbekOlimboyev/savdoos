import { useEffect, useState } from "react";
import { ShieldCheck } from "@phosphor-icons/react";
import { api, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Modal, Topbar, inputStyle, td, th, useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";

interface Emp { id: string; full_name: string; phone: string | null; role: string; role_name: string; status: string; branch?: string | null; }

const ROLES = [["ega", "Ega"], ["administrator", "Administrator"], ["menejer", "Menejer"], ["omborchi", "Omborchi"], ["kassir", "Kassir"]];
const ROLE_COLOR: Record<string, [string, string]> = { ega: ["rgba(201,151,0,0.16)", "#c99700"], administrator: ["var(--accent-soft)", "var(--accent-strong)"], menejer: ["var(--info-soft)", "#3b82f6"], omborchi: ["var(--warn-soft)", "var(--warn)"], kassir: ["var(--border)", "var(--text3)"] };
// Telefon maydoni ochilganда avto to'ldiriladi (login kabi) — foydalanuvchi davom ettirib yozadi,
// xohlasa o'chirib boshqa kod (masalan +996) qo'yadi. Bo'sh (faqat prefiks) bo'lsa — telefonsiz saqlanadi.
const PHONE_PREFIX = "+998 ";

export function Employees() {
  const { data, err, reload } = useGet<Emp[]>("/employees");
  const [add, setAdd] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [roleFilter, setRoleFilter] = useState("all");
  const t = useT();
  const all = data || [];
  const rows = all.filter((e) => roleFilter === "all" || e.role === roleFilter);

  const kpi = [
    { label: t("emp.totalEmp"), value: all.length, color: "var(--accent-strong)" },
    { label: t("emp.cashiers"), value: all.filter((e) => e.role === "kassir").length, color: "var(--text)" },
    { label: t("emp.role_administrator"), value: all.filter((e) => e.role === "administrator").length, color: "var(--text)" },
    { label: t("emp.kpiActive"), value: all.filter((e) => e.status === "active").length, color: "var(--ok)" },
  ];

  return (
    <main className="main">
      <Topbar title={t("nav.xodimlar")} sub={t("emp.sub")}
        right={<button className="btn btn-primary" onClick={() => setAdd(true)}>＋ {t("emp.addEmp")}</button>} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {err && <div style={{ color: "var(--red)", marginBottom: 12 }}>{err}</div>}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 18 }}>
          {kpi.map((k) => (
            <div key={k.label} className="card" style={{ padding: "15px 18px" }}>
              <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{k.label}</div>
              <div className="tabular" style={{ fontSize: 24, fontWeight: 800, marginTop: 6, color: k.color }}>{k.value}</div>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
          {[["all"], ...ROLES].map(([k]) => {
            const on = roleFilter === k;
            return <button key={k} onClick={() => setRoleFilter(k)} style={{ height: 38, padding: "0 15px", borderRadius: 10, fontSize: 13, fontWeight: 600, cursor: "pointer", border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`, background: on ? "var(--accent)" : "var(--card)", color: on ? "#fff" : "var(--text3)" }}>{k === "all" ? t("pos.all") : t("emp.role_" + k)}</button>;
          })}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "var(--card-alt)" }}><th style={th}>{t("emp.thEmployee")}</th><th style={th}>{t("emp.thRole")}</th><th style={th}>{t("emp.thBranch")}</th><th style={th}>{t("cust.thPhone")}</th><th style={th}>{t("emp.thStatus")}</th></tr></thead>
            <tbody>
              {rows.map((e) => {
                const rc = ROLE_COLOR[e.role] || ["var(--border)", "var(--text3)"];
                return (
                  <tr key={e.id} onClick={() => setDetailId(e.id)} style={{ cursor: "pointer" }}>
                    <td style={{ ...td }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <div style={{ width: 34, height: 34, borderRadius: "50%", background: "var(--accent-soft)", color: "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700 }}>{e.full_name.charAt(0)}</div>
                        <span style={{ fontWeight: 600 }}>{e.full_name}</span>
                      </div>
                    </td>
                    <td style={td}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 11px", borderRadius: 9, background: rc[0], color: rc[1] }}>{e.role_name}</span></td>
                    <td style={{ ...td, color: e.branch ? "var(--text3)" : "var(--muted)" }}>{e.branch || "—"}</td>
                    <td style={{ ...td, color: "var(--text3)" }} className="tabular">{e.phone}</td>
                    <td style={td}><span style={{ fontSize: 12.5, fontWeight: 600, color: e.status === "active" ? "var(--ok)" : "var(--danger)" }}>● {e.status === "active" ? t("emp.statusActive") : e.status === "suspended" ? t("emp.statusSuspended") : t("emp.statusFired")}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      {add && <AddEmp onClose={() => setAdd(false)} onSaved={() => { setAdd(false); reload(); }} />}
      {detailId && <DetailModal id={detailId} onClose={() => setDetailId(null)} onChanged={reload} />}
    </main>
  );
}

const MODULE_LABEL: Record<string, string> = {
  kassa: "nav.kassa", sotuvlar: "nav.sotuvlar", qaytarishlar: "nav.qaytarishlar", mijozlar: "nav.mijozlar",
  mahsulotlar: "emp.mod_mahsulotlar", ombor: "emp.mod_ombor", xaridlar: "nav.xaridlar", hisobot: "emp.mod_hisobot",
  xodimlar: "nav.xodimlar", sozlamalar: "nav.sozlamalar",
};

// Ruxsat kodining amal qismi -> tushunarli nom (kassa.sell -> "Sotish")
const ACTION_LABEL: Record<string, string> = { view: "perm.view", edit: "perm.edit", sell: "perm.sell", create: "perm.create", make_admin: "perm.make_admin" };
function permLabel(code: string, t: (k: string) => string): string {
  const action = code.split(".")[1] || "";
  return ACTION_LABEL[action] ? t(ACTION_LABEL[action]) : code;
}

function DetailModal({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const perms = useGet<{ code: string; module: string }[]>("/permissions");
  const emp = useGet<{ full_name: string; phone: string | null; role: string; role_name: string; branch_id: string | null; permissions: string[] }>(`/employees/${id}`);
  const stats = useGet<{ month_sales: number; tx: number; chart: { label: string; sales: number }[] }>(`/employees/${id}/stats`);
  const branches = useGet<{ branches: { id: string; name: string }[] }>("/branches");
  const [local, setLocal] = useState<Record<string, boolean>>({});
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState("kassir");
  const [branchId, setBranchId] = useState("");
  const [newPw, setNewPw] = useState("");
  const [busy, setBusy] = useState(false);
  const t = useT();

  useEffect(() => {
    if (emp.data && perms.data) {
      const m: Record<string, boolean> = {};
      perms.data.forEach((p) => (m[p.code] = emp.data!.permissions.includes(p.code)));
      setLocal(m);
      setName(emp.data.full_name); setPhone(emp.data.phone || PHONE_PREFIX); setRole(emp.data.role);
      setBranchId(emp.data.branch_id || "");
    }
  }, [emp.data, perms.data]);

  async function toggle(code: string) {
    const next = { ...local, [code]: !local[code] };
    setLocal(next);
    try { await api(`/employees/${id}/permissions`, { method: "PATCH", body: JSON.stringify({ overrides: { [code]: next[code] } }) }); }
    catch { setLocal((prev) => ({ ...prev, [code]: !next[code] })); }
  }
  const [err, setErr] = useState("");
  async function save() {
    setBusy(true); setErr("");
    try {
      const body: any = { full_name: name, phone: phone.trim() === PHONE_PREFIX.trim() ? "" : phone, role_code: role, branch_id: branchId };
      if (newPw) body.password = newPw;
      await api(`/employees/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      setNewPw(""); onChanged();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }
  async function del() {
    if (!window.confirm(t("cust.deleteConfirm", { name }))) return;
    setBusy(true); setErr("");
    try { await api(`/employees/${id}`, { method: "DELETE" }); onChanged(); onClose(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  const groups: Record<string, { code: string }[]> = {};
  // make_admin — oddiy ruxsat guruhlarида ko'rsatilmaydi; faqat admin kartasида alohida beriladi (Ega).
  (perms.data || []).filter((p) => p.code !== "xodimlar.make_admin").forEach((p) => { (groups[p.module] = groups[p.module] || []).push(p); });
  const maxH = Math.max(1, ...(stats.data?.chart || []).map((c) => c.sales));
  const compact = (n: number) => (n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(Math.round(n)));

  return (
    <Modal onClose={onClose} width={540}>
      <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 10 }}>{t("emp.empCard")}</div>
      {/* Ichki scroll YO'Q — Modal o'zi aylantiradi. Ixcham joylashuv — karta ekranga sig'sin. */}
      <div>
        {/* tahrirlash: 3 qator — ism+rol · telefon+filial · parol */}
        <div style={{ display: "flex", gap: 10, marginBottom: 8 }}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("pos.firstName")} style={inputStyle} />
          <select value={role} onChange={(e) => setRole(e.target.value)} style={{ ...inputStyle, width: 150 }}>
            {ROLES.map(([k]) => <option key={k} value={k}>{t("emp.role_" + k)}</option>)}
          </select>
        </div>
        <div style={{ display: "flex", gap: 10, marginBottom: 8 }}>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder={t("cust.thPhone")} style={inputStyle} />
          <select value={branchId} onChange={(e) => setBranchId(e.target.value)} title={t("emp.branch")} style={{ ...inputStyle, width: 190 }}>
            <option value="">{t("emp.branchNone")}</option>
            {(branches.data?.branches || []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <input value={newPw} onChange={(e) => setNewPw(e.target.value)} type="password" autoComplete="new-password" placeholder={t("emp.newPassword")} style={{ ...inputStyle, marginBottom: 10 }} />

        {/* statistika */}
        <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
          <div style={{ flex: 1, background: "var(--surface)", borderRadius: 12, padding: "9px 12px" }}><div style={{ fontSize: 11, color: "var(--muted)" }}>{t("emp.monthSales")}</div><div style={{ fontSize: 15, fontWeight: 800, marginTop: 2 }} className="tabular">{stats.data ? fmt(stats.data.month_sales) : "—"}</div></div>
          <div style={{ flex: 1, background: "var(--surface)", borderRadius: 12, padding: "9px 12px" }}><div style={{ fontSize: 11, color: "var(--muted)" }}>{t("sales.receipts")}</div><div style={{ fontSize: 15, fontWeight: 800, marginTop: 2 }}>{stats.data?.tx ?? "—"}</div></div>
        </div>
        <div style={{ background: "var(--surface)", borderRadius: 12, padding: "10px 14px", marginBottom: 10 }}>
          <div style={{ fontSize: 11.5, color: "var(--muted)", marginBottom: 6 }}>{t("emp.last6mSales")}</div>
          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 8, height: 58 }}>
            {(stats.data?.chart || []).map((cc, i) => (
              <div key={i} title={fmt(cc.sales)} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 3, height: "100%", justifyContent: "flex-end" }}>
                <div style={{ fontSize: 9.5, color: "var(--muted)" }}>{cc.sales ? compact(cc.sales) : ""}</div>
                <div style={{ width: "60%", maxWidth: 22, borderRadius: 5, background: "var(--accent)", height: `${Math.round((cc.sales / maxH) * 40)}px` }} />
                <div style={{ fontSize: 10, color: "var(--muted)" }}>{cc.label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* ruxsatlar */}
        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>{t("emp.permissions")}</div>
        {role === "ega" || role === "administrator" ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "10px 13px", borderRadius: 11, background: "var(--accent-soft)", color: "var(--accent-strong)", fontSize: 13, fontWeight: 600 }}>
              <ShieldCheck size={17} weight="fill" />{role === "ega" ? t("emp.egaAllPerms") : t("emp.adminAllPerms")}
            </div>
            {/* Ega adminga "boshqani admin qilish" huquqini beradi (make_admin). Ega'da doim bor. */}
            {role === "administrator" && (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 2px", marginTop: 8 }}>
                <span style={{ fontSize: 13.5, color: local["xodimlar.make_admin"] ? "var(--ink)" : "var(--muted)" }}>{t("perm.make_admin")}</span>
                <button onClick={() => toggle("xodimlar.make_admin")} style={{ width: 42, height: 23, borderRadius: 12, border: "none", background: local["xodimlar.make_admin"] ? "var(--accent)" : "var(--border-input)", position: "relative", cursor: "pointer", flex: "none" }}>
                  <span style={{ position: "absolute", top: 3, left: local["xodimlar.make_admin"] ? 22 : 3, width: 17, height: 17, borderRadius: "50%", background: "var(--card)", transition: "left .15s" }} />
                </button>
              </div>
            )}
          </>
        ) : (
          Object.entries(groups).map(([mod, list]) => (
            <div key={mod} style={{ marginBottom: 14, border: "1px solid var(--border)", borderRadius: 12, padding: "10px 14px" }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text2)", marginBottom: 6 }}>{t(MODULE_LABEL[mod] || mod)}</div>
              {list.map((p) => {
                const on = !!local[p.code];
                return (
                  <div key={p.code} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 0" }}>
                    <span style={{ fontSize: 13.5, color: on ? "var(--ink)" : "var(--muted)" }}>{permLabel(p.code, t)}</span>
                    <button onClick={() => toggle(p.code)} style={{ width: 42, height: 23, borderRadius: 12, border: "none", background: on ? "var(--accent)" : "var(--border-input)", position: "relative", cursor: "pointer", flex: "none" }}>
                      <span style={{ position: "absolute", top: 3, left: on ? 22 : 3, width: 17, height: 17, borderRadius: "50%", background: "var(--card)", transition: "left .15s" }} />
                    </button>
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>

      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 8 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
        <button className="btn" style={{ background: "var(--danger-soft)", color: "var(--danger)", padding: "0 16px" }} disabled={busy} onClick={del}>🗑</button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-ghost" onClick={onClose}>{t("common.close")}</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "..." : t("common.save")}</button>
      </div>
    </Modal>
  );
}

function AddEmp({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState(PHONE_PREFIX);
  const [role, setRole] = useState("kassir");
  const [password, setPassword] = useState("");
  const [branchId, setBranchId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const branches = useGet<{ branches: { id: string; name: string }[] }>("/branches");
  const t = useT();

  useEffect(() => {
    const list = branches.data?.branches || [];
    if (list.length && !branchId) setBranchId(list[0].id);
  }, [branches.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    if (!name.trim()) return;
    setBusy(true); setErr("");
    try {
      const cleanPhone = phone.trim() === PHONE_PREFIX.trim() ? "" : phone;
      await post("/employees", { full_name: name, phone: cleanPhone, role_code: role, password: password || null, branch_id: branchId || null });
      onSaved();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  const branchList = branches.data?.branches || [];
  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>{t("emp.newEmp")}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input placeholder={t("emp.namePlaceholder")} value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} />
        <input placeholder={t("pos.phonePlaceholder")} value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="off" style={inputStyle} />
        <select value={role} onChange={(e) => setRole(e.target.value)} style={inputStyle}>
          {ROLES.map(([k]) => <option key={k} value={k}>{t("emp.role_" + k)}</option>)}
        </select>
        <div>
          <div style={{ fontSize: 11.5, color: "var(--muted)", marginBottom: 5 }}>{t("emp.branch")}</div>
          <select value={branchId} onChange={(e) => setBranchId(e.target.value)} style={inputStyle}>
            <option value="">{t("emp.branchNone")}</option>
            {branchList.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <input placeholder={t("emp.passwordPlaceholder")} value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="new-password" style={inputStyle} />
        <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: -4 }}>{t("emp.passwordHint")}</div>
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : t("common.add")}</button>
      </div>
    </Modal>
  );
}
