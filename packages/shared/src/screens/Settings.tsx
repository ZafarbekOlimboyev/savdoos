import { useEffect, useState } from "react";
import { CreditCard, Percent, Receipt, ShieldCheck, Storefront } from "@phosphor-icons/react";
import { get, put } from "@/lib/api";
import { Topbar, inputStyle } from "@/components/ui";

interface SettingsData {
  payments?: { karta?: boolean; qr?: boolean; qarz?: boolean };
  features?: { returns?: boolean };
  store_info?: { name?: string; branch?: string; address?: string; phone?: string; stir?: string };
  tax?: { rate?: number; vat_on?: boolean; max_disc?: number };
  receipt?: { header?: string; footer?: string; show_barcode?: boolean };
  security?: { force_shift?: boolean; auto_logout?: number };
}

const TABS = [
  { key: "general", label: "Umumiy", Icon: Storefront },
  { key: "payment", label: "To'lov va savdo", Icon: CreditCard },
  { key: "receipt", label: "Chek va printer", Icon: Receipt },
  { key: "tax", label: "Soliq va chegirma", Icon: Percent },
  { key: "security", label: "Xavfsizlik", Icon: ShieldCheck },
];

export function Settings() {
  const [tab, setTab] = useState("general");
  const [d, setD] = useState<SettingsData>({});
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loadErr, setLoadErr] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    get<SettingsData>("/settings")
      .then((x) => { setD(x); setLoaded(true); setLoadErr(false); })
      .catch(() => setLoadErr(true)); // yuklanmaguncha tahrir yopiq (server qiymatlari o'chib ketmasin)
  }, [retry]);

  async function save(key: string, value: unknown) {
    setSaving(true);
    try { await put("/settings", { key, value }); } finally { setTimeout(() => setSaving(false), 400); }
  }
  const setStore = (patch: Partial<NonNullable<SettingsData["store_info"]>>) => {
    const v = { ...(d.store_info || {}), ...patch }; setD((x) => ({ ...x, store_info: v })); return v;
  };
  const setTax = (patch: Partial<NonNullable<SettingsData["tax"]>>) => {
    const v = { rate: 12, ...(d.tax || {}), ...patch }; setD((x) => ({ ...x, tax: v })); return v;
  };
  const setReceipt = (patch: Partial<NonNullable<SettingsData["receipt"]>>) => {
    const v = { ...(d.receipt || {}), ...patch }; setD((x) => ({ ...x, receipt: v })); return v;
  };
  const setSec = (patch: Partial<NonNullable<SettingsData["security"]>>) => {
    const v = { ...(d.security || {}), ...patch }; setD((x) => ({ ...x, security: v })); return v;
  };
  const setPay = (patch: Partial<NonNullable<SettingsData["payments"]>>) => {
    const v = { ...(d.payments || {}), ...patch }; setD((x) => ({ ...x, payments: v })); save("payments", v);
  };
  const setFeat = (patch: Partial<NonNullable<SettingsData["features"]>>) => {
    const v = { ...(d.features || {}), ...patch }; setD((x) => ({ ...x, features: v })); save("features", v);
  };

  const store = d.store_info || {};
  const tax = d.tax || {};
  const rc = d.receipt || {};
  const pay = d.payments || {};
  const feat = d.features || {};
  const sec = d.security || {};

  return (
    <main className="main">
      <Topbar title="Sozlamalar" sub="Tizim va do'kon sozlamalari" right={
        <span style={{ fontSize: 12.5, color: saving ? "var(--warn)" : "var(--muted)" }}>{saving ? "Saqlanmoqda…" : "O'zgarishlar avtomatik saqlanadi"}</span>
      } />
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* Tab nav */}
        <div style={{ width: 230, flex: "none", borderRight: "1px solid var(--border)", padding: "18px 12px" }}>
          {TABS.map(({ key, label, Icon }) => {
            const on = tab === key;
            return (
              <button key={key} onClick={() => setTab(key)} style={{ display: "flex", alignItems: "center", gap: 11, width: "100%", padding: "11px 13px", borderRadius: 10, border: "none", cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: on ? 600 : 500, textAlign: "left", marginBottom: 2, background: on ? "var(--accent-soft)" : "transparent", color: on ? "var(--accent-strong)" : "var(--text3)" }}>
                <Icon size={18} weight={on ? "fill" : "regular"} />{label}
              </button>
            );
          })}
        </div>

        {/* Content */}
        <div className="scroll" style={{ flex: 1, padding: 28 }}>
          {!loaded && !loadErr && <div style={{ color: "var(--muted)" }}>Yuklanmoqda…</div>}
          {loadErr && (
            <div className="card" style={{ maxWidth: 460 }}>
              <div style={{ color: "var(--danger)", fontWeight: 600, marginBottom: 10 }}>Sozlamalar yuklanmadi</div>
              <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14 }}>Server bilan aloqa yo'q — xavfsizlik uchun tahrirlash vaqtincha yopiq.</div>
              <button className="btn btn-primary" onClick={() => setRetry((x) => x + 1)}>Qayta urinish</button>
            </div>
          )}

          {loaded && tab === "general" && (
            <Section title="Do'kon ma'lumotlari" desc="Chek va hujjatlarda ko'rinadi.">
              <Row>
                <Field label="Do'kon nomi" value={store.name || ""} onChange={(v) => setStore({ name: v })} onBlur={() => save("store_info", store)} />
                <Field label="Filial" value={store.branch || ""} onChange={(v) => setStore({ branch: v })} onBlur={() => save("store_info", store)} />
              </Row>
              <Field label="Manzil" value={store.address || ""} onChange={(v) => setStore({ address: v })} onBlur={() => save("store_info", store)} placeholder="Toshkent sh., Chilonzor t., ..." />
              <Row>
                <Field label="Telefon" value={store.phone || ""} onChange={(v) => setStore({ phone: v })} onBlur={() => save("store_info", store)} placeholder="+998 __ ___ __ __" />
                <Field label="STIR (INN)" value={store.stir || ""} onChange={(v) => setStore({ stir: v })} onBlur={() => save("store_info", store)} placeholder="9 raqam" />
              </Row>
            </Section>
          )}

          {loaded && tab === "payment" && (
            <>
              <Section title="To'lov usullari" desc="O'chirilgan usullar kassa ekranida ko'rinmaydi.">
                <Toggle label="Naqd (o'zgarmas)" on disabled />
                <Toggle label="Karta" on={pay.karta !== false} onChange={(v) => setPay({ karta: v })} />
                <Toggle label="QR to'lov" on={pay.qr !== false} onChange={(v) => setPay({ qr: v })} />
                <Toggle label="Qarz (nasiya)" on={pay.qarz !== false} onChange={(v) => setPay({ qarz: v })} />
              </Section>
              <Section title="Savdo funksiyalari" desc="Qo'shimcha modullar.">
                <Toggle label="Qaytarishlar moduli" on={feat.returns !== false} onChange={(v) => setFeat({ returns: v })} />
              </Section>
            </>
          )}

          {loaded && tab === "receipt" && (
            <Section title="Chek ko'rinishi" desc="Chekning yuqori va pastki matnlari.">
              <Field label="Yuqori matn (shior)" value={rc.header || ""} onChange={(v) => setReceipt({ header: v })} onBlur={() => save("receipt", rc)} placeholder="Xush kelibsiz!" />
              <Field label="Pastki matn" value={rc.footer || ""} onChange={(v) => setReceipt({ footer: v })} onBlur={() => save("receipt", rc)} placeholder="Xaridingiz uchun rahmat" />
              <Toggle label="Chekda barcode ko'rsatilsin" on={rc.show_barcode !== false} onChange={(v) => save("receipt", setReceipt({ show_barcode: v }))} />
            </Section>
          )}

          {loaded && tab === "tax" && (
            <Section title="Soliq va chegirma" desc="QQS va chegirma cheklovlari.">
              <Toggle label="QQS to'lovchi" on={!!tax.vat_on} onChange={(v) => save("tax", setTax({ vat_on: v }))} />
              <Row>
                <Field label="QQS (%)" value={String(tax.rate ?? 12)} onChange={(v) => setTax({ rate: +v.replace(/[^\d.]/g, "") || 0 })} onBlur={() => save("tax", tax)} />
                <Field label="Maksimal chegirma (%)" value={String(tax.max_disc ?? 0)} onChange={(v) => setTax({ max_disc: +v.replace(/[^\d.]/g, "") || 0 })} onBlur={() => save("tax", tax)} />
              </Row>
            </Section>
          )}

          {loaded && tab === "security" && (
            <>
              <Section title="Xavfsizlik va kirish" desc="Xodimlar PIN kodi bilan kiradi (Xodimlar bo'limidan o'zgartiriladi).">
                <Toggle label="Smenani majburiy ochish" on={!!sec.force_shift} onChange={(v) => save("security", setSec({ force_shift: v }))} />
                <Row>
                  <Field label="Avtomatik chiqish (daqiqa, 0 = o'chiq)" value={String(sec.auto_logout ?? 0)} onChange={(v) => setSec({ auto_logout: +v.replace(/\D/g, "") || 0 })} onBlur={() => save("security", sec)} />
                  <div style={{ flex: 1 }} />
                </Row>
              </Section>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--ok)", marginTop: 4 }}>
                <ShieldCheck size={16} weight="fill" />Parollar bcrypt bilan shifrlanadi · ma'lumotlar xavfsiz serverda
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

function Section({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="card" style={{ marginBottom: 18, maxWidth: 620 }}>
      <div style={{ fontSize: 17, fontWeight: 700 }}>{title}</div>
      {desc && <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 3, marginBottom: 14 }}>{desc}</div>}
      {!desc && <div style={{ height: 14 }} />}
      {children}
    </div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", gap: 12, marginBottom: 12 }}>{children}</div>;
}

function Field({ label, value, onChange, onBlur, placeholder }: { label: string; value: string; onChange: (v: string) => void; onBlur?: () => void; placeholder?: string }) {
  return (
    <div style={{ flex: 1, marginBottom: 12 }}>
      <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} onBlur={onBlur} placeholder={placeholder} style={{ ...inputStyle, marginTop: 6 }} />
    </div>
  );
}

function Toggle({ label, on, onChange, disabled }: { label: string; on: boolean; onChange?: (v: boolean) => void; disabled?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", borderTop: "1px solid var(--border-soft)" }}>
      <span style={{ fontSize: 14, fontWeight: 500, color: disabled ? "var(--muted)" : "var(--text)" }}>{label}</span>
      <button onClick={() => !disabled && onChange?.(!on)} style={{ width: 46, height: 26, borderRadius: 13, border: "none", background: on ? "var(--accent)" : "var(--border-input)", position: "relative", cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.6 : 1 }}>
        <span style={{ position: "absolute", top: 3, left: on ? 23 : 3, width: 20, height: 20, borderRadius: "50%", background: "#fff", transition: "left .15s", boxShadow: "0 1px 3px rgba(0,0,0,0.25)" }} />
      </button>
    </div>
  );
}
