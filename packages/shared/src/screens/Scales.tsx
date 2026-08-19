import { useEffect, useRef, useState } from "react";
import {
  ArrowClockwise, ArrowLeft, ArrowRight, CaretRight, CheckCircle, Circle, Gear,
  Globe, Plug, Scales as ScalesIcon, Spinner, Trash, Warning, X,
} from "@phosphor-icons/react";
import { get, post, patch, del } from "@/lib/api";
import { fmt } from "@/lib/format";
import { Topbar, inputStyle, useGet } from "@/components/ui";
import { useT } from "@/lib/i18n";

const A = "#6d5dd3";

interface Scale {
  id: string; name: string; brand: string | null; model: string | null;
  connection_type: string; host: string | null; port: number | null; com_port: string | null;
  baud: number | null; status: string; synced_count: number; last_sync_at: string | null; is_active: boolean;
}
interface BrandDef { brand: string; models: string[] }
interface Probe { ok: boolean; brand: string | null; model: string | null; supported: boolean; message: string }
interface SyncItem { plu: string; name: string; price_per_kg: number }

// ── status pill ──────────────────────────────────────────────
function statusPill(t: (k: string) => string, status: string) {
  const map: Record<string, [string, string, string]> = {
    connected: ["var(--ok)", "var(--ok-soft)", t("scale.status_connected")],
    checking: ["var(--warn)", "var(--warn-soft)", t("scale.status_checking")],
    disconnected: ["var(--danger)", "var(--danger-soft)", t("scale.status_disconnected")],
  };
  const [c, bg, label] = map[status] || map.disconnected;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 12.5, fontWeight: 600, color: c, background: bg, padding: "5px 11px", borderRadius: 20 }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: c }} />{label}
    </span>
  );
}

function fmtSync(t: (k: string, v?: any) => string, iso: string | null): string {
  if (!iso) return t("scale.never");
  return new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function Scales() {
  const t = useT();
  const { data, reload } = useGet<Scale[]>("/scales");
  const [wizard, setWizard] = useState(false);
  const [settings, setSettings] = useState<Scale | null>(null);
  const scales = data || [];

  return (
    <main className="main">
      <Topbar title={t("scale.title")} sub={t("scale.sub")} right={
        <button className="btn btn-primary" style={{ display: "flex", alignItems: "center", gap: 7 }} onClick={() => setWizard(true)}>
          <ScalesIcon size={17} weight="fill" />{t("scale.add")}
        </button>
      } />
      <div className="scroll" style={{ flex: 1, padding: 24 }}>
        {scales.length === 0 ? (
          <div style={{ maxWidth: 460, margin: "60px auto 0", textAlign: "center" }}>
            <div style={{ width: 76, height: 76, margin: "0 auto 18px", borderRadius: 20, background: "var(--accent-soft)", color: A, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <ScalesIcon size={38} weight="fill" />
            </div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{t("scale.empty")}</div>
            <div style={{ fontSize: 13.5, color: "var(--muted)", marginTop: 6, lineHeight: 1.55 }}>{t("scale.emptyHint")}</div>
            <button className="btn btn-primary" style={{ marginTop: 20, display: "inline-flex", alignItems: "center", gap: 7 }} onClick={() => setWizard(true)}>
              <ScalesIcon size={17} weight="fill" />{t("scale.add")}
            </button>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 16 }}>
            {scales.map((s) => <ScaleCard key={s.id} scale={s} t={t} onSettings={() => setSettings(s)} onSynced={reload} />)}
          </div>
        )}
      </div>

      {wizard && <AddWizard t={t} onClose={() => setWizard(false)} onDone={() => { setWizard(false); reload(); }} />}
      {settings && <SettingsModal scale={settings} t={t} onClose={() => setSettings(null)} onChanged={reload} />}
    </main>
  );
}

// ── Scale card ───────────────────────────────────────────────
function ScaleCard({ scale, t, onSettings, onSynced }: { scale: Scale; t: (k: string, v?: any) => string; onSettings: () => void; onSynced: () => void }) {
  const [syncing, setSyncing] = useState(false);
  async function sync() {
    setSyncing(true);
    try { await post(`/scales/${scale.id}/sync`, {}); onSynced(); } catch { /* ignore */ } finally { setSyncing(false); }
  }
  const conn = scale.connection_type === "lan" ? scale.host : scale.com_port;
  return (
    <div className="card" style={{ padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 13 }}>
        <div style={{ width: 46, height: 46, flex: "none", borderRadius: 12, background: "var(--accent-soft)", color: A, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <ScalesIcon size={24} weight="fill" />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15.5, fontWeight: 700, letterSpacing: "-0.01em" }}>{scale.name}</div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>{[scale.brand, scale.model].filter(Boolean).join(" ") || "—"}</div>
        </div>
        {statusPill(t, scale.status)}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 7, fontSize: 12.5, color: "var(--text3)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {scale.connection_type === "lan" ? <Globe size={15} color="var(--muted)" /> : <Plug size={15} color="var(--muted)" />}
          <span className="tabular">{conn || "—"}{scale.connection_type === "lan" && scale.port ? `:${scale.port}` : ""}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <ArrowClockwise size={15} color="var(--muted)" />
          <span>{t("scale.lastSync")}: <b style={{ color: "var(--text2)", fontWeight: 600 }}>{fmtSync(t, scale.last_sync_at)}</b></span>
        </div>
      </div>
      <div style={{ display: "flex", gap: 9, marginTop: 2 }}>
        <button onClick={onSettings} style={{ flex: 1, height: 42, borderRadius: 11, border: "1px solid var(--border-input)", background: "var(--card)", color: "var(--text2)", cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: 7 }}>
          <Gear size={16} />{t("nav.sozlamalar")}
        </button>
        <button onClick={sync} disabled={syncing} style={{ flex: 1, height: 42, borderRadius: 11, border: "none", background: A, color: "#fff", cursor: syncing ? "default" : "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: 7, opacity: syncing ? 0.7 : 1 }}>
          <ArrowClockwise size={16} weight="bold" className={syncing ? "spin" : ""} />{syncing ? t("scale.syncing") : t("scale.sync")}
        </button>
      </div>
    </div>
  );
}

// ── Add-scale wizard ─────────────────────────────────────────
type Form = { name: string; brand: string; model: string; host: string; port: string; com_port: string; baud: string; data_bits: string; parity: string; stop_bits: string };

function AddWizard({ t, onClose, onDone }: { t: (k: string, v?: any) => string; onClose: () => void; onDone: () => void }) {
  const [step, setStep] = useState(1);
  const [mode, setMode] = useState<"lan" | "usb" | "">("");
  const [f, setF] = useState<Form>({ name: "", brand: "auto", model: "", host: "192.168.1.150", port: "3001", com_port: "", baud: "9600", data_bits: "8", parity: "None", stop_bits: "1" });
  const set = (patch: Partial<Form>) => { setF((x) => ({ ...x, ...patch })); if ("host" in patch || "port" in patch || "com_port" in patch || "baud" in patch) setProbe(null); };
  const [testing, setTesting] = useState(false);
  const [probe, setProbe] = useState<Probe | null>(null);
  const [ports, setPorts] = useState<{ port: string; label: string }[]>([]);
  const [manual, setManual] = useState(false);
  const [brands, setBrands] = useState<BrandDef[]>([]);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createErr, setCreateErr] = useState("");

  useEffect(() => { get<{ brands: BrandDef[] }>("/scales/brands").then((r) => setBrands(r.brands)).catch(() => {}); }, []);
  useEffect(() => { if (mode === "usb") loadPorts(); /* eslint-disable-next-line */ }, [mode]);
  async function loadPorts() { try { const r = await get<{ ports: any[] }>("/scales/ports"); setPorts(r.ports); } catch { /* ignore */ } }

  async function test() {
    setTesting(true); setProbe(null);
    try {
      const body = mode === "lan"
        ? { connection_type: "lan", host: f.host, port: +f.port || null, brand: f.brand }
        : { connection_type: "usb", com_port: f.com_port, baud: +f.baud || null, brand: f.brand };
      const r = await post<Probe>("/scales/test", body);
      setProbe(r);
      if (r.ok && r.brand && f.brand === "auto") set({ brand: r.brand, model: r.model || "" });
    } catch { setProbe({ ok: false, brand: null, model: null, supported: true, message: "—" }); } finally { setTesting(false); }
  }

  async function createScale() {
    if (creating) return;
    setCreating(true); setCreateErr("");
    try {
      const body: any = { name: f.name.trim() || t("scale.namePlaceholder"), brand: f.brand, model: f.model || (probe?.model ?? null), connection_type: mode };
      if (mode === "lan") { body.host = f.host; body.port = +f.port || null; }
      else { body.com_port = f.com_port; body.baud = +f.baud || null; body.data_bits = +f.data_bits || null; body.parity = f.parity; body.stop_bits = +f.stop_bits || null; }
      const r = await post<{ id: string }>("/scales", body);
      setCreatedId(r.id);
      setStep(4);
    } catch (e: any) { setCreateErr(e?.message || t("common.error")); } finally { setCreating(false); }
  }

  const stepTitle = step === 1 ? t("scale.w_howConnect") : step === 2 ? (mode === "usb" ? t("scale.selectConnected") : t("scale.w_selectDevice")) : step === 3 ? t("scale.w_brandModel") : t("scale.w_sync");
  const nextDisabled = creating || (step === 1 && !mode) || (step === 2 && !probe?.ok) || (step === 3 && !((f.brand && f.brand !== "auto" && (f.model || f.brand === "Other")) || (probe?.ok && probe.supported)));

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.55)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 30 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 528, maxHeight: "92vh", overflowY: "auto", background: "var(--card)", borderRadius: 20, padding: 26, boxShadow: "0 24px 60px rgba(0,0,0,0.4)" }}>
        {/* header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: A, background: "var(--accent-soft)", padding: "4px 11px", borderRadius: 20 }}>{t("scale.step", { n: step })}</span>
          <button onClick={onClose} style={{ width: 34, height: 34, border: "none", background: "var(--surface)", borderRadius: 9, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={16} /></button>
        </div>
        <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: "-0.02em", marginBottom: 20 }}>{stepTitle}</div>

        {/* STEP 1 — mode */}
        {step === 1 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {([["lan", Globe, t("scale.w_lan"), t("scale.w_lanDesc")], ["usb", Plug, t("scale.w_usb"), t("scale.w_usbDesc")]] as const).map(([key, Icon, title, desc]) => {
              const on = mode === key;
              return (
                <button key={key} onClick={() => { setMode(key); setProbe(null); }} style={{ textAlign: "left", display: "flex", alignItems: "center", gap: 15, padding: "18px 18px", borderRadius: 14, cursor: "pointer", font: "inherit", background: on ? "var(--accent-soft)" : "var(--surface)", border: `1.5px solid ${on ? A : "var(--border)"}` }}>
                  <div style={{ width: 48, height: 48, flex: "none", borderRadius: 12, background: on ? A : "var(--card)", color: on ? "#fff" : A, display: "flex", alignItems: "center", justifyContent: "center" }}><Icon size={24} weight="fill" /></div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 15, fontWeight: 700, color: on ? "var(--accent-strong)" : "var(--text)" }}>{title}</div>
                    <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2, lineHeight: 1.5 }}>{desc}</div>
                  </div>
                  <Circle size={20} weight={on ? "fill" : "regular"} color={on ? A : "var(--border-input)"} />
                </button>
              );
            })}
          </div>
        )}

        {/* STEP 2 — device / connection */}
        {step === 2 && mode === "lan" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Field label={t("scale.name")} value={f.name} onChange={(v) => set({ name: v })} placeholder={t("scale.namePlaceholder")} />
            <div>
              <Lbl>{t("scale.brandModel")}</Lbl>
              <select value={f.brand} onChange={(e) => set({ brand: e.target.value })} style={{ ...inputStyle, marginTop: 6 }}>
                <option value="auto">{t("scale.autoDetect")}</option>
                {brands.map((b) => <option key={b.brand} value={b.brand}>{b.brand}</option>)}
              </select>
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              <div style={{ flex: 2 }}><Field label={t("scale.ip")} value={f.host} onChange={(v) => set({ host: v })} placeholder="192.168.1.150" /></div>
              <div style={{ flex: 1 }}><Field label={t("scale.port")} value={f.port} onChange={(v) => set({ port: v.replace(/\D/g, "") })} placeholder="3001" /></div>
            </div>
            <TestBlock t={t} testing={testing} probe={probe} onTest={test} />
          </div>
        )}

        {step === 2 && mode === "usb" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {ports.map((p) => {
                const on = f.com_port === p.port;
                return (
                  <button key={p.port} onClick={() => set({ com_port: p.port })} style={{ textAlign: "left", display: "flex", alignItems: "center", gap: 11, padding: "13px 15px", borderRadius: 12, cursor: "pointer", font: "inherit", background: on ? "var(--accent-soft)" : "var(--surface)", border: `1.5px solid ${on ? A : "var(--border)"}` }}>
                    <Plug size={18} color={on ? A : "var(--muted)"} />
                    <span style={{ flex: 1, fontSize: 13.5, fontWeight: 600, color: on ? "var(--accent-strong)" : "var(--text2)" }}>{p.label}</span>
                    {on && <CheckCircle size={18} weight="fill" color={A} />}
                  </button>
                );
              })}
              {ports.length === 0 && <div style={{ padding: 18, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>—</div>}
            </div>
            <button onClick={loadPorts} style={{ alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 7, background: "none", border: "none", cursor: "pointer", font: "inherit", fontSize: 13, fontWeight: 600, color: A }}>
              <ArrowClockwise size={15} />{t("scale.refreshDevices")}
            </button>

            <button onClick={() => setManual((v) => !v)} style={{ marginTop: 2, display: "flex", alignItems: "center", justifyContent: "space-between", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 11, padding: "12px 14px", cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600, color: "var(--text3)" }}>
              {t("scale.manualSetup")}<CaretRight size={15} style={{ transform: manual ? "rotate(90deg)" : "none", transition: "transform .15s" }} />
            </button>
            {manual && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <Sel label={t("scale.port")} value={f.com_port} onChange={(v) => set({ com_port: v })} opts={ports.map((p) => p.port)} />
                <Sel label={t("scale.baud")} value={f.baud} onChange={(v) => set({ baud: v })} opts={["4800", "9600", "19200", "38400", "115200"]} />
                <Sel label={t("scale.dataBits")} value={f.data_bits} onChange={(v) => set({ data_bits: v })} opts={["7", "8"]} />
                <Sel label={t("scale.parity")} value={f.parity} onChange={(v) => set({ parity: v })} opts={["None", "Even", "Odd"]} />
                <Sel label={t("scale.stopBits")} value={f.stop_bits} onChange={(v) => set({ stop_bits: v })} opts={["1", "2"]} />
              </div>
            )}
            <TestBlock t={t} testing={testing} probe={probe} onTest={test} />
          </div>
        )}

        {/* STEP 3 — brand / model */}
        {step === 3 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {probe?.ok && probe.supported ? (
              <div style={{ display: "flex", alignItems: "center", gap: 13, padding: 16, borderRadius: 13, background: "var(--ok-soft)" }}>
                <CheckCircle size={26} weight="fill" color="var(--ok)" />
                <div><div style={{ fontSize: 14.5, fontWeight: 700, color: "var(--text)" }}>{f.brand === "auto" ? probe.brand : f.brand} {probe.model || f.model}</div><div style={{ fontSize: 12.5, color: "var(--ok)", fontWeight: 600, marginTop: 1 }}>{t("scale.contactOk")}</div></div>
              </div>
            ) : (
              <>
                {probe && !probe.supported && (
                  <div style={{ display: "flex", gap: 11, padding: "13px 15px", borderRadius: 12, background: "var(--warn-soft)", color: "var(--warn)" }}>
                    <Warning size={20} weight="fill" style={{ flex: "none", marginTop: 1 }} />
                    <div style={{ fontSize: 12.5, lineHeight: 1.5 }}>{t("scale.unsupported")}</div>
                  </div>
                )}
                <div>
                  <Lbl>{t("scale.pickBrand")}</Lbl>
                  <select value={f.brand === "auto" ? "" : f.brand} onChange={(e) => set({ brand: e.target.value, model: "" })} style={{ ...inputStyle, marginTop: 6 }}>
                    <option value="" disabled>{t("scale.pickBrand")}</option>
                    {brands.map((b) => <option key={b.brand} value={b.brand}>{b.brand}</option>)}
                    <option value="Other">{t("scale.otherBrand")}</option>
                  </select>
                </div>
                <div>
                  <Lbl>{t("scale.pickModel")}</Lbl>
                  {f.brand === "Other" ? (
                    <input value={f.model} onChange={(e) => set({ model: e.target.value })} placeholder={t("scale.model")} style={{ ...inputStyle, marginTop: 6 }} />
                  ) : (
                    <select value={f.model} onChange={(e) => set({ model: e.target.value })} style={{ ...inputStyle, marginTop: 6 }}>
                      <option value="" disabled>{t("scale.pickModel")}</option>
                      {(brands.find((b) => b.brand === f.brand)?.models || []).map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                  )}
                </div>
              </>
            )}
            <div style={{ fontSize: 11.5, color: "var(--muted)", lineHeight: 1.5, padding: "0 2px" }}>{t("scale.supportNote")}</div>
          </div>
        )}

        {/* STEP 4 — sync */}
        {step === 4 && <SyncStep t={t} scaleId={createdId!} onDone={onDone} />}

        {/* footer nav (steps 1-3) */}
        {step < 4 && (
          <>
            {createErr && <div style={{ marginTop: 16, padding: "11px 14px", borderRadius: 11, background: "var(--danger-soft)", color: "var(--danger)", fontSize: 13 }}>{createErr}</div>}
            <div style={{ display: "flex", gap: 10, marginTop: createErr ? 12 : 24 }}>
              <button onClick={() => (step === 1 ? onClose() : setStep(step - 1))} style={{ flex: 1, height: 50, borderRadius: 12, border: "1px solid var(--border-input)", background: "var(--card)", color: "var(--text3)", cursor: "pointer", font: "inherit", fontSize: 14, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: 7 }}>
                {step > 1 && <ArrowLeft size={16} />}{step === 1 ? t("common.cancel") : t("scale.back")}
              </button>
              <button
                disabled={nextDisabled}
                onClick={() => (step === 3 ? createScale() : setStep(step + 1))}
                style={{ flex: 1.4, height: 50, borderRadius: 12, border: "none", cursor: nextDisabled ? "default" : "pointer", font: "inherit", fontSize: 14, fontWeight: 700, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, background: nextDisabled ? "#c9ccd8" : A }}>
                {creating ? <Spinner size={16} className="spin" /> : <>{t("scale.continue")}<ArrowRight size={16} weight="bold" /></>}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Step 4 body ──────────────────────────────────────────────
function SyncStep({ t, scaleId, onDone }: { t: (k: string, v?: any) => string; scaleId: string; onDone: () => void }) {
  const [items, setItems] = useState<SyncItem[] | null>(null);
  const [pct, setPct] = useState(0);
  const [state, setState] = useState<"idle" | "running" | "done">("idle");
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => { get<{ items: SyncItem[] }>("/scales/sync-preview").then((r) => setItems(r.items)).catch(() => setItems([])); }, []);
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  async function run() {
    setState("running"); setPct(0); setFailed(false);
    timer.current = setInterval(() => setPct((p) => (p < 90 ? p + 6 : p)), 90);
    try {
      await post(`/scales/${scaleId}/sync`, {});
      if (timer.current) { clearInterval(timer.current); timer.current = null; }
      setPct(100); setState("done");
    } catch {
      if (timer.current) { clearInterval(timer.current); timer.current = null; }
      setState("idle"); setFailed(true);
    }
  }

  if (items === null) return <div style={{ padding: 30, textAlign: "center", color: "var(--muted)" }}><Spinner size={22} className="spin" /></div>;

  if (state === "done") {
    return (
      <div style={{ textAlign: "center", padding: "10px 4px" }}>
        <div style={{ width: 76, height: 76, margin: "0 auto 16px", borderRadius: "50%", background: "var(--ok-soft)", color: "var(--ok)", display: "flex", alignItems: "center", justifyContent: "center" }}><CheckCircle size={40} weight="fill" /></div>
        <div style={{ fontSize: 18, fontWeight: 700 }}>{t("scale.syncDone", { n: items.length })}</div>
        <button className="btn btn-primary" style={{ width: "100%", height: 50, marginTop: 22 }} onClick={onDone}>{t("scale.finish")}</button>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div>
        <div style={{ textAlign: "center", padding: "24px 10px", background: "var(--surface)", borderRadius: 14 }}>
          <div style={{ fontSize: 14.5, fontWeight: 600 }}>{t("scale.noWeighted")}</div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 6, lineHeight: 1.5 }}>{t("scale.noWeightedHint")}</div>
        </div>
        <button className="btn btn-primary" style={{ width: "100%", height: 50, marginTop: 20 }} onClick={onDone}>{t("scale.finish")}</button>
      </div>
    );
  }

  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>{t("scale.w_syncDesc")}</div>
      <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 16 }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ background: "var(--card-alt)", textAlign: "left", color: "var(--muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            <th style={{ padding: "11px 16px", fontWeight: 600 }}>{t("sales.thProduct")}</th>
            <th style={{ padding: "11px 10px", fontWeight: 600 }}>{t("scale.thPlu")}</th>
            <th style={{ padding: "11px 16px", fontWeight: 600, textAlign: "right" }}>{t("scale.thPricePerKg")}</th>
          </tr></thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i} style={{ borderTop: "1px solid var(--border-soft)", fontSize: 13.5 }}>
                <td style={{ padding: "11px 16px", fontWeight: 600 }}>{it.name}</td>
                <td style={{ padding: "11px 10px", color: "var(--text3)" }} className="tabular">{it.plu}</td>
                <td style={{ padding: "11px 16px", textAlign: "right", fontWeight: 700 }} className="tabular">{fmt(it.price_per_kg)}{t("prod2.perKg")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {state === "running" ? (
        <div>
          <div style={{ fontSize: 13, color: "var(--text3)", marginBottom: 8 }}>{t("scale.syncingProducts")}</div>
          <div style={{ height: 10, borderRadius: 6, background: "var(--surface)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${pct}%`, background: A, borderRadius: 6, transition: "width .15s" }} />
          </div>
        </div>
      ) : (
        <>
          {failed && <div style={{ marginBottom: 12, padding: "11px 14px", borderRadius: 11, background: "var(--danger-soft)", color: "var(--danger)", fontSize: 13 }}>{t("common.error")}</div>}
          <button className="btn btn-primary" style={{ width: "100%", height: 50 }} onClick={run}>{failed ? t("common.retry") : t("scale.syncN", { n: items.length })}</button>
        </>
      )}
    </div>
  );
}

// ── Test-connection block (used in step 2) ───────────────────
function TestBlock({ t, testing, probe, onTest }: { t: (k: string, v?: any) => string; testing: boolean; probe: Probe | null; onTest: () => void }) {
  return (
    <div>
      <button onClick={onTest} disabled={testing} style={{ width: "100%", height: 46, borderRadius: 11, border: `1.5px solid ${A}`, background: "var(--accent-soft)", color: "var(--accent-strong)", cursor: testing ? "default" : "pointer", font: "inherit", fontSize: 14, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
        {testing ? <Spinner size={17} className="spin" /> : <Globe size={17} />}{testing ? t("scale.testing") : t("scale.testConnection")}
      </button>
      {probe && probe.ok && (
        <div style={{ marginTop: 12, padding: 15, borderRadius: 13, background: "var(--ok-soft)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 700, color: "var(--text)" }}><CheckCircle size={18} weight="fill" color="var(--ok)" />{t("scale.found")}</div>
          <div style={{ display: "flex", gap: 22, marginTop: 10 }}>
            <div><div style={{ fontSize: 11, color: "var(--muted)" }}>{t("scale.brand")}</div><div style={{ fontSize: 13.5, fontWeight: 700 }}>{probe.brand || "—"}</div></div>
            <div><div style={{ fontSize: 11, color: "var(--muted)" }}>{t("scale.model")}</div><div style={{ fontSize: 13.5, fontWeight: 700 }}>{probe.model || "—"}</div></div>
          </div>
        </div>
      )}
      {probe && !probe.ok && (
        <div style={{ marginTop: 12, padding: "12px 14px", borderRadius: 12, background: "var(--danger-soft)", color: "var(--danger)", fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
          <Warning size={17} weight="fill" />{probe.message || t("scale.status_disconnected")}
        </div>
      )}
    </div>
  );
}

// ── Per-scale settings modal ─────────────────────────────────
function SettingsModal({ scale, t, onClose, onChanged }: { scale: Scale; t: (k: string, v?: any) => string; onClose: () => void; onChanged: () => void }) {
  const [name, setName] = useState(scale.name);
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);

  async function save() { setBusy(true); try { await patch(`/scales/${scale.id}`, { name }); onChanged(); onClose(); } catch { /* ignore */ } finally { setBusy(false); } }
  async function syncNow() { setSyncing(true); try { await post(`/scales/${scale.id}/sync`, {}); onChanged(); } catch { /* ignore */ } finally { setSyncing(false); } }
  async function disconnect() { try { await patch(`/scales/${scale.id}`, { status: "disconnected" }); onChanged(); onClose(); } catch { /* ignore */ } }
  async function remove() { if (!window.confirm(t("scale.removeConfirm", { name: scale.name }))) return; try { await del(`/scales/${scale.id}`); onChanged(); onClose(); } catch { /* ignore */ } }

  const conn = scale.connection_type === "lan" ? `${scale.host || "—"}${scale.port ? ":" + scale.port : ""}` : (scale.com_port || "—");

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(8,10,18,0.55)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 30 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 460, maxHeight: "92vh", overflowY: "auto", background: "var(--card)", borderRadius: 20, padding: 26, boxShadow: "0 24px 60px rgba(0,0,0,0.4)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
          <div style={{ fontSize: 19, fontWeight: 700 }}>{t("scale.settingsTitle")}</div>
          <button onClick={onClose} style={{ width: 34, height: 34, border: "none", background: "var(--surface)", borderRadius: 9, cursor: "pointer", color: "var(--muted)", display: "flex", alignItems: "center", justifyContent: "center" }}><X size={16} /></button>
        </div>

        <Field label={t("scale.name")} value={name} onChange={setName} />

        <Sec title={t("scale.secConnection")}>
          <Row2 k={t("scale.connType")} v={scale.connection_type.toUpperCase()} />
          <Row2 k={scale.connection_type === "lan" ? t("scale.ip") : t("scale.port")} v={conn} />
          <Row2 k={t("scale.statusLabel")} v={statusPill(t, scale.status)} />
        </Sec>

        <Sec title={t("scale.secDevice")}>
          <Row2 k={t("scale.brand")} v={scale.brand || "—"} />
          <Row2 k={t("scale.model")} v={scale.model || "—"} />
          <Row2 k={t("scale.driver")} v={scale.brand || "generic"} />
        </Sec>

        <Sec title={t("scale.secSync")}>
          <Row2 k={t("scale.lastSync")} v={fmtSync(t, scale.last_sync_at)} />
          <Row2 k={t("scale.syncedProducts")} v={String(scale.synced_count)} />
          <button onClick={syncNow} disabled={syncing} className="btn btn-primary" style={{ width: "100%", height: 44, marginTop: 8, display: "flex", alignItems: "center", justifyContent: "center", gap: 7 }}>
            <ArrowClockwise size={16} weight="bold" className={syncing ? "spin" : ""} />{syncing ? t("scale.syncing") : t("scale.syncNow")}
          </button>
        </Sec>

        <div style={{ fontSize: 12, fontWeight: 700, color: "var(--danger)", textTransform: "uppercase", letterSpacing: "0.05em", margin: "20px 0 10px" }}>{t("scale.dangerZone")}</div>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={disconnect} style={{ flex: 1, height: 44, borderRadius: 11, border: "1px solid var(--border-input)", background: "var(--card)", color: "var(--text3)", cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 600 }}>{t("scale.disconnect")}</button>
          <button onClick={remove} style={{ flex: 1, height: 44, borderRadius: 11, border: "none", background: "var(--danger-soft)", color: "var(--danger)", cursor: "pointer", font: "inherit", fontSize: 13.5, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", gap: 7 }}><Trash size={16} />{t("scale.remove")}</button>
        </div>

        <button onClick={save} disabled={busy} className="btn btn-primary" style={{ width: "100%", height: 50, marginTop: 18 }}>{busy ? "…" : t("common.save")}</button>
      </div>
    </div>
  );
}

// ── small helpers ────────────────────────────────────────────
function Lbl({ children }: { children: React.ReactNode }) { return <label style={{ fontSize: 12.5, color: "var(--text3)", fontWeight: 600 }}>{children}</label>; }
function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (<div style={{ marginBottom: 4 }}><Lbl>{label}</Lbl><input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} style={{ ...inputStyle, marginTop: 6 }} /></div>);
}
function Sel({ label, value, onChange, opts }: { label: string; value: string; onChange: (v: string) => void; opts: string[] }) {
  return (<div><Lbl>{label}</Lbl><select value={value} onChange={(e) => onChange(e.target.value)} style={{ ...inputStyle, marginTop: 6 }}>{opts.map((o) => <option key={o} value={o}>{o}</option>)}</select></div>);
}
function Sec({ title, children }: { title: string; children: React.ReactNode }) {
  return (<div style={{ marginTop: 18 }}><div style={{ fontSize: 13, fontWeight: 700, color: "var(--text2)", marginBottom: 8 }}>{title}</div><div style={{ display: "flex", flexDirection: "column", gap: 2 }}>{children}</div></div>);
}
function Row2({ k, v }: { k: string; v: React.ReactNode }) {
  return (<div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 0", borderTop: "1px solid var(--border-soft)", fontSize: 13.5 }}><span style={{ color: "var(--muted)" }}>{k}</span><span style={{ fontWeight: 600, color: "var(--text2)" }}>{v}</span></div>);
}
