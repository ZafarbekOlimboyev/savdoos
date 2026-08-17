import { useEffect, useState } from "react";
import { get, put } from "@/lib/api";
import { Topbar, inputStyle } from "@/components/ui";

interface SettingsData {
  payments?: { karta?: boolean; qr?: boolean; qarz?: boolean };
  features?: { returns?: boolean };
  store_info?: { name?: string; branch?: string };
  tax?: { rate?: number };
  receipt?: { header?: string; footer?: string; show_barcode?: boolean };
}

export function Settings() {
  const [data, setData] = useState<SettingsData>({});
  const [saving, setSaving] = useState("");
  const [store, setStore] = useState({ name: "", branch: "" });
  const [tax, setTax] = useState("12");
  const [receipt, setReceipt] = useState({ header: "", footer: "", show_barcode: true });

  useEffect(() => {
    get<SettingsData>("/settings").then((d) => {
      setData(d);
      setStore({ name: d.store_info?.name || "", branch: d.store_info?.branch || "" });
      setTax(String(d.tax?.rate ?? 12));
      setReceipt({ header: d.receipt?.header || "", footer: d.receipt?.footer || "", show_barcode: d.receipt?.show_barcode !== false });
    }).catch(() => {});
  }, []);

  async function saveStore() {
    setSaving("store");
    try { await put("/settings", { key: "store_info", value: store }); } finally { setSaving(""); }
  }
  async function saveTax() {
    setSaving("tax");
    try { await put("/settings", { key: "tax", value: { rate: +tax || 0 } }); } finally { setSaving(""); }
  }
  async function saveReceipt(next: typeof receipt) {
    setReceipt(next);
    setSaving("receipt");
    try { await put("/settings", { key: "receipt", value: next }); } finally { setSaving(""); }
  }

  async function savePayments(next: SettingsData["payments"]) {
    setData((d) => ({ ...d, payments: next }));
    setSaving("payments");
    try { await put("/settings", { key: "payments", value: next }); } finally { setSaving(""); }
  }
  async function saveFeatures(next: SettingsData["features"]) {
    setData((d) => ({ ...d, features: next }));
    setSaving("features");
    try { await put("/settings", { key: "features", value: next }); } finally { setSaving(""); }
  }

  const pay = data.payments || {};
  const feat = data.features || {};

  return (
    <main className="main">
      <Topbar title="Sozlamalar" sub="Tizim va do'kon sozlamalari" />
      <div className="scroll" style={{ flex: 1, padding: 24, display: "flex", justifyContent: "center" }}>
        <div style={{ width: 640 }}>
          <div className="card" style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 14 }}>Do'kon ma'lumotlari</div>
            <div style={{ display: "flex", gap: 12, marginBottom: 12 }}>
              <div style={{ flex: 1 }}>
                <label style={{ fontSize: 12.5, color: "#6b7183", fontWeight: 600 }}>Do'kon nomi</label>
                <input value={store.name} onChange={(e) => setStore({ ...store, name: e.target.value })} style={{ ...inputStyle, marginTop: 6 }} />
              </div>
              <div style={{ flex: 1 }}>
                <label style={{ fontSize: 12.5, color: "#6b7183", fontWeight: 600 }}>Filial</label>
                <input value={store.branch} onChange={(e) => setStore({ ...store, branch: e.target.value })} style={{ ...inputStyle, marginTop: 6 }} />
              </div>
            </div>
            <button className="btn btn-primary" style={{ padding: "10px 20px" }} onClick={saveStore}>Saqlash</button>
          </div>

          <div className="card" style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 17, fontWeight: 700 }}>To'lov usullari</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 3, marginBottom: 14 }}>O'chirilgan usullar kassa ekranida ko'rinmaydi.</div>
            <Toggle label="Naqd (o'zgarmas)" on disabled />
            <Toggle label="Karta" on={pay.karta !== false} onChange={(v) => savePayments({ ...pay, karta: v })} />
            <Toggle label="QR to'lov" on={!!pay.qr} onChange={(v) => savePayments({ ...pay, qr: v })} />
            <Toggle label="Qarz (nasiya)" on={!!pay.qarz} onChange={(v) => savePayments({ ...pay, qarz: v })} />
          </div>

          <div className="card">
            <div style={{ fontSize: 17, fontWeight: 700 }}>Savdo funksiyalari</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 3, marginBottom: 14 }}>Qo'shimcha modullarni yoqish/o'chirish.</div>
            <Toggle label="Qaytarishlar moduli" on={feat.returns !== false} onChange={(v) => saveFeatures({ ...feat, returns: v })} />
          </div>

          <div className="card" style={{ marginTop: 18 }}>
            <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>Soliq</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14 }}>QQS foizi — chek va hisobotlarda ishlatiladi.</div>
            <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
              <div style={{ width: 160 }}>
                <label style={{ fontSize: 12.5, color: "#6b7183", fontWeight: 600 }}>QQS (%)</label>
                <input value={tax} onChange={(e) => setTax(e.target.value.replace(/[^\d.]/g, ""))} style={{ ...inputStyle, marginTop: 6 }} />
              </div>
              <button className="btn btn-primary" style={{ padding: "0 20px", height: 44 }} onClick={saveTax}>Saqlash</button>
            </div>
          </div>

          <div className="card" style={{ marginTop: 18 }}>
            <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 14 }}>Chek ko'rinishi</div>
            <label style={{ fontSize: 12.5, color: "#6b7183", fontWeight: 600 }}>Yuqori matn (do'kon shiori)</label>
            <input value={receipt.header} onChange={(e) => setReceipt({ ...receipt, header: e.target.value })} onBlur={() => saveReceipt(receipt)} placeholder="masalan: Xush kelibsiz!" style={{ ...inputStyle, marginTop: 6, marginBottom: 12 }} />
            <label style={{ fontSize: 12.5, color: "#6b7183", fontWeight: 600 }}>Pastki matn</label>
            <input value={receipt.footer} onChange={(e) => setReceipt({ ...receipt, footer: e.target.value })} onBlur={() => saveReceipt(receipt)} placeholder="masalan: Xaridingiz uchun rahmat" style={{ ...inputStyle, marginTop: 6 }} />
            <div style={{ marginTop: 6 }}>
              <Toggle label="Chekda barcode ko'rsatilsin" on={receipt.show_barcode} onChange={(v) => saveReceipt({ ...receipt, show_barcode: v })} />
            </div>
          </div>

          <div className="card" style={{ marginTop: 18 }}>
            <div style={{ fontSize: 17, fontWeight: 700, marginBottom: 4 }}>Xavfsizlik va kirish</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 8 }}>Xodimlar PIN kodi bilan kiradi. PIN'ni Xodimlar bo'limidan o'zgartiring.</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#12915a" }}>🔒 Ma'lumotlar bazasi lokalda saqlanadi · parollar bcrypt bilan shifrlanadi</div>
          </div>

          {saving && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 12 }}>Saqlanmoqda...</div>}
        </div>
      </div>
    </main>
  );
}

function Toggle({ label, on, onChange, disabled }: { label: string; on: boolean; onChange?: (v: boolean) => void; disabled?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", borderTop: "1px solid #f4f5f9" }}>
      <span style={{ fontSize: 14, fontWeight: 500, color: disabled ? "#9aa0b4" : "var(--ink)" }}>{label}</span>
      <button
        onClick={() => !disabled && onChange?.(!on)}
        style={{ width: 46, height: 26, borderRadius: 13, border: "none", background: on ? "var(--accent)" : "#dfe2ec", position: "relative", cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.6 : 1 }}
      >
        <span style={{ position: "absolute", top: 3, left: on ? 23 : 3, width: 20, height: 20, borderRadius: "50%", background: "#fff", transition: "left .15s", boxShadow: "0 1px 3px rgba(28,31,43,0.25)" }} />
      </button>
    </div>
  );
}
