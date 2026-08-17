import { useEffect, useState } from "react";
import { api, post } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Modal, Topbar, inputStyle, td, th, useGet } from "@/components/ui";

interface Emp { id: string; full_name: string; phone: string | null; role: string; role_name: string; status: string; }

const ROLES = [["administrator", "Administrator"], ["menejer", "Menejer"], ["omborchi", "Omborchi"], ["kassir", "Kassir"]];
const ROLE_COLOR: Record<string, [string, string]> = { administrator: ["#efedfb", "#5a4bc4"], menejer: ["#eaf3ff", "#2b6cb0"], omborchi: ["#fef7e6", "#c08a1e"], kassir: ["#eef0f5", "#5b6072"] };

export function Employees() {
  const { data, err, reload } = useGet<Emp[]>("/employees");
  const [add, setAdd] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const rows = data || [];

  return (
    <main className="main">
      <Topbar title="Xodimlar" sub="Jamoa, rollar va ruxsatlar"
        right={<button className="btn btn-primary" onClick={() => setAdd(true)}>＋ Xodim qo'shish</button>} />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {err && <div style={{ color: "var(--red)", marginBottom: 12 }}>{err}</div>}
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr style={{ background: "#f8f9fc" }}><th style={th}>Xodim</th><th style={th}>Lavozim</th><th style={th}>Telefon</th><th style={th}>Holat</th></tr></thead>
            <tbody>
              {rows.map((e) => {
                const rc = ROLE_COLOR[e.role] || ["#eef0f5", "#5b6072"];
                return (
                  <tr key={e.id} onClick={() => setDetailId(e.id)} style={{ cursor: "pointer" }}>
                    <td style={{ ...td }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <div style={{ width: 34, height: 34, borderRadius: "50%", background: "#efedfb", color: "#5a4bc4", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700 }}>{e.full_name.charAt(0)}</div>
                        <span style={{ fontWeight: 600 }}>{e.full_name}</span>
                      </div>
                    </td>
                    <td style={td}><span style={{ fontSize: 11.5, fontWeight: 600, padding: "4px 11px", borderRadius: 9, background: rc[0], color: rc[1] }}>{e.role_name}</span></td>
                    <td style={{ ...td, color: "#5b6072" }} className="tabular">{e.phone}</td>
                    <td style={td}><span style={{ fontSize: 12.5, fontWeight: 600, color: "#12915a" }}>● {e.status === "active" ? "Faol" : e.status}</span></td>
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
  kassa: "Kassa", sotuvlar: "Sotuvlar", qaytarishlar: "Qaytarishlar", mijozlar: "Mijozlar",
  mahsulotlar: "Mahsulotlar", ombor: "Ombor", xaridlar: "Xaridlar", hisobot: "Hisobot",
  xodimlar: "Xodimlar", sozlamalar: "Sozlamalar",
};

function DetailModal({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const perms = useGet<{ code: string; module: string }[]>("/permissions");
  const emp = useGet<{ full_name: string; phone: string | null; role: string; role_name: string; permissions: string[] }>(`/employees/${id}`);
  const stats = useGet<{ month_sales: number; tx: number; chart: { label: string; hours: number }[] }>(`/employees/${id}/stats`);
  const [local, setLocal] = useState<Record<string, boolean>>({});
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState("kassir");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (emp.data && perms.data) {
      const m: Record<string, boolean> = {};
      perms.data.forEach((p) => (m[p.code] = emp.data!.permissions.includes(p.code)));
      setLocal(m);
      setName(emp.data.full_name); setPhone(emp.data.phone || ""); setRole(emp.data.role);
    }
  }, [emp.data, perms.data]);

  async function toggle(code: string) {
    const next = { ...local, [code]: !local[code] };
    setLocal(next);
    try { await api(`/employees/${id}/permissions`, { method: "PATCH", body: JSON.stringify({ overrides: { [code]: next[code] } }) }); }
    catch { setLocal(local); }
  }
  async function save() {
    setBusy(true);
    try { await api(`/employees/${id}`, { method: "PATCH", body: JSON.stringify({ full_name: name, phone, role_code: role }) }); onChanged(); }
    finally { setBusy(false); }
  }
  async function del() {
    if (!window.confirm(`"${name}" o'chirilsinmi?`)) return;
    setBusy(true);
    try { await api(`/employees/${id}`, { method: "DELETE" }); onChanged(); onClose(); }
    finally { setBusy(false); }
  }

  const groups: Record<string, { code: string }[]> = {};
  (perms.data || []).forEach((p) => { (groups[p.module] = groups[p.module] || []).push(p); });
  const maxH = Math.max(1, ...(stats.data?.chart || []).map((c) => c.hours));

  return (
    <Modal onClose={onClose} width={540}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 14 }}>Xodim kartasi</div>
      <div style={{ maxHeight: "68vh", overflowY: "auto" }}>
        {/* tahrirlash */}
        <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ism" style={inputStyle} />
          <select value={role} onChange={(e) => setRole(e.target.value)} style={{ ...inputStyle, width: 150 }}>
            {ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </div>
        <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Telefon" style={{ ...inputStyle, marginBottom: 16 }} />

        {/* statistika */}
        <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
          <div style={{ flex: 1, background: "#f7f8fb", borderRadius: 12, padding: 12 }}><div style={{ fontSize: 11.5, color: "#8b91a4" }}>Oylik savdo</div><div style={{ fontSize: 16, fontWeight: 800, marginTop: 3 }} className="tabular">{stats.data ? fmt(stats.data.month_sales) : "—"}</div></div>
          <div style={{ flex: 1, background: "#f7f8fb", borderRadius: 12, padding: 12 }}><div style={{ fontSize: 11.5, color: "#8b91a4" }}>Cheklar</div><div style={{ fontSize: 16, fontWeight: 800, marginTop: 3 }}>{stats.data?.tx ?? "—"}</div></div>
        </div>
        <div style={{ background: "#f7f8fb", borderRadius: 12, padding: "14px 16px", marginBottom: 16 }}>
          <div style={{ fontSize: 12, color: "#8b91a4", marginBottom: 10 }}>So'nggi 6 oy — ish soati</div>
          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 8, height: 80 }}>
            {(stats.data?.chart || []).map((cc, i) => (
              <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 5, height: "100%", justifyContent: "flex-end" }}>
                <div style={{ fontSize: 10, color: "#8b91a4" }}>{cc.hours}</div>
                <div style={{ width: "60%", maxWidth: 22, borderRadius: 5, background: "var(--accent)", height: `${Math.round((cc.hours / maxH) * 60)}px` }} />
                <div style={{ fontSize: 10.5, color: "#9aa0b4" }}>{cc.label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* ruxsatlar */}
        <div style={{ fontSize: 11, fontWeight: 700, color: "#a2a7b8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>Ruxsatlar</div>
        {Object.entries(groups).map(([mod, list]) => (
          <div key={mod} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#c0c4d2", marginBottom: 4 }}>{MODULE_LABEL[mod] || mod}</div>
            {list.map((p) => {
              const on = !!local[p.code];
              return (
                <div key={p.code} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0" }}>
                  <span style={{ fontSize: 13, color: on ? "var(--ink)" : "#8b91a4" }}>{p.code}</span>
                  <button onClick={() => toggle(p.code)} style={{ width: 42, height: 23, borderRadius: 12, border: "none", background: on ? "var(--accent)" : "#dfe2ec", position: "relative", cursor: "pointer" }}>
                    <span style={{ position: "absolute", top: 3, left: on ? 22 : 3, width: 17, height: 17, borderRadius: "50%", background: "#fff" }} />
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
        <button className="btn" style={{ background: "#fdecec", color: "#c93a3e", padding: "0 16px" }} disabled={busy} onClick={del}>🗑</button>
        <div style={{ flex: 1 }} />
        <button className="btn btn-ghost" onClick={onClose}>Yopish</button>
        <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? "..." : "Saqlash"}</button>
      </div>
    </Modal>
  );
}

function AddEmp({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState("kassir");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    if (!name.trim()) return;
    setBusy(true); setErr("");
    try { await post("/employees", { full_name: name, phone, role_code: role, pin: pin || null }); onSaved(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <Modal onClose={onClose}>
      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 16 }}>Yangi xodim</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <input placeholder="Ism familiya" value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} />
        <input placeholder="+998 __ ___ __ __" value={phone} onChange={(e) => setPhone(e.target.value)} style={inputStyle} />
        <select value={role} onChange={(e) => setRole(e.target.value)} style={inputStyle}>
          {ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <input placeholder="PIN (4 xona)" value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))} style={inputStyle} />
      </div>
      {err && <div style={{ color: "var(--red)", fontSize: 13, marginTop: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
        <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onClose}>Bekor</button>
        <button className="btn btn-primary" style={{ flex: 1 }} disabled={busy} onClick={save}>{busy ? "..." : "Qo'shish"}</button>
      </div>
    </Modal>
  );
}
