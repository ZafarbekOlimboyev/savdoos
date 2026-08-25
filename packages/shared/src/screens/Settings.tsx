import { useEffect, useState } from "react";
import { Check, CreditCard, CrownSimple, Percent, Receipt, ShieldCheck, Storefront } from "@phosphor-icons/react";
import { get, post, put } from "@/lib/api";
import { Topbar, inputStyle } from "@/components/ui";
import { printReceipt } from "@/lib/receipt";
import { useT } from "@/lib/i18n";
import { useLang, LANGS } from "@/store/lang";
import { THEMES, useTheme } from "@/store/theme";

interface SettingsData {
  payments?: { karta?: boolean; qr?: boolean; qarz?: boolean; qr_mode?: "manual" | "xpay" };
  features?: { returns?: boolean };
  store_info?: { name?: string; branch?: string; address?: string; phone?: string; stir?: string };
  tax?: { rate?: number; vat_on?: boolean; max_disc?: number };
  receipt?: { header?: string; footer?: string; show_barcode?: boolean; printer?: string };
  security?: { force_shift?: boolean; auto_logout?: number };
  plan?: { plan?: string };
}

const TABS = [
  { key: "general", label: "Umumiy", Icon: Storefront },
  { key: "tarif", label: "Tarif", Icon: CrownSimple },
  { key: "payment", label: "To'lov va savdo", Icon: CreditCard },
  { key: "receipt", label: "Chek va printer", Icon: Receipt },
  { key: "tax", label: "Soliq va chegirma", Icon: Percent },
  { key: "security", label: "Xavfsizlik", Icon: ShieldCheck },
];

const PLANS: { key: string; branches: number }[] = [
  { key: "start", branches: 1 },
  { key: "start+", branches: 5 },
  { key: "business", branches: 999 },
];

export function Settings() {
  const t = useT();
  const { lang, set: setLang } = useLang();
  const { theme, set: setTheme } = useTheme();
  const [tab, setTab] = useState("general");
  const [d, setD] = useState<SettingsData>({});
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loadErr, setLoadErr] = useState(false);
  const [retry, setRetry] = useState(0);
  const [xpayAvail, setXpayAvail] = useState(false);

  useEffect(() => {
    get<SettingsData>("/settings")
      .then((x) => { setD(x); setLoaded(true); setLoadErr(false); })
      .catch(() => setLoadErr(true)); // yuklanmaguncha tahrir yopiq (server qiymatlari o'chib ketmasin)
    get<{ xpay_enabled: boolean }>("/payments/config").then((c) => setXpayAvail(!!c.xpay_enabled)).catch(() => setXpayAvail(false));
  }, [retry]);

  async function save(key: string, value: unknown) {
    setSaving(true);
    try { await put("/settings", { key, value }); setSaveErr(false); }
    catch { setSaveErr(true); }
    finally { setTimeout(() => setSaving(false), 400); }
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
  const setPlan = (plan: string) => {
    const v = { plan }; setD((x) => ({ ...x, plan: v })); save("plan", v);
  };

  const store = d.store_info || {};
  const tax = d.tax || {};
  const rc = d.receipt || {};
  const pay = d.payments || {};
  const feat = d.features || {};
  const sec = d.security || {};

  return (
    <main className="main">
      <Topbar title={t("nav.sozlamalar")} sub={t("settings.sub")} right={
        <span style={{ fontSize: 12.5, color: saving ? "var(--warn)" : saveErr ? "var(--danger)" : "var(--muted)" }}>{saving ? t("common.saving") : saveErr ? t("settings.saveFailed") : t("common.autoSaved")}</span>
      } />
      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* Tab nav */}
        <div style={{ width: 230, flex: "none", borderRight: "1px solid var(--border)", padding: "18px 12px" }}>
          {TABS.map(({ key, label, Icon }) => {
            const on = tab === key;
            return (
              <button key={key} onClick={() => setTab(key)} style={{ display: "flex", alignItems: "center", gap: 11, width: "100%", padding: "11px 13px", borderRadius: 10, border: "none", cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: on ? 600 : 500, textAlign: "left", marginBottom: 2, background: on ? "var(--accent-soft)" : "transparent", color: on ? "var(--accent-strong)" : "var(--text3)" }}>
                <Icon size={18} weight={on ? "fill" : "regular"} />{t("settings.tab_" + key)}
              </button>
            );
          })}
        </div>

        {/* Content */}
        <div className="scroll" style={{ flex: 1, padding: 28 }}>
          {!loaded && !loadErr && <div style={{ color: "var(--muted)" }}>{t("common.loading")}</div>}
          {loadErr && (
            <div className="card" style={{ maxWidth: 460 }}>
              <div style={{ color: "var(--danger)", fontWeight: 600, marginBottom: 10 }}>{t("settings.loadErrTitle")}</div>
              <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14 }}>{t("settings.loadErrText")}</div>
              <button className="btn btn-primary" onClick={() => setRetry((x) => x + 1)}>{t("common.retry")}</button>
            </div>
          )}

          {loaded && tab === "general" && (
            <>
              <Section title={t("settings.storeInfo")} desc={t("settings.storeInfoDesc")}>
                <Row>
                  <Field label={t("settings.storeName")} value={store.name || ""} onChange={(v) => setStore({ name: v })} onBlur={() => save("store_info", store)} />
                  <Field label={t("settings.branch")} value={store.branch || ""} onChange={(v) => setStore({ branch: v })} onBlur={() => save("store_info", store)} />
                </Row>
                <Field label={t("settings.address")} value={store.address || ""} onChange={(v) => setStore({ address: v })} onBlur={() => save("store_info", store)} placeholder={t("settings.addressPlaceholder")} />
                <Row>
                  <Field label={t("cust.thPhone")} value={store.phone || ""} onChange={(v) => setStore({ phone: v })} onBlur={() => save("store_info", store)} placeholder={t("pos.phonePlaceholder")} />
                  <Field label={t("settings.tin")} value={store.stir || ""} onChange={(v) => setStore({ stir: v })} onBlur={() => save("store_info", store)} placeholder={t("settings.tinPlaceholder")} />
                </Row>
              </Section>
              <Section title={t("settings.langTitle")} desc={t("settings.langDesc")}>
                <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
                  {LANGS.map((l) => (
                    <button key={l.code} onClick={() => setLang(l.code)}
                      style={{ flex: 1, height: 46, borderRadius: 11, cursor: "pointer", font: "inherit", fontSize: 14, fontWeight: 600,
                        border: `1.5px solid ${lang === l.code ? "var(--accent)" : "var(--border)"}`,
                        background: lang === l.code ? "var(--accent-soft)" : "var(--card)",
                        color: lang === l.code ? "var(--accent-strong)" : "var(--text3)" }}>
                      {l.native}
                    </button>
                  ))}
                </div>
              </Section>
              <Section title={t("theme.title")} desc={t("theme.pick")}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginTop: 4 }}>
                  {THEMES.map((th) => {
                    const on = theme === th.id;
                    return (
                      <button key={th.id} onClick={() => setTheme(th.id)}
                        style={{ border: "none", background: "none", cursor: "pointer", padding: 0, font: "inherit" }}>
                        <div style={{ height: 64, borderRadius: 12, background: th.bg, position: "relative", overflow: "hidden",
                          border: on ? `2.5px solid ${th.accent}` : "1px solid var(--border-input)" }}>
                          <div style={{ position: "absolute", left: 10, top: 12, width: 42, height: 8, borderRadius: 4, background: th.accent }} />
                          <div style={{ position: "absolute", left: 10, top: 27, width: 62, height: 7, borderRadius: 3, background: th.card, border: "1px solid rgba(128,128,150,0.25)" }} />
                          <div style={{ position: "absolute", left: 10, top: 40, width: 34, height: 7, borderRadius: 3, background: th.card, border: "1px solid rgba(128,128,150,0.25)" }} />
                          {on && <div style={{ position: "absolute", right: 6, top: 6, width: 16, height: 16, borderRadius: "50%", background: th.accent, color: "#fff", fontSize: 11, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center" }}>✓</div>}
                        </div>
                        <div style={{ marginTop: 6, fontSize: 12, fontWeight: on ? 800 : 600, color: on ? "var(--accent-strong)" : "var(--text2)", textAlign: "center" }}>
                          {t(`theme.${th.id}`)}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </Section>
            </>
          )}

          {loaded && tab === "tarif" && (
            <Section title={t("settings.planTitle")} desc={t("settings.planDesc")}>
              <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 4 }}>
                {PLANS.map((p) => {
                  const cur = (d.plan?.plan || "start") === p.key;
                  const limit = p.branches >= 999 ? t("settings.planUnlimited") : t("settings.planBranches", { n: p.branches });
                  return (
                    <button key={p.key} onClick={() => setPlan(p.key)}
                      style={{ display: "flex", alignItems: "center", gap: 14, width: "100%", padding: "16px 18px", borderRadius: 14, cursor: "pointer", font: "inherit", textAlign: "left",
                        border: `1.5px solid ${cur ? "var(--accent)" : "var(--border)"}`, background: cur ? "var(--accent-soft)" : "var(--card)" }}>
                      <div style={{ width: 44, height: 44, flex: "none", borderRadius: 12, background: cur ? "var(--accent)" : "var(--surface)", color: cur ? "#fff" : "var(--accent-strong)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                        <CrownSimple size={22} weight="fill" />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 15.5, fontWeight: 700, color: cur ? "var(--accent-strong)" : "var(--text)" }}>{p.key === "start" ? "Start" : p.key === "start+" ? "Start+" : "Business"}</div>
                        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>{limit}</div>
                      </div>
                      {cur
                        ? <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, fontWeight: 700, color: "var(--accent-strong)", background: "var(--card)", padding: "5px 11px", borderRadius: 8 }}><Check size={13} weight="bold" />{t("settings.planCurrent")}</span>
                        : <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--faint)" }}>{t("settings.planSelect")}</span>}
                    </button>
                  );
                })}
              </div>
              <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 14, lineHeight: 1.5 }}>{t("settings.planNote")}</div>
            </Section>
          )}

          {loaded && tab === "payment" && (
            <>
              <Section title={t("settings.payMethods")} desc={t("settings.payMethodsDesc")}>
                <Toggle label={t("settings.cashFixed")} on disabled />
                <Toggle label={t("pay.card")} on={pay.karta !== false} onChange={(v) => setPay({ karta: v })} />
                <Toggle label={t("settings.qrPay")} on={pay.qr !== false} onChange={(v) => setPay({ qr: v })} />
                <Toggle label={t("settings.creditNasiya")} on={pay.qarz !== false} onChange={(v) => setPay({ qarz: v })} />
              </Section>
              {pay.qr !== false && (
                <Section title={t("settings.qrModeTitle")} desc={t("settings.qrModeDesc")}>
                  <QrModeSelect
                    value={pay.qr_mode === "xpay" ? "xpay" : "manual"}
                    xpayAvail={xpayAvail}
                    onChange={(m) => setPay({ qr_mode: m })}
                  />
                </Section>
              )}
              <Section title={t("settings.tradeFeatures")} desc={t("settings.tradeFeaturesDesc")}>
                <Toggle label={t("settings.returnsModule")} on={feat.returns !== false} onChange={(v) => setFeat({ returns: v })} />
              </Section>
            </>
          )}

          {loaded && tab === "receipt" && (
            <Section title={t("settings.receiptView")} desc={t("settings.receiptViewDesc")}>
              <Field label={t("settings.headerText")} value={rc.header || ""} onChange={(v) => setReceipt({ header: v })} onBlur={() => save("receipt", rc)} placeholder={t("settings.headerPlaceholder")} />
              <Field label={t("settings.footerText")} value={rc.footer || ""} onChange={(v) => setReceipt({ footer: v })} onBlur={() => save("receipt", rc)} placeholder={t("settings.footerPlaceholder")} />
              <Toggle label={t("settings.showBarcode")} on={rc.show_barcode !== false} onChange={(v) => save("receipt", setReceipt({ show_barcode: v }))} />
              <PrinterSelect t={t} value={rc.printer} onChange={(v) => save("receipt", setReceipt({ printer: v }))} />
            </Section>
          )}

          {loaded && tab === "tax" && (
            <Section title={t("settings.taxTitle")} desc={t("settings.taxDesc")}>
              <Toggle label={t("settings.vatPayer")} on={!!tax.vat_on} onChange={(v) => save("tax", setTax({ vat_on: v }))} />
              <Row>
                <Field label={t("settings.vatPct")} value={String(tax.rate ?? 12)} onChange={(v) => setTax({ rate: +v.replace(/[^\d.]/g, "") || 0 })} onBlur={() => save("tax", tax)} />
                <Field label={t("settings.maxDiscount")} value={String(tax.max_disc ?? 0)} onChange={(v) => setTax({ max_disc: +v.replace(/[^\d.]/g, "") || 0 })} onBlur={() => save("tax", tax)} />
              </Row>
            </Section>
          )}

          {loaded && tab === "security" && (
            <>
              <Section title={t("settings.securityTitle")} desc={t("settings.securityDesc")}>
                <Toggle label={t("settings.forceShift")} on={!!sec.force_shift} onChange={(v) => save("security", setSec({ force_shift: v }))} />
                <Row>
                  <Field label={t("settings.autoLogout")} value={String(sec.auto_logout ?? 0)} onChange={(v) => setSec({ auto_logout: +v.replace(/\D/g, "") || 0 })} onBlur={() => save("security", sec)} />
                  <div style={{ flex: 1 }} />
                </Row>
              </Section>
              <PasswordChange t={t} />
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--ok)", marginTop: 4 }}>
                <ShieldCheck size={16} weight="fill" />{t("settings.securityFooter")}
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

function PasswordChange({ t }: { t: (k: string) => string }) {
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [newPw2, setNewPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit() {
    if (newPw.length < 6) return setMsg({ ok: false, text: t("settings.pwShort") });
    if (newPw !== newPw2) return setMsg({ ok: false, text: t("settings.pwMismatch") });
    setBusy(true);
    setMsg(null);
    try {
      await post("/auth/password", { old_password: oldPw || null, new_password: newPw });
      setMsg({ ok: true, text: t("settings.pwDone") });
      setOldPw(""); setNewPw(""); setNewPw2("");
    } catch (e: any) {
      setMsg({ ok: false, text: e.message || "Xato" });
    } finally {
      setBusy(false);
    }
  }

  const field = (label: string, value: string, set: (v: string) => void) => (
    <div style={{ marginTop: 10 }}>
      <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{label}</label>
      <input type="password" value={value} onChange={(e) => set(e.target.value)} style={{ ...inputStyle, marginTop: 6 }} />
    </div>
  );

  return (
    <Section title={t("settings.pwTitle")} desc={t("settings.pwDesc")}>
      {field(t("settings.pwOld"), oldPw, setOldPw)}
      {field(t("settings.pwNew"), newPw, setNewPw)}
      {field(t("settings.pwNew2"), newPw2, setNewPw2)}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 14 }}>
        <button className="btn btn-primary" disabled={busy || !newPw || !newPw2} onClick={submit}
          style={{ padding: "9px 18px", fontSize: 13.5 }}>
          {busy ? "..." : t("settings.pwSave")}
        </button>
        {msg && <span style={{ fontSize: 13, color: msg.ok ? "var(--green)" : "var(--red)" }}>{msg.text}</span>}
      </div>
    </Section>
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

function PrinterSelect({ t, value, onChange }: { t: (k: string) => string; value?: string; onChange: (v: string) => void }) {
  const [printers, setPrinters] = useState<{ name: string; displayName?: string }[]>([]);
  const [avail, setAvail] = useState(false);
  useEffect(() => {
    if (typeof window !== "undefined" && window.savdoosPrint) {
      setAvail(true);
      window.savdoosPrint.listPrinters().then((ps) => setPrinters(ps || [])).catch(() => {});
    }
  }, []);
  if (!avail) {
    return <div style={{ fontSize: 12.5, color: "var(--muted)", padding: "12px 0 0", borderTop: "1px solid var(--border-soft)", marginTop: 4 }}>{t("settings.printerNote")}</div>;
  }
  const sample = {
    receipt_no: "#TEST", offline: false, store: "SavdoOS", branch: "", cashier: "", date: new Date().toLocaleString("ru-RU"),
    items: [{ name: "Sinov mahsuloti", qty: 1, price: 1000, line: 1000 }], total: 1000, method: "cash", given: 1000, change: 0,
  };
  return (
    <div style={{ paddingTop: 12, borderTop: "1px solid var(--border-soft)", marginTop: 4 }}>
      <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{t("settings.printer")}</label>
      <select value={value || ""} onChange={(e) => onChange(e.target.value)} style={{ ...inputStyle, marginTop: 6 }}>
        <option value="">{t("settings.printerDefault")}</option>
        {printers.map((p) => <option key={p.name} value={p.name}>{p.displayName || p.name}</option>)}
      </select>
      <button className="btn btn-ghost" style={{ marginTop: 10, fontSize: 13, padding: "8px 14px" }} onClick={() => printReceipt(sample)}>{t("settings.testPrint")}</button>
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

function QrModeSelect({ value, xpayAvail, onChange }: { value: "manual" | "xpay"; xpayAvail: boolean; onChange: (m: "manual" | "xpay") => void }) {
  const t = useT();
  const opts: { key: "manual" | "xpay"; title: string; desc: string; locked?: boolean }[] = [
    { key: "manual", title: t("settings.qrManual"), desc: t("settings.qrManualDesc") },
    { key: "xpay", title: t("settings.qrXpay"), desc: xpayAvail ? t("settings.qrXpayDescOn") : t("settings.qrXpayDescOff"), locked: !xpayAvail },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 4 }}>
      {opts.map((o) => {
        const on = value === o.key;
        const disabled = !!o.locked;
        return (
          <button key={o.key} onClick={() => !disabled && onChange(o.key)} disabled={disabled}
            style={{ textAlign: "left", display: "flex", alignItems: "flex-start", gap: 12, padding: "13px 15px", borderRadius: 12, cursor: disabled ? "not-allowed" : "pointer", font: "inherit", background: on ? "var(--accent-soft)" : "var(--surface)", border: `1.5px solid ${on ? "var(--accent)" : "var(--border)"}`, opacity: disabled ? 0.6 : 1 }}>
            <span style={{ width: 20, height: 20, flex: "none", marginTop: 1, borderRadius: "50%", border: `2px solid ${on ? "var(--accent)" : "var(--border-input)"}`, background: on ? "var(--accent)" : "transparent", display: "flex", alignItems: "center", justifyContent: "center" }}>
              {on && <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#fff" }} />}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ display: "block", fontSize: 14, fontWeight: 600, color: on ? "var(--accent-strong)" : "var(--text)" }}>{o.title}{disabled ? ` · ${t("settings.qrOff")}` : ""}</span>
              <span style={{ display: "block", fontSize: 12.5, color: "var(--muted)", marginTop: 3, lineHeight: 1.5 }}>{o.desc}</span>
            </span>
          </button>
        );
      })}
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
